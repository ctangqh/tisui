from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any

from tisui.shared.logger import logger
from tisui.shared.utils import crop_image_bytes

from .preprocess import preprocess_for_action
from .prompt import build_locator_elements_prompt, build_locator_elements_repair_prompt, build_locator_frame_prompt
from .types import Coordinate, ImageInfo, LocatorElementsList
from .utils import (
    get_bbox_action_point,
    image_to_base64,
    instant_image,
    resize_image_bbox_to_original_image_bbox,
    resize_image_by_max_side
)

_ACTION_IMAGE_CACHE: dict[str, bytes] = {}

LocatorOutput = dict[str, Any]
KeyValueMap = dict[str, Any]


def locator_elements(
    image: ImageInfo,
    raw_absolute_coord: Coordinate,
    *,
    original_image: ImageInfo | None = None,
) -> LocatorOutput:
    """
    根据截图识别全部可交互元素。

    用法：
    - `image` 传入当前待识别图片信息，必须包含 `image_bytes`
    - `raw_absolute_coord` 传入当前图片在原图中的起始坐标 `[x, y]`
    - `original_image` 可选；传入原始整图后，会补充基于原图坐标系的 bbox 信息

    返回：
    - 返回 locator 原始输出，包含 `input_image`、`elements`、`errors` 等字段
    """

    image_input = _build_images_input(start_coordinate, image, original_image)
    return _invoke_locator_prompt(
        image, raw_absolute_coord, prompt, original_image=original_image
    )


def locator_temp():
        # 大致框架定位
    resize_image = resize_image_by_max_side(image, 500)
    prompt_frame = build_locator_frame_prompt()
    vlm_result = _invoke_vision_model(resize_image, prompt_frame)
    prompt = build_locator_elements_prompt()
    vlm_result = _invoke_vision_model(image, prompt)


def locator(
    image: ImageInfo,
    raw_absolute_coord: Coordinate,
    action_text: str,
    *,
    original_image: ImageInfo | None = None,
) -> LocatorElementsList:
    """
    根据动作描述识别当前截图中的候选目标元素。

    用法：
    - `image` 传入当前待定位图片信息，必须包含 `image_bytes`
    - `raw_absolute_coord` 传入当前图片在原图中的起始坐标 `[x, y]`
    - `action_text` 传入用户动作描述，例如“点击发送按钮”
    - `original_image` 可选；传入原始整图后，会补充原图坐标系下的 bbox 信息

    返回：
    - 返回 locator 输出结构，重点关注 `elements` 中的候选控件信息
    """
    prompt = build_locator_elements_prompt()
    prompt_content = f"{prompt}\n\naction_text: {action_text.strip()}"
    return _invoke_locator_prompt(
        image, raw_absolute_coord, prompt_content, original_image=original_image
    )


def locator_by_action_text(image_bytes: bytes, action_text: str) -> LocatorElementsList:
    """
    基于预处理结果，按动作文本快速推断目标区域。

    用法：
    - `image_bytes` 传入原始截图二进制
    - `action_text` 传入用户动作描述，例如“搜索 pymidscene”

    说明：
    - 该方法优先走 `preprocess_for_action()` 的粗定位结果
    - 适用于快速返回单个高置信度候选，不会走完整的视觉元素枚举流程

    返回：
    - 返回仅包含 `elements` 的简化定位结果；未命中时返回空数组
    """
    cache_key = _hash_action_text(action_text)
    _ACTION_IMAGE_CACHE[cache_key] = image_bytes

    preprocess_result = preprocess_for_action(image_bytes, action_text)
    target_hint = preprocess_result.target_hint
    if target_hint is None:
        return {"elements": []}

    bbox = target_hint.intersect_bbox or target_hint.target_grid_bbox
    if bbox is None:
        return {"elements": []}

    action = _infer_action(action_text)
    element_type, refine_type = _infer_element_type(action)
    confidence = float(target_hint.confidence or 0.0)
    reasoning = (target_hint.reasoning or "").strip()

    relative_bbox = _to_relative_bbox(
        bbox,
        width=int(preprocess_result.preprocess.image_width or 0),
        height=int(preprocess_result.preprocess.image_height or 0),
    )

    action_region = {
        "absolute_bbox": bbox,
        "relative_bbox": relative_bbox,
        "action_point": get_bbox_action_point(bbox),
        "action": action,
        "confidence": confidence,
        "adopt_strategy": "primary",
    }

    element = {
        "action_text": target_hint.action_text,
        "locator_way": "coarse",
        "type": element_type,
        "refine_type": refine_type,
        "action_regions": [action_region],
        "raw_model_response": dict(target_hint.raw_llm_result),
        "normalized_summary": dict(target_hint.normalized_summary),
    }
    if reasoning:
        element["reasoning"] = reasoning

    return {"elements": [element]}


