from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, TypedDict

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from tisui.shared.config import settings
from tisui.shared.exceptions import ModelResponseError, ModelTimeoutError
from tisui.shared.logger import logger

from .types import ModelCapabilities


class ChatCompletionResult(TypedDict, total=False):
    content: str
    raw_response: Any
    usage: Dict[str, Any]


class BaseLLM(ABC):
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = kwargs.get("timeout", settings.MODEL_TIMEOUT)
        self.max_retries = kwargs.get("max_retries", settings.MODEL_MAX_RETRIES)
        self._last_token_usage: Dict[str, Any] | None = None

    def summarize_messages(self, messages: List[Dict[str, Any]], *, max_chars: int = 240) -> str:
        if not messages:
            return ""

        segments: List[str] = []
        for msg in messages[:3]:
            role = str(msg.get("role") or "unknown").strip() or "unknown"
            content = self._flatten_content(msg.get("content"))
            if len(content) > 80:
                content = content[:80] + "..."
            segments.append(f"{role}:{content}")
        if len(messages) > 3:
            segments.append(f"...(+{len(messages) - 3} more)")

        summary = " | ".join(segments).strip()
        if len(summary) > max_chars:
            return summary[:max_chars] + "..."
        return summary

    def _flatten_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content.replace("\n", " ").strip()
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if not isinstance(item, dict):
                    parts.append(str(item))
                    continue
                item_type = str(item.get("type") or "").strip()
                if item_type == "text":
                    parts.append(str(item.get("text") or "").replace("\n", " ").strip())
                    continue
                if item_type == "image_url":
                    parts.append("[image_url]")
                    continue
                if item_type == "image":
                    parts.append("[image]")
                    continue
                parts.append(str(item))
            return " ".join(part for part in parts if part).strip()
        if isinstance(content, dict):
            return str(content)
        return str(content or "").strip()

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(supports_text=True)

    def token_count(self, *, result: ChatCompletionResult, messages: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        usage = result.get("usage")
        if isinstance(usage, dict) and usage:
            return usage
        return None

    @abstractmethod
    def chat_completion(self, messages: List[Dict[str, Any]], **kwargs) -> ChatCompletionResult:
        raise NotImplementedError

    @retry(
        stop=stop_after_attempt(settings.MODEL_MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ModelTimeoutError, ConnectionError)),
        before_sleep=lambda retry_state: logger.warning(
            f"模型调用第 {retry_state.attempt_number} 次失败，正在重试..."
        ),
    )
    def chat(self, messages: List[Dict[str, Any]], **kwargs) -> ChatCompletionResult:
        try:
            logger.debug(f"调用 {self.__class__.__name__} 模型，消息长度：{len(str(messages))} 字符")
            result = self.chat_completion(messages, **kwargs)
            content = str(result.get("content") or "").strip()
            usage = self.token_count(result=result, messages=messages)
            self._last_token_usage = usage
            preview = content[:200] + ("..." if len(content) > 200 else "")
            logger.debug(f"模型返回结果：{preview}")
            logger.debug(f"Token 用量：{usage}")
            return {
                "content": content,
                "raw_response": result.get("raw_response"),
                "usage": usage or {},
            }
        except TimeoutError as e:
            raise ModelTimeoutError(f"模型调用超时: {str(e)}") from e
        except Exception as e:
            logger.error(f"模型调用失败: {str(e)}")
            raise ModelResponseError(f"模型调用失败: {str(e)}") from e

    def last_token_usage(self) -> Dict[str, Any] | None:
        return self._last_token_usage


__all__ = ["BaseLLM", "ChatCompletionResult"]
