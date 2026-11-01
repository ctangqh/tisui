from __future__ import annotations

from typing import Any, Dict, Optional

from tisui.shared.config import settings

from .base import BaseLLM
from .factory import LLMFactory


class ModelProvider:
    """注册并提供当前配置的 LLM/Vision 模型实例。"""

    def __init__(self) -> None:
        self._models: Dict[str, BaseLLM] = {}

    def register_configured_models(self) -> None:
        self._models["llm"] = self._create_model(kind="text")
        self._models["vision"] = self._create_model(kind="vision")

    def _ensure_registered(self, model_type: str) -> BaseLLM:
        model = self._models.get(model_type)
        if model is not None:
            return model
        kind = "vision" if model_type == "vision" else "text"
        model = self._create_model(kind=kind)
        self._models[model_type] = model
        return model

    def _resolve_options(self, *, kind: str, **kwargs: Any) -> tuple[str, Dict[str, Any]]:
        config = settings.vision_config if kind == "vision" else settings.llm_config
        resolved_provider = str(kwargs.pop("provider", None) or config.provider or "").strip().lower()
        options = dict(kwargs)
        options.setdefault("api_key", config.api_key)
        options.setdefault("base_url", config.base_url)
        options.setdefault("model", config.model)
        options.setdefault("timeout", config.timeout)
        options.setdefault("max_retries", config.max_retries)
        return resolved_provider, options

    def _create_model(self, provider: Optional[str] = None, *, kind: str, **kwargs: Any) -> BaseLLM:
        resolved_provider, options = self._resolve_options(
            kind=kind,
            provider=provider,
            **kwargs,
        )
        return LLMFactory.create(resolved_provider, kind=kind, **options)

    def get_llm_model(self, provider: Optional[str] = None, **kwargs: Any) -> BaseLLM:
        if provider is None and not kwargs:
            return self._ensure_registered("llm")
        return self._create_model(provider, kind="text", **kwargs)

    def get_vision_model(self, provider: Optional[str] = None, **kwargs: Any) -> BaseLLM:
        if provider is None and not kwargs:
            return self._ensure_registered("vision")
        return self._create_model(provider, kind="vision", **kwargs)


model_provider = ModelProvider()


def get_llm_model(provider: Optional[str] = None, **kwargs: Any) -> BaseLLM:
    return model_provider.get_llm_model(provider, **kwargs)


def get_vision_model(provider: Optional[str] = None, **kwargs: Any) -> BaseLLM:
    return model_provider.get_vision_model(provider, **kwargs)

def get_llm(content: str) -> tuple[BaseLLM, list[dict[str, str]]]:
    model = get_llm_model()
    messages = [{"role": "user", "content": content.rstrip()}]
    return model, messages


def invoke_vision_llm(*, image_data_url: str, content: str) -> dict[str, Any]:
    from .invoker import invoke_vision_llm as _invoke_vision_llm

    return _invoke_vision_llm(image_data_url=image_data_url, content=content)


__all__ = [
    "ModelProvider",
    "get_llm_model",
    "get_vision_model",
    "get_llm",
    "invoke_vision_llm",
    "model_provider",
]