__all__ = [
    "LocatorOutput",
    "locator",
    "locator_elements",
    "locator_by_action_text",
]


def _hash_action_text(action_text: str) -> str:
    return hashlib.sha256(action_text.encode("utf-8")).hexdigest()


def _infer_action(action_text: str) -> str:
    normalized = action_text.strip()
    if any(keyword in normalized for keyword in ("输入", "填写", "键入", "粘贴")):
        return "input"
    return "click"


def _infer_element_type(action: str) -> tuple[str, str]:
    if action == "input":
        return "input", "text_input"
    return "button", "action_button"


def _to_relative_bbox(bbox: list[int], *, width: int, height: int) -> list[float]:
    if width <= 0 or height <= 0:
        return [0.0, 0.0, 0.0, 0.0]
    left, top, right, bottom = bbox
    return [left / width, top / height, right / width, bottom / height]


def _build_image_data_url(image: ImageInfo) -> str:
    image_bytes = image.get("image_bytes") or b""
    if not image_bytes:
        return ""

    image_format = str(image.get("image_format") or "").upper()
    mime_type = {
        "PNG": "image/png",
        "JPG": "image/jpeg",
        "JPEG": "image/jpeg",
        "WEBP": "image/webp",
    }.get(image_format, "application/octet-stream")

    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def _try_parse_json_object(content: str) -> dict[str, Any]:
    candidate = (content or "").strip()
    if candidate.startswith("```"):
        lines = [line.rstrip() for line in candidate.splitlines()]
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[0].strip().lower() == "json":
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()

    def _extract_first_json_object(text: str) -> str:
        start = text.find("{")
        if start < 0:
            return text

        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        return text

    def _sanitize_json_text(text: str) -> str:
        sanitized = text.strip().lstrip("\ufeff")
        sanitized = _extract_first_json_object(sanitized)
        sanitized = re.sub(r"^\s*//.*$", "", sanitized, flags=re.MULTILINE)
        sanitized = re.sub(r"/\*[\s\S]*?\*/", "", sanitized)
        sanitized = re.sub(r",(\s*[}\]])", r"\1", sanitized)
        return sanitized.strip()

    errors: list[str] = []
    for attempt in (candidate, _sanitize_json_text(candidate)):
        if not attempt:
            continue
        try:
            data = json.loads(attempt)
            if not isinstance(data, dict):
                raise ValueError("vision llm response is not a json object")
            return data
        except Exception as exc:
            errors.append(str(exc))

    # 完整解析失败，尝试恢复 elements
    def _try_recover_elements_from_truncated(text: str) -> dict[str, Any] | None:
        elements_anchor = '"elements":'
        idx = text.find(elements_anchor)
        if idx < 0:
            return None

        elements_start = idx + len(elements_anchor)
        depth = 0
        in_string = False
        escape = False
        elements_end = None

        for i in range(elements_start, len(text)):
            char = text[i]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char in ("[", "{"):
                depth += 1
            elif char in ("]", "}"):
                depth -= 1
                if depth == 0:
                    elements_end = i + 1
                    break

        if elements_end is None:
            # 没找到完整闭合，尝试去掉最后一个对象直到能解析
            partial = text[elements_start:].rstrip().rstrip(",")
            # 尝试多次截断最后一个对象
            for trim_round in range(10):
                last_comma = partial.rfind(",")
                if last_comma < 0:
                    break
                partial = partial[:last_comma].rstrip()
                # 尝试用这段去解析数组
                try_candidate = "[" + partial + "]"
                try:
                    parsed = json.loads(try_candidate)
                    if isinstance(parsed, list):
                        return {"elements": parsed}
                except Exception:
                    continue
            return None

        try:
            elements_part = text[elements_start:elements_end]
            elements_list = json.loads(elements_part)
            if not isinstance(elements_list, list):
                return None
            return {"elements": elements_list}
        except Exception:
            return None

    recovered = _try_recover_elements_from_truncated(candidate)
    if isinstance(recovered, dict):
        return recovered

    raise ValueError(
        errors[-1] if errors else "vision llm response is not a json object"
    )


