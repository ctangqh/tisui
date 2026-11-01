"""页面身份识别 (loop-design.md §5.3)。

跨运行匹配「这个页面我来过」。三条原则:
1. 误判方向偏向"新页面": 任何拿不准的情况判新页 (不漏探索才致命)
2. 识别成本接近零: 纯本地 URL / pHash 计算, VLM 标题来自已有的观察规划输出
3. 指纹取结构而非内容: 只拼合 stable 区域, 滚动/轮播/广告不改变身份

page_id 只在首次发现时生成一次 (`hash(title + pHash 前缀)`), 之后靠匹配复用,
绝不重算。锚点存入 ExploreState.visited_pages, 持久化由 memory.py 接管。
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from PIL import Image  # explorer 已用到 PIL, 这里直接复用

_PHASH_SIZE = 8
_PHASH_BITS = _PHASH_SIZE * _PHASH_SIZE
_PHASH_HAMMING_THRESHOLD = 8  # 64-bit: ≤8 位不同视为同页 (汉明距离粗筛阈值)

# URL query 参数中属于易变噪声的键 (忽略大小写, 前缀匹配)
_NOISY_QUERY_KEYS_RE = re.compile(
    r"(?:^|_)(?:session|token|sid|uid|sign|signature|ts|time|t|timestamp|nonce|random|rand|_"
    r"v|version|_x|_t|hash|h|callback|cb|_|requestid|reqid|traceid|trackid)",
    re.IGNORECASE,
)

BBox = tuple[int, int, int, int]  # (x1, y1, x2, y2) 像素, 与 vision_io / explorer._bbox_point 一致


@dataclass
class PageFingerprint:
    """单个已发现页面的锚点 (存入 state.json 后永不重算)。"""

    page_id: str
    title: str
    url: str | None
    stable_phash_prefix: str  # stable 区域 pHash 前 16 字符 (32 bit, 粗筛足够)


@dataclass
class PageRegistry:
    """运行时页面注册表。memory.py 持久化加载/保存它。"""

    pages: list[PageFingerprint] = field(default_factory=list)
    _by_id: dict[str, PageFingerprint] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        for p in self.pages:
            self._by_id.setdefault(p.page_id, p)

    def append(self, fp: PageFingerprint) -> None:
        self.pages.append(fp)
        self._by_id.setdefault(fp.page_id, fp)

    def __len__(self) -> int:
        return len(self.pages)

    def __iter__(self) -> Iterable[PageFingerprint]:
        return iter(self.pages)

    def get(self, page_id: str) -> PageFingerprint | None:
        return self._by_id.get(page_id)


# -------- 公共: 匹配入口 ------------------------------------------------


def identify_page(
    registry: PageRegistry,
    *,
    url: str | None,
    title_from_vlm: str,
    image_bytes: bytes,
    stable_bboxes: Sequence[BBox] = (),
) -> tuple[str, bool]:
    """返回 (page_id, is_new_page)。按 §5.3 两道闸门: Web 用 URL, 原生用 pHash+标题。

    stable_bboxes: 本轮 VLM 观察输出的 regions 中 stability="stable" 的那些, 原生应用
    指纹只拼合这些区域; 空序列时退化整图 pHash (兼容 Phase 1 过渡)。
    """
    if url:
        norm = normalize_url(url)
        # Web 优先 URL 精确匹配
        for p in registry:
            if p.url and normalize_url(p.url) == norm:
                # 标题若变化很大可能是 SPA 换页但 query 没改, 仍判新页 (偏新页方向)
                return p.page_id, False
        new_id = _make_page_id(url=norm, title=title_from_vlm, image=image_bytes)
        registry.append(PageFingerprint(page_id=new_id, title=title_from_vlm, url=url,
                                        stable_phash_prefix=_phash_prefix(image_bytes, stable_bboxes)))
        return new_id, True

    # 原生应用: pHash 粗筛 + 标题精配
    current_prefix = _phash_prefix(image_bytes, stable_bboxes)
    candidates: list[PageFingerprint] = []
    for p in registry:
        if hamming_prefix(current_prefix, p.stable_phash_prefix) <= _PHASH_HAMMING_THRESHOLD:
            candidates.append(p)
    if candidates:
        title_clean = _norm_title(title_from_vlm)
        for c in candidates:
            if _norm_title(c.title) == title_clean and title_clean:
                return c.page_id, False
        # 标题没匹配上但粗筛过了 → 可能同模板不同内容页 (设置-网络 vs 设置-蓝牙), 判新页
    new_id = _make_page_id(url=None, title=title_from_vlm, image=image_bytes)
    registry.append(PageFingerprint(
        page_id=new_id, title=title_from_vlm, url=None, stable_phash_prefix=current_prefix,
    ))
    return new_id, True


# -------- 工具: URL 规范化 ----------------------------------------------


def normalize_url(url: str) -> str:
    """Web URL 规范化: 去 fragment, 剥离易变 query 参数, 保留语义参数 (page=2 等)。"""
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url
    clean_query = _drop_noisy_params(parts.query)
    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path.rstrip("/") or "/",
        clean_query,
        "",  # 丢弃 fragment
    ))


def _drop_noisy_params(query: str) -> str:
    if not query:
        return ""
    kept: list[tuple[str, str]] = []
    for k, v in parse_qsl(query, keep_blank_values=True):
        if _NOISY_QUERY_KEYS_RE.search(k):
            continue
        kept.append((k, v))
    kept.sort(key=lambda kv: kv[0])
    return urlencode(kept)


# -------- 工具: pHash (感知哈希) ----------------------------------------


def perceptual_hash(image_bytes: bytes, bboxes: Sequence[BBox] = ()) -> str:
    """返回 64 bit pHash 十六进制字符串 (16 字符)。

    bboxes 非空时先把各 stable 区域横向拼合到一张画布上再算哈希, 去除轮播/列表等噪声源;
    为空时整图哈希。
    """
    with Image.open(io.BytesIO(image_bytes)) as img:
        canvas = _compose_stable_regions(img, bboxes) if bboxes else img.convert("L")
        return _phash_of(canvas)


def hamming_prefix(a_hex: str, b_hex: str) -> int:
    """两个 pHash 前缀 (16 进制字符串, 长度无需对齐) 之间的汉明距离。"""
    if not a_hex or not b_hex:
        return _PHASH_BITS
    shortest = min(len(a_hex), len(b_hex))
    a = int(a_hex[:shortest], 16)
    b = int(b_hex[:shortest], 16)
    xor = a ^ b
    return bin(xor).count("1")


def _phash_prefix(image_bytes: bytes, bboxes: Sequence[BBox]) -> str:
    full = perceptual_hash(image_bytes, bboxes)
    return full[:8]  # 32 bit 前缀, 粗筛够用


def _compose_stable_regions(img: Image.Image, bboxes: Sequence[BBox]) -> Image.Image:
    crops: list[Image.Image] = []
    for (x1, y1, x2, y2) in bboxes:
        x1 = max(0, int(x1)); y1 = max(0, int(y1))
        x2 = min(img.width, int(x2)); y2 = min(img.height, int(y2))
        if x2 <= x1 or y2 <= y1:
            continue
        crops.append(img.crop((x1, y1, x2, y2)).convert("L"))
    if not crops:
        return img.convert("L")
    total_w = sum(c.width for c in crops)
    h = max(c.height for c in crops)
    canvas = Image.new("L", (total_w, h), 0)
    x = 0
    for c in crops:
        canvas.paste(c, (x, 0))
        x += c.width
    return canvas


def _phash_of(gray: Image.Image) -> str:
    """经典 9x8 平均哈希 (dHash 风格, 9x8 共 64 bit)。"""
    small = gray.resize((_PHASH_SIZE + 1, _PHASH_SIZE), Image.Resampling.LANCZOS)
    pixels = list(small.getdata())
    bits: list[str] = []
    for row in range(_PHASH_SIZE):
        off = row * (_PHASH_SIZE + 1)
        for col in range(_PHASH_SIZE):
            bits.append("1" if pixels[off + col] > pixels[off + col + 1] else "0")
    value = int("".join(bits), 2)
    return f"{value:0{_PHASH_BITS // 4}x}"


# -------- 工具: 标题/page_id 生成 ---------------------------------------


def _norm_title(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").strip().lower())


def _make_page_id(*, url: str | None, title: str, image: bytes) -> str:
    """首次发现时生成 page_id; 之后匹配复用, 绝对不重算。"""
    h = hashlib.sha1()
    if url:
        h.update(url.encode("utf-8"))
    h.update(b"|")
    h.update(_norm_title(title).encode("utf-8"))
    h.update(b"|")
    h.update(perceptual_hash(image).encode("ascii")[:8])
    return h.hexdigest()[:12]


# -------- 持久化辅助 (memory.py 用) -------------------------------------


def registry_to_json(reg: PageRegistry) -> list[dict[str, Any]]:
    return [
        {
            "page_id": p.page_id,
            "title": p.title,
            "url": p.url,
            "stable_phash_prefix": p.stable_phash_prefix,
        }
        for p in reg
    ]


def registry_from_json(rows: list[dict[str, Any]]) -> PageRegistry:
    reg = PageRegistry()
    for r in rows or []:
        reg.append(PageFingerprint(
            page_id=str(r.get("page_id") or ""),
            title=str(r.get("title") or ""),
            url=r.get("url") if isinstance(r.get("url"), str) else None,
            stable_phash_prefix=str(r.get("stable_phash_prefix") or ""),
        ))
    return reg


__all__ = [
    "BBox",
    "PageFingerprint",
    "PageRegistry",
    "identify_page",
    "normalize_url",
    "perceptual_hash",
    "hamming_prefix",
    "registry_to_json",
    "registry_from_json",
]
