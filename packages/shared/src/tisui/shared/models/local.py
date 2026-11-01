from __future__ import annotations

from typing import Any, Dict, List, Optional

from .custom import CustomLLM

# llama.cpp server 一般无鉴权, api_key 缺失时用占位值
_LOCAL_DEFAULT_API_KEY = "not-needed"

# llama.cpp jinja chat 模板参数: 按请求级关闭思考。
# 服务端 chat-template-kwargs 常默认开启 thinking, 思考 token 会挤占 content 输出
# (表现为返回 200 tokens 但 content 为空); llama.cpp 不识别顶层 enable_thinking,
# 必须经 chat_template_kwargs 传入。
_LOCAL_NO_THINKING_EXTRA_BODY = {"chat_template_kwargs": {"enable_thinking": False}}


class LocalLLM(CustomLLM):
    """本地 llama.cpp server (OpenAI 兼容端点, /v1/chat/completions) 适配器。

    与 CustomLLM 的差异:
    1. api_key 可选: 本地服务一般无鉴权, 缺失时用占位值, 不抛 MissingAPIKeyError;
    2. 默认关闭思考: 经 llama.cpp 专属的 chat_template_kwargs 传参,
       避免思考 token 挤占 content 导致返回空内容。
    """

    def __init__(self, **kwargs):
        if not kwargs.get("api_key"):
            kwargs["api_key"] = _LOCAL_DEFAULT_API_KEY
        super().__init__(**kwargs)
        self.provider = "local"

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        *,
        mode: str = "text",
        image_data_url: Optional[str] = None,
        image_urls: Optional[List[str]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        # 调用方未显式指定 extra_body 时, 用 chat_template_kwargs 关闭思考;
        # 显式指定则尊重调用方 (如需要保留思考链时可自行覆盖)。
        if "extra_body" not in kwargs:
            kwargs["extra_body"] = dict(_LOCAL_NO_THINKING_EXTRA_BODY)
        return super().chat_completion(
            messages,
            mode=mode,
            image_data_url=image_data_url,
            image_urls=image_urls,
            **kwargs,
        )


__all__ = ["LocalLLM"]