def _build_input_image(
    image: ImageInfo,
    raw_absolute_coord: Coordinate,
    *,
    original_image: ImageInfo | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "start_coordinate": list(raw_absolute_coord),
        "width": int(image.get("width") or 0),
        "height": int(image.get("height") or 0),
        "zoom_ratio": float(image.get("zoom_ratio") or 1.0),
    }
    if isinstance(original_image, dict):
        original_width = int(original_image.get("width") or 0)
        original_height = int(original_image.get("height") or 0)
        if original_width > 0 and original_height > 0:
            payload["original_width"] = original_width
            payload["original_height"] = original_height
    return payload


def _calc_bbox_to_original_bbox(
    payload: LocatorOutput, *, original_image: ImageInfo | None
) -> LocatorOutput:
    input_image = payload.get("input_image")
    if not isinstance(input_image, dict):
        return payload

    start_coordinate = input_image.get("start_coordinate")
    if not (isinstance(start_coordinate, list) and len(start_coordinate) == 2):
        return payload

    resize_image_width = int(input_image.get("width") or 0)
    resize_image_height = int(input_image.get("height") or 0)
    if resize_image_width <= 0 or resize_image_height <= 0:
        return payload

    zoom_ratio = float(input_image.get("zoom_ratio") or 1.0)
    if zoom_ratio <= 0:
        zoom_ratio = 1.0

    crop_original_width = int(round(resize_image_width / zoom_ratio))
    crop_original_height = int(round(resize_image_height / zoom_ratio))
    if crop_original_width <= 0 or crop_original_height <= 0:
        crop_original_width = resize_image_width
        crop_original_height = resize_image_height

    raw_original_width = int(input_image.get("original_width") or 0)
    raw_original_height = int(input_image.get("original_height") or 0)
    if raw_original_width <= 0 and isinstance(original_image, dict):
        raw_original_width = int(original_image.get("width") or 0)
    if raw_original_height <= 0 and isinstance(original_image, dict):
        raw_original_height = int(original_image.get("height") or 0)

    full_original_width = raw_original_width
    full_original_height = raw_original_height
    if full_original_width <= 0 or full_original_height <= 0:
        full_original_width = crop_original_width
        full_original_height = crop_original_height

    def _apply_relative_bbox(
        relative_bbox: Any,
    ) -> tuple[list[int] | None, list[float] | None]:
        if not (isinstance(relative_bbox, list) and len(relative_bbox) == 4):
            return None, None
        try:
            conversion = resize_image_bbox_to_original_image_bbox(
                [float(x) for x in relative_bbox],
                resize_image_width=resize_image_width,
                resize_image_height=resize_image_height,
                start_coordinate=[int(start_coordinate[0]), int(start_coordinate[1])],
                original_width=full_original_width,
                original_height=full_original_height,
            )
        except Exception:
            conversion = {}

        absolute_bbox = conversion.get("absolute_bbox")
        relative_bbox_on_original = conversion.get("relative_bbox")
        if not (isinstance(absolute_bbox, list) and len(absolute_bbox) == 4):
            absolute_bbox = None
        if not (
            isinstance(relative_bbox_on_original, list)
            and len(relative_bbox_on_original) == 4
        ):
            relative_bbox_on_original = None

        if absolute_bbox is not None and relative_bbox_on_original is not None:
            return [int(x) for x in absolute_bbox], [
                float(x) for x in relative_bbox_on_original
            ]

        try:
            from tisui.shared.utils import relative_to_absolute_coord

            absolute_bbox = relative_to_absolute_coord(
                crop_original_width,
                crop_original_height,
                [float(x) for x in relative_bbox],
                [int(start_coordinate[0]), int(start_coordinate[1])],
            )
        except Exception:
            return None, None

        if not (isinstance(absolute_bbox, list) and len(absolute_bbox) == 4):
            return None, None

        try:
            relative_bbox_on_original = [
                round(int(absolute_bbox[0]) / max(1, full_original_width), 6),
                round(int(absolute_bbox[1]) / max(1, full_original_height), 6),
                round(int(absolute_bbox[2]) / max(1, full_original_width), 6),
                round(int(absolute_bbox[3]) / max(1, full_original_height), 6),
            ]
        except Exception:
            return None, None

        return [int(x) for x in absolute_bbox], relative_bbox_on_original

    elements = payload.get("elements")
    if not isinstance(elements, list):
        return payload

    for element in elements:
        if not isinstance(element, dict):
            continue

        # 优先从 regions 获取，其次从 action_regions 获取
        source_regions = element.get("regions")
        if not isinstance(source_regions, dict):
            candidate = element.get("action_regions")
            if isinstance(candidate, dict):
                source_regions = candidate
            elif (
                isinstance(candidate, list)
                and candidate
                and isinstance(candidate[0], dict)
            ):
                source_regions = candidate[0]

        if not isinstance(source_regions, dict):
            continue

        # 获取相对坐标，如果没有则尝试从绝对坐标计算
        relative_bbox = source_regions.get("relative_bbox")
        if not (isinstance(relative_bbox, list) and len(relative_bbox) == 4):
            absolute_bbox_in_resize = source_regions.get("absolute_bbox")
            if (
                isinstance(absolute_bbox_in_resize, list)
                and len(absolute_bbox_in_resize) == 4
            ):
                relative_bbox = _to_relative_bbox(
                    [int(x) for x in absolute_bbox_in_resize],
                    width=resize_image_width,
                    height=resize_image_height,
                )
            if not (isinstance(relative_bbox, list) and len(relative_bbox) == 4):
                continue

        # 计算完整的 action_region
        absolute_bbox, relative_bbox_on_original = _apply_relative_bbox(relative_bbox)
        if absolute_bbox is None or relative_bbox_on_original is None:
            continue

        # 获取或设置默认值
        confidence = source_regions.get("confidence")
        if isinstance(confidence, (int, float)):
            confidence = float(confidence)
        else:
            confidence = None

        adopt_strategy = source_regions.get("adopt_strategy")
        if not isinstance(adopt_strategy, str) or not adopt_strategy.strip():
            adopt_strategy = "primary"

        action = source_regions.get("action")
        if not isinstance(action, str) or not action.strip():
            action = "click"

        # 构建完整的 action_region
        action_region = {
            "absolute_bbox": absolute_bbox,
            "relative_bbox": relative_bbox_on_original,
            "action_point": get_bbox_action_point(absolute_bbox),
            "action": action,
            "adopt_strategy": adopt_strategy,
        }
        if confidence is not None:
            action_region["confidence"] = confidence

        # 覆盖 element["action_regions"]
        element["action_regions"] = action_region

        # 更新 attributes 的 position（这个仍然需要处理）
        attributes = element.get("attributes")
        if not isinstance(attributes, dict):
            attributes = {}
            element["attributes"] = attributes
        if raw_original_width > 0 and raw_original_height > 0:
            attributes["position"] = _calc_bbox_position_by_nine_grid(
                absolute_bbox,
                [raw_original_width, raw_original_height],
            )
        else:
            attributes.pop("position", None)

    return payload


