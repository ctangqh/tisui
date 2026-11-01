from __future__ import annotations

import base64
import importlib

import datetime
try:
    # Python 3.11+
    UTC = datetime.UTC
except AttributeError:
    # Python 3.10
    UTC = datetime.timezone.utc

from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any

from ..schemas import ImageFramePayload


@lru_cache(maxsize=1)
def load_agent_prompt_module() -> ModuleType:
    return importlib.import_module("tisui.agent.prompt")


def get_bbox_prompt() -> tuple[str, str]:
    prompt_module = load_agent_prompt_module()
    locale = str(getattr(prompt_module, "DEFAULT_LOCALE"))
    content = str(prompt_module.build_bbox_prompt())
    return locale, content


@lru_cache(maxsize=1)
def load_agent_playground_module() -> ModuleType:
    return importlib.import_module("tisui.agent.playground")


@lru_cache(maxsize=1)
def load_agent_preprocess_module() -> ModuleType:
    return importlib.import_module("tisui.agent.preprocess")


@lru_cache(maxsize=1)
def load_agent_locator_module() -> ModuleType:
    return importlib.import_module("tisui.agent.locator")


@lru_cache(maxsize=1)
def load_agent_locate_pipeline_module() -> ModuleType:
    """加载三阶段定位管道模块"""
    return importlib.import_module("tisui.agent.locate.pipeline")


@lru_cache(maxsize=1)
def load_agent_locate_types_module() -> ModuleType:
    """加载三阶段定位类型模块"""
    return importlib.import_module("tisui.agent.locate.types")


@lru_cache(maxsize=1)
def load_agent_utils_module() -> ModuleType:
    return importlib.import_module("tisui.agent.utils")


def _decode_image_base64(image_base64: str) -> bytes:
    candidate = str(image_base64 or "").strip()
    if not candidate:
        raise ValueError("image base64 is empty")
    if candidate.startswith("data:"):
        _, _, candidate = candidate.partition(",")
    try:
        return base64.b64decode(candidate, validate=True)
    except Exception as exc:
        raise ValueError("image base64 is invalid") from exc


def get_current_frame() -> ImageFramePayload | None:
    playground_module = load_agent_playground_module()
    current_frame = playground_module.get_current_frame()
    if current_frame is None:
        return None

    frame_payload = current_frame.to_dict()
    return ImageFramePayload(
        frame_id=str(frame_payload.get("frame_id") or ""),
        mime_type=str(frame_payload.get("mime_type") or "image/png"),
        image_url=str(frame_payload.get("image_url") or ""),
        width=frame_payload.get("width"),
        height=frame_payload.get("height"),
        sent_at=datetime.now(UTC).isoformat(),
    )


def get_current_preprocess_payload() -> dict[str, Any] | None:
    playground_module = load_agent_playground_module()
    preprocess_module = load_agent_preprocess_module()
    current_frame_path = Path(playground_module.get_current_frame_path())

    if not current_frame_path.exists() or not current_frame_path.is_file():
        return None

    preprocess_ctx = preprocess_module.preprocess_image(
        current_frame_path.read_bytes(),
        file_name=current_frame_path.name,
    )
    return playground_module.build_playground_payload(
        preprocess_ctx,
        image_variant="raw",
    )


def _build_original_image_info(image: dict[str, Any], original_image_size: dict[str, int] | None) -> dict[str, Any]:
    width = int((original_image_size or {}).get("width") or 0)
    height = int((original_image_size or {}).get("height") or 0)
    if width <= 0 or height <= 0:
        raise ValueError("original_image_size.width and original_image_size.height must be positive")

    return {
        "width": width,
        "height": height,
        "image_format": image.get("image_format") or "PNG",
        "byte_size": 0,
        "image_bytes": b"",
        "zoom_ratio": 1.0,
    }


def get_locator_elements_payload(
    *,
    original_image_size: dict[str, int] | None,
    image_base64: str,
    start_coordinate: list[int],
) -> dict[str, Any]:
    if len(start_coordinate) != 2:
        raise ValueError("start_coordinate must be [x, y]")

    locator_module = load_agent_locator_module()
    utils_module = load_agent_utils_module()

    image_bytes = _decode_image_base64(image_base64)
    image = utils_module.instant_image(image_bytes)
    normalized_start_coordinate = [int(start_coordinate[0]), int(start_coordinate[1])]

    resolved_original_image_size = original_image_size
    if resolved_original_image_size is None:
        if normalized_start_coordinate == [0, 0]:
            resolved_original_image_size = {
                "width": int(image.get("width") or 0),
                "height": int(image.get("height") or 0),
            }
        else:
            raise ValueError("original_image_size is required when start_coordinate is not [0, 0]")

    original_image = _build_original_image_info(image, resolved_original_image_size)

    return locator_module.locator_elements(
        image,
        normalized_start_coordinate,
        original_image=original_image,
    )


def get_pipeline_debug_payload(
    image_base64: str,
    action_text: str,
) -> dict[str, Any]:
    """
    调用三阶段定位管道，返回带 debug 数据的完整结果。
    """
    image_bytes = _decode_image_base64(image_base64)
    pipeline_module = load_agent_locate_pipeline_module()
    types_module = load_agent_locate_types_module()

    result = pipeline_module.run_pipeline(
        image_bytes,
        action_text,
        options=types_module.LocateOptions(debug_mode=True),
    )
    return _serialize_locate_result(result)


def _serialize_locate_result(result: Any) -> dict[str, Any]:
    """将 LocateResult dataclass 序列化为 JSON 兼容的 dict"""
    import dataclasses

    def _convert(obj: Any) -> Any:
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return {f.name: _convert(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
        if isinstance(obj, list):
            return [_convert(item) for item in obj]
        if isinstance(obj, tuple):
            return list(obj)
        return obj

    return _convert(result)
