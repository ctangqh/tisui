from __future__ import annotations

import base64
from contextvars import ContextVar
from io import BytesIO
from typing import Any

from PIL import Image

from tisui.shared.config import settings
from tisui.shared.exceptions import ModelResponseError
from tisui.shared.logger import logger

from .provider import get_llm_model, get_vision_model
from .types import UnifiedImage

_TOKEN_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")
_TOKEN_METER: ContextVar[dict[str, int] | None] = ContextVar("token_meter", default=None)


def optimize_image_for_model(
    image_data_url: str,
    *,
    supported_formats: list[str] = None,
    preferred_order: list[str] = None,
    quality: int = 85,
) -> str:
    """中间适配函数：自动优化图片格式，优先使用高效格式

    Args:
        image_data_url: 原始的 data URL
        supported_formats: 模型支持的格式列表
        preferred_order: 优先使用的格式顺序
        quality: 压缩质量 (1-100)

    Returns:
        优化后的 data URL
    """
    if not supported_formats:
        supported_formats = ["image/png", "image/jpeg"]
    if not preferred_order:
        preferred_order = ["image/jpeg", "image/png"]
    
    try:
        # 解析图片
        img = UnifiedImage.from_base64(image_data_url)
        
        original_size = img.byte_size
        
        # 转换为最佳格式
        optimized_img = img.convert_to_best_format(
            supported_formats=supported_formats,
            preferred_order=preferred_order,
            quality=quality
        )
        
        # 日志记录优化效果
        optimized_size = optimized_img.byte_size
        if original_size > 0 and optimized_size < original_size:
            savings = (1 - optimized_size / original_size) * 100
            logger.debug(
                f"图片格式优化: {img.mime_type} -> {optimized_img.mime_type}, "
                f"大小: {original_size / 1024:.1f}KB -> {optimized_size / 1024:.1f}KB "
                f"(节省 {savings:.1f}%)"
            )
        
        return optimized_img.to_data_url()
    
    except Exception as e:
        logger.warning(f"图片格式优化失败，使用原始格式: {e}")
        return image_data_url


def reset_token_meter() -> None:
    """开启并清零当前上下文的 token 计量 (每步调用前调用)。"""
    _TOKEN_METER.set({key: 0 for key in _TOKEN_KEYS})


def read_token_meter() -> dict[str, int]:
    """读取当前上下文累计的 token 用量; 未开启计量时全部返回 0。"""
    meter = _TOKEN_METER.get()
    return dict(meter) if meter else {key: 0 for key in _TOKEN_KEYS}


DEFAULT_TEXT_TEMPERATURE = 0.1
DEFAULT_TEXT_MAX_TOKENS = 1500
DEFAULT_VISION_TEMPERATURE = 0.1
DEFAULT_VISION_MAX_TOKENS = 6000


def invoke_text_llm(*, content: str) -> dict[str, Any]:
    llm = get_llm_model()
    messages = [{"role": "user", "content": content.rstrip()}]
    temperature = settings.llm_config.temperature
    max_tokens = settings.llm_config.max_tokens
    resolved_temperature = temperature if temperature is not None else DEFAULT_TEXT_TEMPERATURE
    resolved_max_tokens = max_tokens if max_tokens is not None else DEFAULT_TEXT_MAX_TOKENS

    try:
        result = llm.chat_completion(
            messages,
            temperature=resolved_temperature,
            max_tokens=resolved_max_tokens,
            response_format={"type": "json_object"},
        )
    except ModelResponseError:
        result = llm.chat_completion(
            messages,
            temperature=resolved_temperature,
            max_tokens=resolved_max_tokens,
        )

    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    _accumulate_usage(usage)
    return {"content": str(result.get("content") or ""), "usage": usage}


def invoke_vision_llm(*, image_data_url: str, content: str) -> dict[str, Any]:
    import time
    llm = get_vision_model()
    start = time.time()

    # 打开图片优化，使用 JPEG->PNG 路径
    use_image_optimization = True

    if use_image_optimization:
        # 获取模型的能力配置
        capabilities = getattr(llm, "capabilities", None)
        supported_formats = None
        preferred_order = None
        if capabilities:
            supported_formats = getattr(capabilities, "supported_image_formats", None)
            preferred_order = getattr(capabilities, "preferred_image_formats", None)

        # 统一优化图片格式
        t0 = time.time()
        optimized_image_url = optimize_image_for_model(
            image_data_url,
            supported_formats=supported_formats,
            preferred_order=preferred_order,
            quality=85
        )
        t1 = time.time()
    else:
        logger.debug("[invoke_vision_llm] 图片优化已关闭，使用原始图片")
        optimized_image_url = image_data_url
        t0 = t1 = time.time()

    messages = [{"role": "user", "content": content.rstrip()}]
    temperature = settings.vision_config.temperature
    max_tokens = settings.vision_config.max_tokens
    resolved_temperature = temperature if temperature is not None else DEFAULT_VISION_TEMPERATURE
    resolved_max_tokens = max_tokens if max_tokens is not None else DEFAULT_VISION_MAX_TOKENS

    t2 = time.time()
    try:
        result = llm.chat_completion(
            messages,
            mode="vision",
            image_data_url=optimized_image_url,
            temperature=resolved_temperature,
            max_tokens=resolved_max_tokens,
            response_format={"type": "json_object"},
        )
    except ModelResponseError:
        result = llm.chat_completion(
            messages,
            mode="vision",
            image_data_url=optimized_image_url,
            temperature=resolved_temperature,
            max_tokens=resolved_max_tokens,
        )
    t3 = time.time()

    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    _accumulate_usage(usage)
    
    logger.debug(
        f"[invoke_vision_llm] 总耗时: {(t3-start)*1000:.1f}ms, "
        f"image_optimize: {(t1-t0)*1000:.1f}ms, "
        f"llm_call: {(t3-t2)*1000:.1f}ms, "
        f"usage: {usage}"
    )

    return {"content": str(result.get("content") or ""), "usage": usage}


def _accumulate_usage(usage: dict[str, Any] | None) -> None:
    """把单次调用用量累加进当前上下文计量 (未开启计量则忽略)。"""
    meter = _TOKEN_METER.get()
    if meter is None or not isinstance(usage, dict):
        return
    for key in _TOKEN_KEYS:
        value = usage.get(key)
        if value is not None:
            meter[key] += int(value)


__all__ = ["invoke_text_llm", "invoke_vision_llm", "reset_token_meter", "read_token_meter", "optimize_image_for_model"]
