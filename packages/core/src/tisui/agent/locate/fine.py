"""
④ 聚焦精定位 (v2)

输入: 从 raw 原分辨率裁出的 patch (CroppedPatch, 已知 patch 在 raw 中的位置)。
过程: patch → VLM 紧致定位 → patch 内 bbox 直接 +origin 回 raw → 归一化(按 raw)。

不再做条件放大: patch 已是 raw 原生像素, 精度优先 (用户决策)。
坐标只需平移, 杜绝 v1 多级 zoom 反映射的误差累积。
"""

from __future__ import annotations

import base64
import json
from io import BytesIO
from typing import Any

from PIL import Image

from tisui.shared.logger import logger
from tisui.shared.models.invoker import invoke_vision_llm

from .coords import (
    compute_action_point,
    map_patch_bbox_to_raw,
    normalize_relative_bbox,
    relative_to_abs,
    to_relative,
)
from .types import BBox, CroppedPatch, LocatedElement, LocateOptions

_FINE_PROMPT = """\
You are looking at a cropped patch of a UI screenshot.
The full original page is {full_width}x{full_height} pixels.
This patch is taken from region [{patch_left}, {patch_top}, {patch_right}, {patch_bottom}] of the original page.

User wants to: "{action_text}"

Tightly locate the EXACT target element(s) in THIS patch.
Output JSON only:
{{
  "found": true,
  "elements": [
    {{
      "type": "button / text_input / searchbox / checkbox / radio / switch / dropdown / tab / menu_item / card / link / icon_button / other",
      "refine_type": "action_button / text_input / checkbox / radio / dropdown / tab / unknown",
      "text": "visible text on the element",
      "description": "what this element does",
      "relative_bbox": [x1, y1, x2, y2],
      "action_point_hint": "center / left_side / right_side / icon_area / text_area",
      "confidence": 0.95,
      "enabled": true,
      "action_capabilities": ["click"]
    }}
  ],
  "primary_index": 0
}}

Requirements:
1. relative_bbox MUST be TIGHT — the element only, no extra padding.
2. relative_bbox uses RELATIVE ratios in [0,1] of THIS PATCH: x1=left/patch_width, y1=top/patch_height, x2=right/patch_width, y2=bottom/patch_height. Keep 6 decimals. DO NOT output absolute pixels.
3. action_point_hint = best interaction point (center/left_side/right_side/icon_area/text_area).
4. If the target is NOT in this patch, set "found": false.
5. Return up to 2 elements max.
"""


def fine_locate_region(
    patch: CroppedPatch,
    action_text: str,
    options: LocateOptions,
    *,
    raw_size: tuple[int, int],
) -> list[LocatedElement]:
    """对单个 patch 做精定位, 返回 raw 坐标系下的元素列表 (可能为空)。"""
    _ = options
    patch_image = patch.patch_image
    if not isinstance(patch_image, Image.Image):
        return []

    p_left, p_top, p_right, p_bottom = patch.bbox_in_raw
    prompt = _FINE_PROMPT.format(
        full_width=raw_size[0],
        full_height=raw_size[1],
        patch_left=p_left,
        patch_top=p_top,
        patch_right=p_right,
        patch_bottom=p_bottom,
        action_text=(action_text or "")[:200],
    )

    try:
        result = invoke_vision_llm(image_data_url=_pil_to_data_url(patch_image), content=prompt)
        data = _parse_json_object(str(result.get("content") or ""))
    except Exception as exc:
        logger.warning(f"精定位 VLM 调用失败: {exc}")
        return []

    if data.get("found") is False:
        return []
    raw_elements = data.get("elements")
    if not isinstance(raw_elements, list) or not raw_elements:
        return []

    origin = (p_left, p_top)
    primary_index = _safe_int(data.get("primary_index"), 0)
    elements: list[LocatedElement] = []
    for j, elem_data in enumerate(raw_elements):
        if not isinstance(elem_data, dict):
            continue
        rel = normalize_relative_bbox(elem_data.get("relative_bbox"), patch_size=patch_image.size)
        if rel is None:
            logger.warning(
                "精定位丢弃元素: relative_bbox 非法 "
                f"{elem_data.get('relative_bbox')!r} (type={elem_data.get('type')!r}, "
                f"text={elem_data.get('text')!r})"
            )
            continue
        bbox_patch = relative_to_abs(rel, patch_image.size)
        bbox_raw: BBox = map_patch_bbox_to_raw(bbox_patch, origin)
        bbox_raw = _clamp_bbox(bbox_raw, raw_size)
        hint = str(elem_data.get("action_point_hint") or "center")
        element = LocatedElement(
            type=_normalize_control_type(str(elem_data.get("type") or "other")),
            refine_type=str(elem_data.get("refine_type") or "unknown"),
            text=str(elem_data.get("text") or ""),
            description=str(elem_data.get("description") or ""),
            bbox=bbox_raw,
            bbox_relative=to_relative(bbox_raw, raw_size),
            action_point=compute_action_point(bbox_raw, hint),
            action_point_hint=hint,
            confidence=_normalize_confidence(elem_data.get("confidence")),
            enabled=bool(elem_data.get("enabled", True)),
            action_capabilities=_normalize_str_list(elem_data.get("action_capabilities")),
            locator_way="fine",
            source_region_id=patch.source_region_id,
            reasoning=str(elem_data.get("description") or ""),
        )
        if j == primary_index:
            elements.insert(0, element)  # primary 排最前
        else:
            elements.append(element)

    return elements


# ---- helpers ----

def _pil_to_data_url(image: Image.Image) -> str:
    buf = BytesIO()
    image.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def _clamp_bbox(bbox: BBox, size: tuple[int, int]) -> BBox:
    w, h = size
    left = max(0, min(w, bbox[0]))
    top = max(0, min(h, bbox[1]))
    right = max(0, min(w, bbox[2]))
    bottom = max(0, min(h, bbox[3]))
    if right <= left:
        right = min(w, left + 1)
    if bottom <= top:
        bottom = min(h, top + 1)
    return [left, top, right, bottom]


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_confidence(value: Any) -> float:
    try:
        c = float(value)
    except (TypeError, ValueError):
        return 0.0
    if c > 1 and c <= 100:
        c = c / 100.0
    return max(0.0, min(1.0, c))


def _normalize_control_type(control_type: str) -> str:
    if not control_type:
        return "other"
    control_type = control_type.lower().strip()
    alias_map = {
        "textbox": "text_input", "input": "text_input",
        "icon": "icon_button", "image_button": "icon_button",
        "selector": "dropdown", "combobox": "dropdown",
        "toggle_switch": "switch", "check": "checkbox",
        "radio_button": "radio", "link_text": "link", "hyperlink": "link",
    }
    return alias_map.get(control_type, control_type)


def _normalize_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


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


__all__ = ["fine_locate_region"]
