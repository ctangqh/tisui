"""坐标缓存 (loop-design.md §5.5-§5.7)。

定位是链路里 token 消耗最大的环节。同一页面反复探索时 stable 区域元素坐标基本不变,
缓存命中直接免 VLM 定位。

总原则 (§5 总章): 缓存/加速不得改变测试语义。任何缓存路径必须通过视觉校验
(region_hash / crop_hash) 才允许操作 —— 视觉校验是语义守门员, 不是可选优化。

分级缓存 (§5.5):
  - stable   区域: 菜单栏/Tab 栏/工具栏/对话框按钮区等 → 积极长期缓存
  - volatile 区域: 列表/信息流/轮播/广告/图表 → 永远不缓存, 直落 VLM

三级命中 (§5.6, 每级失败无感降级, 成功均回写):
  ① native_ref → 原生接口查实时 rect → crop_hash 视觉校验 → click (毫秒级, 零 token)
  ② 缓存 bbox + crop_hash 元素级视觉校验 → click (毫秒级, 零 token)
  ③ VLM 定位 → 操作 → 回写 bbox/crop_hash/region_hash + 反查 native_ref

前置门槛 (region-level gate):
  volatile 区域直接落 ③; stable 区域先 region_hash 整区 pHash 校验, 不通过则
  该区域全部元素失效 + miss_count+1 (连续 3 次 → region 降级 volatile), 其余区域不受牵连。

失效粒度: 整页/区域/元素三级, 不会因为一条搜索结果刷新就让菜单栏作废。
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from PIL import Image

from tisui.agent.explore.page_identity import BBox, perceptual_hash, hamming_prefix
from tisui.shared.config import CACHE_ROOT
from tisui.shared.logger import logger

Coordinate = tuple[int, int]
_LO_CACHE_NAMESPACE = "locate"
_REGION_HASH_BITS_THRESHOLD = 8   # region 级 pHash 汉明距离 ≤8 判视觉一致
_CROP_HASH_BITS_THRESHOLD = 4     # 元素裁片 pHash 汉明距离 ≤4 判视觉一致
_REGION_MISS_BEFORE_VOLATILE = 3  # 连续 3 次 region 校验不过 → 降级 volatile
_REGION_IOU_MATCH = 0.55          # bbox 区域 IOU ≥ 此值时视为同一个 region (VLM 每次输出略有抖动)
_VIEWPORT_KEY = "viewport"


@dataclass
class CachedElement:
    bbox: BBox
    crop_hash: str
    native_ref: dict[str, Any] | None = None  # {kind, value} → 传 resolve_native_ref
    hits: int = 0
    last_verified: str = ""  # ISO time string


@dataclass
class CachedRegion:
    region_id: str
    kind: str
    stability: str                     # "stable" | "volatile"
    bbox: BBox
    region_hash: str
    miss_count: int = 0
    elements: dict[str, CachedElement] = field(default_factory=dict)


@dataclass
class PageLocateCache:
    page_title: str = ""
    viewport: tuple[int, int] = (0, 0)
    regions: list[CachedRegion] = field(default_factory=list)


class LocateCacheStore:
    """<cache_root>/locate/<cache_key>/<page_id>.json 读写 + 三级命中。

    构造方式:
        store = LocateCacheStore(cache_key="settings-app")  # 与 memory_cache 同名
        ...
        store.save(page_id)  或  store.close() 全部整写
    """

    def __init__(self, cache_key: str | None) -> None:
        """cache_key=None 时完全不读写磁盘, 纯空实现, explorer 可无分支调用。"""
        if cache_key:
            self._root: Path | None = Path(CACHE_ROOT) / _LO_CACHE_NAMESPACE / cache_key
            self._root.mkdir(parents=True, exist_ok=True)
        else:
            self._root = None
        self._loaded: dict[str, PageLocateCache] = {}

    # ---------- 基础: 加载/保存 ------------------------------------------

    def _page_file(self, page_id: str) -> Path:
        assert self._root is not None
        return self._root / f"{page_id}.json"

    def _load(self, page_id: str) -> PageLocateCache:
        if page_id in self._loaded:
            return self._loaded[page_id]
        pc = PageLocateCache()
        if self._root is not None:
            fp = self._page_file(page_id)
            if fp.exists():
                try:
                    import json
                    raw = json.loads(fp.read_text(encoding="utf-8"))
                    pc.page_title = str(raw.get("page_title") or "")
                    vp = raw.get(_VIEWPORT_KEY) or [0, 0]
                    pc.viewport = (int(vp[0]), int(vp[1])) if isinstance(vp, (list, tuple)) and len(vp) == 2 else (0, 0)
                    for r in raw.get("regions") or []:
                        elems: dict[str, CachedElement] = {}
                        for name, ed in (r.get("elements") or {}).items():
                            bb = ed.get("bbox") or [0, 0, 0, 0]
                            elems[name] = CachedElement(
                                bbox=(int(bb[0]), int(bb[1]), int(bb[2]), int(bb[3])),
                                crop_hash=str(ed.get("crop_hash") or ""),
                                native_ref=ed.get("native_ref"),
                                hits=int(ed.get("hits") or 0),
                                last_verified=str(ed.get("last_verified") or ""),
                            )
                        rbb = r.get("bbox") or [0, 0, 0, 0]
                        pc.regions.append(CachedRegion(
                            region_id=str(r.get("region_id") or ""),
                            kind=str(r.get("kind") or ""),
                            stability=str(r.get("stability") or "volatile"),
                            bbox=(int(rbb[0]), int(rbb[1]), int(rbb[2]), int(rbb[3])),
                            region_hash=str(r.get("region_hash") or ""),
                            miss_count=int(r.get("miss_count") or 0),
                            elements=elems,
                        ))
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"locate_cache 加载 {page_id} 失败: {type(exc).__name__}: {exc}")
        self._loaded[page_id] = pc
        return pc

    def save(self, page_id: str) -> None:
        if self._root is None or page_id not in self._loaded:
            return
        pc = self._loaded[page_id]
        obj: dict[str, Any] = {
            "page_title": pc.page_title,
            _VIEWPORT_KEY: list(pc.viewport),
            "regions": [],
        }
        for r in pc.regions:
            obj["regions"].append({
                "region_id": r.region_id,
                "kind": r.kind,
                "stability": r.stability,
                "bbox": list(r.bbox),
                "region_hash": r.region_hash,
                "miss_count": r.miss_count,
                "elements": {
                    name: {
                        "bbox": list(e.bbox),
                        "crop_hash": e.crop_hash,
                        "native_ref": e.native_ref,
                        "hits": e.hits,
                        "last_verified": e.last_verified,
                    }
                    for name, e in r.elements.items()
                },
            })
        fp = self._page_file(page_id)
        import json
        import os
        import tempfile
        fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=str(fp.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, fp)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def close(self) -> None:
        for pid in list(self._loaded):
            try:
                self.save(pid)
            except Exception:  # noqa: BLE001
                pass
        self._loaded.clear()

    # ---------- 对外: 查找命中 ------------------------------------------

    def try_locate(
        self,
        device: Any,
        image_bytes: bytes,
        *,
        page_id: str,
        element_desc: str,
        regions_from_vlm: list[dict[str, Any]] | None = None,
    ) -> Optional[tuple[Coordinate, BBox]]:
        """尝试在缓存三级命中等价找到元素坐标。

        - 返回 ((x, y), bbox): 已通过视觉校验, explorer 可以直接 `device.click(pt)`;
          随附的 bbox 是实时校验后的元素框 (原生 ref 时为实时 rect), 报告框选用。
        - 返回 None: 未命中 / 校验不通过 / volatile 区域 / cache_key=None。
          explorer 走完整 VLM 管线, 之后调用 `record_locate_success` 回写。
        """
        if self._root is None:
            return None
        pc = self._load(page_id)

        # viewport 变化 → 整页作废 (§5.6 最后表, 不做不可靠的 DPI 缩放换算)
        w, h = _image_size(image_bytes)
        if pc.viewport == (0, 0):
            pc.viewport = (w, h)
        elif pc.viewport != (w, h):
            pc.regions.clear()
            pc.viewport = (w, h)

        desc = (element_desc or "").strip()
        if not desc:
            return None

        # Step 0: 匹配当前页 regions 与 VLM 输出 regions (确定稳定性与 bbox)
        # volatile 区域直落 ③。stable 区域 region_hash 先校验一次, 校验不过该区域整区失效。
        matched_region = _match_region(pc, regions_from_vlm or [], desc)
        if matched_region is None:
            return None  # 没落在已知 stable region, 让 VLM 重定位
        reg, region_bbox = matched_region
        if reg.stability != "stable":
            return None
        cur_region_hash = _crop_phex(image_bytes, region_bbox)
        if reg.region_hash:
            if hamming_prefix(cur_region_hash, reg.region_hash) > _REGION_HASH_BITS_THRESHOLD:
                reg.miss_count += 1
                if reg.miss_count >= _REGION_MISS_BEFORE_VOLATILE:
                    reg.stability = "volatile"
                    logger.debug(f"locate_cache region {reg.region_id!r} 降级 volatile")
                reg.elements.clear()
                reg.region_hash = cur_region_hash  # 视觉已变, 锚点换成当前
                return None
        reg.region_hash = cur_region_hash
        reg.miss_count = 0

        elem = reg.elements.get(desc)
        if elem is None:
            return None

        # ① native_ref: 原生接口查实时 rect + crop_hash 视觉校验
        if elem.native_ref is not None:
            ref = elem.native_ref
            kind = str(ref.get("kind") or "")
            value = ref.get("value")
            if kind and value is not None:
                rect_fn = getattr(device, "rect_by_native_ref", None)
                if callable(rect_fn):
                    try:
                        real = rect_fn(ref)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug(f"locate_cache ① rect_by_native_ref 失败: {exc}")
                        real = None
                    if _is_valid_bbox(real):
                        cur_crop = _crop_phex(image_bytes, _as_bbox(real))
                        if hamming_prefix(cur_crop, elem.crop_hash) <= _CROP_HASH_BITS_THRESHOLD:
                            cx = (real[0] + real[2]) // 2
                            cy = (real[1] + real[3]) // 2
                            elem.bbox = _as_bbox(real)
                            elem.crop_hash = cur_crop
                            elem.hits += 1
                            elem.last_verified = time.strftime("%Y-%m-%dT%H:%M:%S")
                            return ((cx, cy), list(elem.bbox))

        # ② 缓存 bbox + crop_hash
        cur_crop = _crop_phex(image_bytes, elem.bbox)
        if hamming_prefix(cur_crop, elem.crop_hash) <= _CROP_HASH_BITS_THRESHOLD:
            cx = (elem.bbox[0] + elem.bbox[2]) // 2
            cy = (elem.bbox[1] + elem.bbox[3]) // 2
            elem.hits += 1
            elem.last_verified = time.strftime("%Y-%m-%dT%H:%M:%S")
            return ((cx, cy), list(elem.bbox))

        # 校验不通过: 驱逐该元素, 走 ③
        del reg.elements[desc]
        return None

    # ---------- 对外: 回写成功定位结果 -----------------------------------

    def record_locate_success(
        self,
        device: Any,
        image_bytes: bytes,
        *,
        page_id: str,
        page_title: str = "",
        element_desc: str,
        bbox: BBox,
        regions_from_vlm: list[dict[str, Any]] | None = None,
    ) -> None:
        """VLM 定位成功后调用。回写 bbox + crop_hash + region_hash + 反查 native_ref。

        仅 stable 区域写入缓存; volatile 区域 elements 永远为空, 从源头消除误点。
        """
        if self._root is None:
            return
        if not _is_valid_bbox(bbox):
            return
        pc = self._load(page_id)
        if page_title:
            pc.page_title = page_title
        if pc.viewport == (0, 0):
            pc.viewport = _image_size(image_bytes)
        desc = (element_desc or "").strip()
        if not desc:
            return
        reg = _ensure_region_for_element(pc, regions_from_vlm or [], bbox)
        if reg.stability != "stable":
            return  # 不写 volatile
        cur_region_hash = _crop_phex(image_bytes, reg.bbox)
        if reg.region_hash and cur_region_hash != reg.region_hash:
            if hamming_prefix(cur_region_hash, reg.region_hash) > _REGION_HASH_BITS_THRESHOLD:
                reg.elements.clear()
        reg.region_hash = cur_region_hash

        native_ref = None
        resolve = getattr(device, "resolve_native_ref", None)
        if callable(resolve):
            cx = (bbox[0] + bbox[2]) // 2
            cy = (bbox[1] + bbox[3]) // 2
            try:
                ref = resolve((cx, cy))
            except Exception as exc:  # noqa: BLE001
                ref = None
                logger.debug(f"locate_cache resolve_native_ref 失败: {exc}")
            if isinstance(ref, dict) and _stable_native_ref(ref):
                native_ref = {
                    "kind": str(ref.get("kind") or ""),
                    "value": ref.get("value"),
                }
        elem = reg.elements.get(desc)
        cur_crop = _crop_phex(image_bytes, bbox)
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        if elem is None:
            reg.elements[desc] = CachedElement(
                bbox=tuple(bbox),  # type: ignore[arg-type]
                crop_hash=cur_crop,
                native_ref=native_ref,
                hits=1,
                last_verified=now,
            )
        else:
            elem.bbox = tuple(bbox)  # type: ignore[arg-type]
            elem.crop_hash = cur_crop
            if native_ref is not None:
                elem.native_ref = native_ref
            elem.last_verified = now

    def evict_element(self, page_id: str, element_desc: str) -> None:
        """缓存命中后动作仍无效: 驱逐该元素。"""
        if self._root is None or page_id not in self._loaded:
            return
        desc = (element_desc or "").strip()
        for r in self._loaded[page_id].regions:
            r.elements.pop(desc, None)


# ---------- 内部: 区域匹配/创建 -----------------------------------------


def _match_region(
    pc: PageLocateCache,
    vlm_regions: list[dict[str, Any]],
    element_desc: str,
) -> Optional[tuple[CachedRegion, BBox]]:
    """在已有缓存 regions 中找包含该元素描述的稳定区; 找不到返回 None。"""
    # 优先: VLM regions 匹配已有 regions, 看元素描述落在哪个 VLM region 里
    # 这里缺少元素坐标, 退化为: 若 VLM region 稳定且已有同名 cached region, 就用它;
    # 否则扫描所有 cached stable region, 只要名字 (element_desc) 存在就返回。
    for r in pc.regions:
        if r.stability == "stable" and element_desc in r.elements:
            return r, r.bbox
    return None


def _ensure_region_for_element(
    pc: PageLocateCache,
    vlm_regions: list[dict[str, Any]],
    elem_bbox: BBox,
) -> CachedRegion:
    """VLM 定位成功后, 决定把元素写进哪个 region; volatile 时返回 volatile region (但最终不会写)。"""
    # 找到包含元素 bbox 且在 VLM regions 里稳定性为 stable 的最小 region
    cx = (elem_bbox[0] + elem_bbox[2]) // 2
    cy = (elem_bbox[1] + elem_bbox[3]) // 2
    chosen_vlm: dict[str, Any] | None = None
    chosen_area = float("inf")
    for v in vlm_regions or []:
        bb = v.get("bbox")
        if not (isinstance(bb, (list, tuple)) and len(bb) == 4):
            continue
        x1, y1, x2, y2 = (int(bb[0]), int(bb[1]), int(bb[2]), int(bb[3]))
        if x2 <= x1 or y2 <= y1:
            continue
        if not (x1 <= cx <= x2 and y1 <= cy <= y2):
            continue
        area = (x2 - x1) * (y2 - y1)
        if area < chosen_area:
            chosen_area = area
            chosen_vlm = v
    if chosen_vlm is not None:
        stability = "stable" if str(chosen_vlm.get("stability") or "").lower() == "stable" else "volatile"
        vbb: BBox = (
            int(chosen_vlm["bbox"][0]), int(chosen_vlm["bbox"][1]),
            int(chosen_vlm["bbox"][2]), int(chosen_vlm["bbox"][3]),
        )
        # 找已有 cached region 与之匹配 (同 kind + 同 stability + bbox IOU ≥ 阈值)
        for r in pc.regions:
            if r.kind == str(chosen_vlm.get("kind") or "") and r.stability == stability \
                    and _iou(r.bbox, vbb) >= _REGION_IOU_MATCH:
                return r
        rid = f"{chosen_vlm.get('kind') or 'region'}_{len(pc.regions)}"
        region = CachedRegion(
            region_id=str(chosen_vlm.get("region_id") or rid),
            kind=str(chosen_vlm.get("kind") or ""),
            stability=stability,
            bbox=vbb,
            region_hash="",
        )
        pc.regions.append(region)
        return region
    # 没 VLM region 信息: 创建一个整屏 stable? —— 太危险, 改判 volatile 不缓存
    for r in pc.regions:
        if r.kind == "_unknown":
            return r
    fallback = CachedRegion(
        region_id=f"_unknown_{len(pc.regions)}",
        kind="_unknown",
        stability="volatile",
        bbox=(0, 0, 1, 1),
        region_hash="",
    )
    pc.regions.append(fallback)
    return fallback


# ---------- 工具 ---------------------------------------------------------


def _crop_phex(image_bytes: bytes, bbox: BBox) -> str:
    """裁指定区域算 pHash 前缀 16 字符 (64 bit)。"""
    x1, y1, x2, y2 = bbox
    if x2 <= x1 or y2 <= y1:
        return ""
    with Image.open(io.BytesIO(image_bytes)) as img:
        x1 = max(0, x1); y1 = max(0, y1)
        x2 = min(img.width, x2); y2 = min(img.height, y2)
        if x2 <= x1 or y2 <= y1:
            return ""
        cropped = img.crop((x1, y1, x2, y2)).convert("L")
        buf = io.BytesIO()
        cropped.save(buf, format="PNG")
        return perceptual_hash(buf.getvalue())


def _image_size(image_bytes: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(image_bytes)) as img:
        return img.width, img.height


def _is_valid_bbox(b: Any) -> bool:
    if not isinstance(b, (list, tuple)) or len(b) != 4:
        return False
    try:
        x1, y1, x2, y2 = (int(v) for v in b)
    except (TypeError, ValueError):
        return False
    return x2 > x1 and y2 > y1


def _as_bbox(b: Sequence[Any]) -> BBox:
    return (int(b[0]), int(b[1]), int(b[2]), int(b[3]))


def _iou(a: BBox, b: BBox) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return (inter / union) if union > 0 else 0.0


def _stable_native_ref(ref: dict[str, Any]) -> bool:
    """§5.7 稳定性判据: 宁缺勿存。非稳定选择器一律返回 False 不缓存 native_ref。"""
    kind = str(ref.get("kind") or "").strip().lower()
    value = ref.get("value")
    if value is None:
        return False
    if kind in ("automation_id", "data-testid", "data_testid", "data-test-id"):
        return bool(str(value).strip())
    if kind == "id":
        return bool(str(value).strip())
    if kind == "css":
        s = str(value)
        bad = (":nth-child", "nth-of-type", "> :nth", ":eq(", ":lt(", ":gt(")
        return all(tok not in s for tok in bad) and ("#" in s or "[id=" in s or ".cls-" in s or "[class*=" in s)
    if kind == "by_id" or kind == "hypium_id":
        return bool(str(value).strip())
    if kind == "hypium_text":
        # 文本可能变, 允许但低优先级 (保留策略, 这里直接存储, 命中率由 miss_count 自限)
        return bool(str(value).strip())
    return False


__all__ = [
    "BBox",
    "Coordinate",
    "CachedElement",
    "CachedRegion",
    "PageLocateCache",
    "LocateCacheStore",
]