def _calc_bbox_position_by_nine_grid(original_bbox: Any, image_size: Any) -> str:
    if not (isinstance(original_bbox, list) and len(original_bbox) == 4):
        return "中间"
    if not (isinstance(image_size, list) and len(image_size) == 2):
        return "中间"

    try:
        left, top, right, bottom = [float(value) for value in original_bbox]
        image_width, image_height = [float(value) for value in image_size]
    except (TypeError, ValueError):
        return "中间"

    if image_width <= 0 or image_height <= 0:
        return "中间"

    center_x = (left + right) / 2
    center_y = (top + bottom) / 2

    horizontal_index = min(max(int(center_x / (image_width / 3)), 0), 2)
    vertical_index = min(max(int(center_y / (image_height / 3)), 0), 2)

    position_map = [
        ["左上", "中上", "右上"],
        ["左中", "中间", "右中"],
        ["左下", "中下", "右下"],
    ]
    return position_map[vertical_index][horizontal_index]


def _finalize_locator_payload(
    payload: LocatorOutput, *, token_usage: dict[str, Any]
) -> LocatorOutput:
    errors = payload.pop("errors", [])
    payload["token_usage"] = token_usage if isinstance(token_usage, dict) else {}
    payload["errors"] = errors if isinstance(errors, list) else []
    return payload


