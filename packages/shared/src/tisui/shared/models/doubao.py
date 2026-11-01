from __future__ import annotations

from typing import Any, Dict, List, Optional

from tisui.shared.config import settings
from tisui.shared.exceptions import MissingAPIKeyError
from tisui.shared.logger import logger

from .base import BaseLLM
from .custom import make_openai_client
from .types import ModelCapabilities, UnifiedImage


class DoubaoLLM(BaseLLM):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        llm_config = settings.llm_config

        self.api_key = self.api_key or llm_config.api_key
        if not self.api_key:
            raise MissingAPIKeyError("LLM_API_KEY 未配置")

        self.base_url = self.base_url or llm_config.base_url
        self.model = self.model or llm_config.model
        self.provider = "doubao"
        self.name = self.model

        self.timeout = max(int(self.timeout or 0), 180)

        self.client = make_openai_client(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=self.max_retries,
        )

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            supports_text=True,
            supports_vision=True,
            supports_structured_output=False,
            supports_system_prompt=True,
            supports_tool_calling=False,
        )

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        *,
        mode: str = "text",
        image_data_url: Optional[str] = None,
        image_urls: Optional[List[str]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        resolved_mode = (mode or "text").strip().lower()
        requested_model = kwargs.get("model", self.model)
        prepared_messages = _to_text_messages(messages)
        image_count = 0
        if resolved_mode == "vision":
            urls: List[str] = []
            urls.extend(list(image_urls or []))
            if image_data_url:
                urls.append(image_data_url)
            image_count = len(urls)
            prepared_messages = _to_vision_messages(prepared_messages, image_urls=urls)

        extra: Dict[str, Any] = {}
        if "response_format" in kwargs:
            extra["response_format"] = kwargs.get("response_format")
        # 默认关闭深度思考(thinking): 该模型为推理模型, 会为感知/格式化类任务生成大量
        # 无用的思维链, 显著拖慢速度。需要推理时可通过 kwargs["thinking"] 显式覆盖。
        thinking = kwargs.get("thinking", {"type": "disabled"})
        if thinking is not None:
            extra["extra_body"] = {"thinking": thinking}
        request_summary = self.summarize_messages(messages)
        logger.debug(
            f"Doubao 请求开始: mode={resolved_mode}, model={requested_model}, "
            f"messages={len(prepared_messages)}, images={image_count}, "
            f"temperature={kwargs.get('temperature', 0.1)}, max_tokens={kwargs.get('max_tokens', 4096)}, "
            f"thinking={thinking!r}, response_format={extra.get('response_format')!r}, request_summary={request_summary!r}"
        )
        import time
        t0 = time.time()
        try:
            response = self.client.chat.completions.create(
                model=requested_model,
                messages=prepared_messages,
                temperature=kwargs.get('temperature', 0.1),
                max_tokens=kwargs.get('max_tokens', 4096),
                **extra,
            )
        except Exception as exc:
            logger.error(
                f"Doubao 请求失败: mode={resolved_mode}, model={requested_model}, "
                f"images={image_count}, request_summary={request_summary!r}, error={exc}"
            )
            raise
        t1 = time.time()
        logger.debug(f"Doubao 网络请求耗时: {(t1-t0)*1000:.1f}ms")
        msg = response.choices[0].message
        content = (getattr(msg, "content", None) or "").strip()
        if not content:
            reasoning = getattr(msg, "reasoning_content", None)
            if isinstance(reasoning, str) and reasoning.strip():
                content = reasoning.strip()

        usage = getattr(response, "usage", None)
        usage_dict = None
        if usage is not None:
            usage_dict = {}
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = getattr(usage, key, None)
                if value is not None:
                    usage_dict[key] = int(value)

        preview = content[:200] + ("..." if len(content) > 200 else "")
        logger.debug(
            f"Doubao 请求完成: mode={resolved_mode}, model={requested_model}, "
            f"images={image_count}, content_preview={preview!r}, usage={usage_dict or {}}"
        )
        return {"content": content, "raw_response": response, "usage": usage_dict or {}}


def _to_text_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    encoded: List[Dict[str, Any]] = []
    for msg in messages:
        msg2 = dict(msg)
        content = msg.get("content")
        if isinstance(content, str):
            msg2["content"] = content
            encoded.append(msg2)
            continue
        if not isinstance(content, list):
            msg2["content"] = str(content or "")
            encoded.append(msg2)
            continue
        msg2["content"] = _flatten_content_to_text(content)
        encoded.append(msg2)
    return encoded


def _to_vision_messages(messages: List[Dict[str, Any]], *, image_urls: List[str]) -> List[Dict[str, Any]]:
    normalized_urls = [url.strip() for url in (image_urls or []) if isinstance(url, str) and url.strip()]
    if not normalized_urls or not messages:
        return messages

    encoded = list(messages)
    last_index = len(encoded) - 1
    last_msg = dict(encoded[last_index])
    text = str(last_msg.get("content") or "")
    parts: List[Dict[str, Any]] = []
    for url in normalized_urls:
        parts.append({"type": "image_url", "image_url": {"url": url}})
    parts.append({"type": "text", "text": text})
    last_msg["content"] = parts
    encoded[last_index] = last_msg
    return encoded


def _flatten_content_to_text(content: List[Any]) -> str:
    texts: List[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        ptype = part.get("type")
        if ptype == "text":
            text = str(part.get("text") or "").strip()
            if text:
                texts.append(text)
            continue
        if ptype == "image_url":
            image_url = part.get("image_url") or {}
            url = image_url.get("url") if isinstance(image_url, dict) else None
            if isinstance(url, str) and url.strip():
                texts.append(f"![image]({url.strip()})")
            continue
        if ptype == "image":
            image = part.get("image")
            if isinstance(image, UnifiedImage):
                texts.append(f"![image](data:{image.mime_type};base64,{image.to_base64()})")
            continue
    return "\n\n".join(texts).strip()


__all__ = ["DoubaoLLM"]
