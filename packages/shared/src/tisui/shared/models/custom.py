from __future__ import annotations

import inspect
from typing import Any, Dict, List, Optional

from openai import OpenAI

from tisui.shared.config import settings
from tisui.shared.exceptions import MissingAPIKeyError
from tisui.shared.logger import logger

from .base import BaseLLM
from .types import ModelCapabilities, UnifiedImage


_OPENAI_INIT_PARAMS = inspect.signature(OpenAI.__init__).parameters
_OPENAI_SUPPORTS_TRUST_ENV = "trust_env" in _OPENAI_INIT_PARAMS


def make_openai_client(
    *,
    api_key: str,
    base_url: Optional[str] = None,
    timeout: Optional[int] = None,
    max_retries: int = 2,
) -> OpenAI:
    """构造 openai.OpenAI 客户端, 兼容 openai 1.x (支持 trust_env) 与 2.x (移除 trust_env)。

    openai 1.x: 传 trust_env=False 屏蔽系统 HTTP_PROXY/HTTPS_PROXY。
    openai 2.x: 签名不再接受 trust_env, 直接忽略该参数。
    两种版本都不会让客户端被系统代理意外劫持 (2.x 默认已不再读 env)。
    """
    kwargs: Dict[str, Any] = {
        "api_key": api_key,
        "max_retries": max_retries,
    }
    if base_url:
        kwargs["base_url"] = base_url
    if timeout is not None:
        kwargs["timeout"] = timeout
    if _OPENAI_SUPPORTS_TRUST_ENV:
        kwargs["trust_env"] = False
    return OpenAI(**kwargs)


class CustomLLM(BaseLLM):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        llm_config = settings.llm_config

        self.api_key = self.api_key or llm_config.api_key
        if not self.api_key:
            raise MissingAPIKeyError("LLM_API_KEY 未配置")

        self.base_url = self.base_url or llm_config.base_url
        self.model = self.model or llm_config.model
        self.provider = "openai"
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
            supports_structured_output=True,
            supports_system_prompt=True,
            supports_tool_calling=True,
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
        if "tools" in kwargs:
            extra["tools"] = kwargs.get("tools")
        if "tool_choice" in kwargs:
            extra["tool_choice"] = kwargs.get("tool_choice")
        # 默认关闭深度思考(thinking): dashscope 的 qwen3 系列推理模型默认开启思维链,
        # 会为感知/格式化类任务生成大量无用的思考输出 (单轮可达数千 tokens, 拖慢速度
        # 并耗尽 explore 的 token 预算)。需要推理时可通过 kwargs["enable_thinking"]=True
        # 或 kwargs["extra_body"] 显式覆盖。
        if "extra_body" in kwargs:
            extra["extra_body"] = kwargs.get("extra_body")
        else:
            extra["extra_body"] = {"enable_thinking": kwargs.get("enable_thinking", False)}

        request_summary = self.summarize_messages(messages)
        logger.debug(
            f"Custom 请求开始: mode={resolved_mode}, model={requested_model}, "
            f"messages={len(prepared_messages)}, images={image_count}, "
            f"temperature={kwargs.get('temperature', 0.1)}, max_tokens={kwargs.get('max_tokens', 4096)}, "
            f"extra_body={extra.get('extra_body')!r}, response_format={extra.get('response_format')!r}, "
            f"request_summary={request_summary!r}"
        )
        request_kwargs: Dict[str, Any] = {
            "model": requested_model,
            "messages": prepared_messages,
            "temperature": kwargs.get("temperature", 0.1),
            "max_tokens": kwargs.get("max_tokens", 4096),
            **extra,
        }
        try:
            response = self.client.chat.completions.create(**request_kwargs)
        except Exception as exc:
            # 兼容不支持 enable_thinking 的 OpenAI 端点 (如官方 gpt 系列):
            # 参数不被识别时报 400, 去掉 extra_body 重试一次。
            if request_kwargs.get("extra_body") is not None and _is_unknown_param_error(str(exc)):
                logger.warning(f"端点不支持 extra_body 参数, 去掉后重试: {str(exc)[:200]}")
                request_kwargs.pop("extra_body", None)
                response = self.client.chat.completions.create(**request_kwargs)
            else:
                logger.error(
                    f"Custom 请求失败: mode={resolved_mode}, model={requested_model}, "
                    f"images={image_count}, request_summary={request_summary!r}, error={exc}"
                )
                raise
        msg = response.choices[0].message
        content = (getattr(msg, "content", None) or "").strip()

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
            f"Custom 请求完成: mode={resolved_mode}, model={requested_model}, "
            f"images={image_count}, content_preview={preview!r}, usage={usage_dict or {}}"
        )
        return {"content": content, "raw_response": response, "usage": usage_dict or {}}


def _is_unknown_param_error(err_text: str) -> bool:
    """判断 OpenAI 端点错误是否为「参数不被识别」(如 gpt 端点不支持 enable_thinking)。"""
    lowered = (err_text or "").lower()
    return any(
        marker in lowered
        for marker in ("unrecognized request argument", "unknown parameter", "unexpected keyword",
                       "enable_thinking", "extra_body")
    )


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


__all__ = ["CustomLLM", "make_openai_client"]