def _invoke_llm_repair_json(
    raw_content: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """
    尝试使用大模型修复不完整的 JSON 数据。

    参数：
    - raw_content: 原始的、无法解析的 JSON 字符串

    返回：
    - (修复后的 dict, token_usage)，修复失败时返回 (None, token_usage)
    """
    from tisui.shared.models.invoker import invoke_text_llm

    repair_prompt = build_locator_elements_repair_prompt()
    full_prompt = f"{repair_prompt}\n\n## 需要修复的原始 JSON 数据\n```json\n{raw_content}\n```"

    try:
        result = invoke_text_llm(content=full_prompt)
        repaired_content = str(result.get("content") or "")
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}

        # 尝试解析修复后的 JSON
        return _try_parse_json_object(repaired_content), usage
    except Exception:
        # 修复失败
        return None, {}


def _invoke_locator_prompt(
    image: ImageInfo,
    raw_absolute_coord: Coordinate,
    prompt_content: str,
    *,
    original_image: ImageInfo | None = None,
) -> LocatorOutput:
    from tisui.shared.models.invoker import invoke_vision_llm

    logger.debug("----------start invoke vision model-----------")
    image_data_url = image_to_base64(image)

    if not image_data_url:
        return _finalize_locator_payload(
            {
                "input_image": _build_input_image(
                    image, raw_absolute_coord, original_image=original_image
                ),
                "elements": [],
                "raw_model_response": {},
                "normalized_summary": [],
                "errors": ["image_bytes is empty"],
            },
            token_usage={},
        )

    result = invoke_vision_llm(image_data_url=image_data_url, content=prompt_content)
    raw_content = str(result.get("content") or "")
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}

    logger.debug("模型原始返回内容 (raw_content):")
    logger.debug(raw_content)

    try:
        payload = _try_parse_json_object(raw_content)
    except Exception as exc:
        # JSON 解析失败，尝试使用大模型修复
        repaired_payload, repair_usage = _invoke_llm_repair_json(raw_content)

        # 合并 token usage
        total_usage: dict[str, Any] = {}
        if isinstance(usage, dict):
            total_usage.update(usage)
        if isinstance(repair_usage, dict):
            for key, value in repair_usage.items():
                total_usage[key] = (total_usage.get(key) or 0) + (value or 0)

        if repaired_payload is not None:
            # 修复成功
            payload = repaired_payload
            if "errors" not in payload:
                payload["errors"] = []
            payload["errors"].append(f"json_repaired: original_error={exc}")
        else:
            # 修复也失败了
            return _finalize_locator_payload(
                {
                    "input_image": _build_input_image(
                        image, raw_absolute_coord, original_image=original_image
                    ),
                    "elements": [],
                    "raw_model_response": {
                        "content": raw_content,
                        "usage": usage,
                        "repair_usage": repair_usage,
                    },
                    "normalized_summary": [],
                    "errors": [f"json_parse_error: {exc}", "json_repair_failed"],
                },
                token_usage=total_usage,
            )

    payload["input_image"] = _build_input_image(
        image, raw_absolute_coord, original_image=original_image
    )
    if not isinstance(payload.get("elements"), list):
        payload["elements"] = []
    if "raw_model_response" not in payload:
        payload["raw_model_response"] = {"content": raw_content, "usage": usage}
    if "normalized_summary" not in payload:
        payload["normalized_summary"] = []
    if not isinstance(payload.get("normalized_summary"), list):
        payload["normalized_summary"] = []
    if "errors" not in payload:
        payload["errors"] = []

    payload = _calc_bbox_to_original_bbox(payload, original_image=original_image)
    return _finalize_locator_payload(payload, token_usage=usage)


