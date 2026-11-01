"""
② 布局分区 (v2)

用 overview 缩略图, 只划 header/content/list/... 大区域, 不枚举控件。
**意图无关**: prompt 不含 action_text, 保证 L2(按 sha256) 布局缓存可跨意图复用。
"""

from __future__ import annotations

import base64
import json
import time
from io import BytesIO
from typing import Any

from PIL import Image

from tisui.shared.logger import logger
from tisui.shared.models.invoker import invoke_vision_llm

from ..prompt import build_layout_prompt
from .coords import normalize_relative_bbox, relative_to_abs
from .types import LayoutRegion, LayoutResult, LocateOptions


def perform_layout(
    overview_image: Image.Image,
    options: LocateOptions,
    *,
    base_size: tuple[int, int],
) -> LayoutResult:
    """overview → VLM → 区域列表 (模型返回相对坐标, 映射回 base 像素)。"""
    start = time.time()
    t0 = time.time()
    image_data_url = _pil_to_data_url(overview_image)
    t1 = time.time()

    try:
        t2 = time.time()
        result = invoke_vision_llm(image_data_url=image_data_url, content=build_layout_prompt("en-US"))
        t3 = time.time()
        raw = _parse_json_object(str(result.get("content") or ""))
    except Exception as exc:
        logger.warning(f"布局分区 VLM 调用失败: {exc}")
        return LayoutResult(regions=[], duration_ms=(time.time() - start) * 1000)

    t4 = time.time()
    regions: list[LayoutRegion] = []
    raw_regions = raw.get("regions") if isinstance(raw, dict) else None
    if isinstance(raw_regions, list):
        for item in raw_regions:
            if not isinstance(item, dict):
                continue
            rel = normalize_relative_bbox(item.get("relative_bbox"))
            if rel is None:
                continue
            bbox_base = relative_to_abs(rel, base_size)
            if bbox_base[2] <= bbox_base[0] or bbox_base[3] <= bbox_base[1]:
                continue
            regions.append(LayoutRegion(
                region_id=f"region_{len(regions)}",
                region_type=str(item.get("region_type") or "unknown"),
                bbox=bbox_base,
                semantic_tags=_normalize_str_list(item.get("semantic_tags")),
                description=str(item.get("description") or ""),
                confidence=_normalize_confidence(item.get("confidence")),
                z_index=_normalize_z_index(item.get("z_index")),
            ))
    t5 = time.time()

    logger.debug(
        f"[Layout] 总耗时: {(t5-start)*1000:.1f}ms, "
        f"encode: {(t1-t0)*1000:.1f}ms, "
        f"invoke_vision_llm: {(t3-t2)*1000:.1f}ms, "
        f"parse+process: {(t5-t4)*1000:.1f}ms, "
        f"regions: {len(regions)}"
    )

    return LayoutResult(
        regions=regions,
        layout_type=str(raw.get("layout_type") or "unknown") if isinstance(raw, dict) else "unknown",
        model_used="vlm",
        duration_ms=(time.time() - start) * 1000,
        raw_model_response=raw if options.debug_mode else None,
    )


# ---- helpers ----

def _pil_to_data_url(image: Image.Image) -> str:
    buf = BytesIO()
    image.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def _normalize_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


def _normalize_confidence(value: Any) -> float:
    try:
        c = float(value)
    except (TypeError, ValueError):
        return 0.5
    if c > 1 and c <= 100:
        c = c / 100.0
    return max(0.0, min(1.0, c))


def _normalize_z_index(value: Any) -> int:
    """规范化堆叠层级: 0=基础层, >=1=覆盖层; 非法值归 0。"""
    try:
        z = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(0, z)


def _parse_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[0].strip().lower() == "json":
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(raw[start:end + 1])
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
    return {}


__all__ = ["perform_layout"]
