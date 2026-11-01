from __future__ import annotations

from typing import Any, Dict, List, Optional

from .custom import CustomLLM

# Ollama 本地服务一般无鉴权, api_key 缺失时用占位值, 不抛 MissingAPIKeyError
_OLLAMA_DEFAULT_API_KEY = "not-needed"

# Ollama 关闭思考: 顶层 think=false (OpenAI 兼容端点同样适用)。
# 注意 Ollama 不识别 chat_template_kwargs (llama.cpp 字段) 与 enable_thinking (dashscope 字段),
# 只能经顶层 think 关闭推理模型的思考链。
_OLLAMA_NO_THINKING_EXTRA_BODY = {"think": False}


class OllamaLLM(CustomLLM):
    """Ollama (OpenAI 兼容端点 /v1/chat/completions) 适配器。

    与 CustomLLM 的差异:
    1. api_key 可选: 本地服务一般无鉴权, 缺失时用占位值, 不抛 MissingAPIKeyError;
    2. 默认关闭思考: 经顶层 think=false 传参, 避免推理模型 (qwen3 等) 的
       思考链 token 挤占 content 输出 (表现为 content 为空或响应极慢);
    3. 调用方显式传 extra_body 时尊重调用方 (如需保留思考链可自行覆盖)。
    """

    def __init__(self, **kwargs):
        if not kwargs.get("api_key"):
            kwargs["api_key"] = _OLLAMA_DEFAULT_API_KEY
        super().__init__(**kwargs)
        self.provider = "ollama"

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        *,
        mode: str = "text",
        image_data_url: Optional[str] = None,
        image_urls: Optional[List[str]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        # 调用方未显式指定 extra_body 时, 用顶层 think=false 关闭思考;
        # 显式指定则尊重调用方 (如需要保留思考链时可自行覆盖)。
        if "extra_body" not in kwargs:
            kwargs["extra_body"] = dict(_OLLAMA_NO_THINKING_EXTRA_BODY)
        return super().chat_completion(
            messages,
            mode=mode,
            image_data_url=image_data_url,
            image_urls=image_urls,
            **kwargs,
        )


__all__ = ["OllamaLLM"]
