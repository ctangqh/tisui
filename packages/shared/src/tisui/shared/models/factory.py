from __future__ import annotations

from typing import Dict, Optional

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from tisui.shared.config import settings
from tisui.shared.exceptions import ModelUnsupportedError
from tisui.shared.logger import logger

from .base import BaseLLM
from .custom import CustomLLM
from .deepseek import DeepSeekLLM
from .doubao import DoubaoLLM
from .llama_cpp import LlamaCppLLM
from .local import LocalLLM
from .ollama import OllamaLLM


class LLMFactory:
    """LLM 实例工厂。"""

    _provider_classes: Dict[str, type[BaseLLM]] = {
        "deepseek": DeepSeekLLM,
        "doubao": DoubaoLLM,
        "openai": CustomLLM,
        "local": LocalLLM,
        "llamacpp": LlamaCppLLM,
        "ollama": OllamaLLM,
    }
    _instances: Dict[str, BaseLLM] = {}

    @classmethod
    def register_provider(cls, name: str, provider_class: type[BaseLLM]) -> None:
        cls._provider_classes[name.lower()] = provider_class

    @classmethod
    def register(cls, name: str, llm: BaseLLM) -> None:
        cls._instances[name] = llm

    @staticmethod
    def _build_instance_key(
        *,
        provider: str,
        kind: str,
        model: str | None,
        base_url: str | None,
    ) -> str:
        return f"{provider}:{kind}:{(model or '').strip()}:{(base_url or '').strip()}"

    @staticmethod
    @retry(
        stop=stop_after_attempt(settings.MODEL_MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        before_sleep=lambda retry_state: logger.warning(
            f"模型实例初始化第 {retry_state.attempt_number} 次失败，正在重试..."
        ),
        reraise=True,
    )
    def _instantiate_provider(provider_class: type[BaseLLM], **options) -> BaseLLM:
        return provider_class(**options)

    @classmethod
    def create(cls, provider: Optional[str] = None, *, kind: str = "text", **kwargs) -> BaseLLM:
        resolved_provider = (provider or settings.llm_config.provider).lower()
        resolved_kind = (kind or "text").strip().lower()

        config = settings.vision_config if resolved_kind == "vision" else settings.llm_config
        options = dict(kwargs)
        options.setdefault("api_key", config.api_key)
        options.setdefault("base_url", config.base_url)
        options.setdefault("model", config.model)
        options.setdefault("timeout", config.timeout)
        options.setdefault("max_retries", config.max_retries)

        instance_key = cls._build_instance_key(
            provider=resolved_provider,
            kind=resolved_kind,
            model=str(options.get("model") or ""),
            base_url=str(options.get("base_url") or ""),
        )
        existing = cls._instances.get(instance_key)
        if existing is not None:
            logger.debug(f"复用模型实例: provider={resolved_provider}, kind={resolved_kind}, key={instance_key}")
            return existing

        if resolved_provider not in cls._provider_classes:
            raise ModelUnsupportedError(
                f"不支持的 LLM 提供商：{resolved_provider}，支持的提供商：{list(cls._provider_classes.keys())}"
            )

        llm = cls._instantiate_provider(cls._provider_classes[resolved_provider], **options)
        cls._instances[instance_key] = llm
        logger.info(
            f"创建模型实例: provider={resolved_provider}, kind={resolved_kind}, "
            f"model={options.get('model')}, base_url={options.get('base_url')}"
        )
        return llm


def get_llm(provider: Optional[str] = None, **kwargs) -> BaseLLM:
    return LLMFactory.create(provider, **kwargs)


__all__ = ["LLMFactory", "get_llm"]