def _invoke_vision_model(image: ImageInfo, prompt: str) -> LocatorOutput:
    """
    调用视觉模型识别控件
    人工写的方法

    参数：
    - image: 图片二进制文件
    - prompt: 调用的prompt

    返回：
    - (修复后的 dict, token_usage)，修复失败时返回 (None, token_usage)
    """
    from tisui.shared.models.invoker import invoke_vision_llm

    image_data_url = image_to_base64(image)
    result = invoke_vision_llm(image_data_url=image_data_url, content=prompt)
    raw_content = str(result.get("content") or "")
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    return {"content": raw_content, "token_usage": usage}


def _build_images_input(
    start_coordinate: Coordinate, image: Image, original_image: Image
) -> KeyValueMap:
    """
    构建图像输入信息

    返回：
    {
        "input_image": {
            "start_coordinate": [0, 0],      # 裁剪起始坐标
            "width": 900,                    # 裁剪区域宽度
            "height": 800,                   # 裁剪区域高度
            "original_width": 1920,          # 原始图像宽度
            "original_height": 1080,         # 原始图像高度
            "zoom_ratio": 1                  # 缩放比例
        }
    }
    """
    # 获取原始图像尺寸
    original_width, original_height = original_image.size

    # 获取裁剪后图像的尺寸
    cropped_width, cropped_height = image.size

    # 计算缩放比例（裁剪后尺寸 / 原始尺寸）
    # 注意：如果图像被放大了，zoom_ratio > 1；如果被缩小了，zoom_ratio < 1
    # 这里用宽度和高度分别计算，取平均值或分别返回
    zoom_ratio_width = cropped_width / original_width
    zoom_ratio_height = cropped_height / original_height

    # 通常 zoom_ratio 指整体缩放比例，可以用宽度或高度的比值
    # 如果宽高比不一致，可以取平均值，或者分别存储
    # zoom_ratio = (zoom_ratio_width + zoom_ratio_height) / 2

    # 或者更精确：如果图像是等比例缩放的，用哪个都一样
    zoom_ratio = zoom_ratio_width  # 或 zoom_ratio_height

    return {
        "input_image": {
            "start_coordinate": [start_coordinate.x, start_coordinate.y],
            "width": cropped_width,
            "height": cropped_height,
            "original_width": original_width,
            "original_height": original_height,
            "zoom_ratio": round(zoom_ratio, 4),  # 保留4位小数，避免浮点数过长
        }
    }
