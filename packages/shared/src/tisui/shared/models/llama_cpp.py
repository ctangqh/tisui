from __future__ import annotations

from typing import Any, Dict, List, Optional

from .local import LocalLLM

# llama.cpp llama-server 一般无鉴权, api_key 缺失时用占位值 (沿用 local.py 惯例)
_LLAMACPP_DEFAULT_API_KEY = "not-needed"


class LlamaCppLLM(LocalLLM):
    """llama.cpp llama-server (OpenAI 兼容端点 /v1/chat/completions) 适配器。

    与 LocalLLM 同构 (同为 llama.cpp), 仅 provider 名独立为 "llamacpp",
    便于配置中显式区分 local / llamacpp。

    关闭思考模式的机制继承自 LocalLLM:
    - llama.cpp 不识别顶层 enable_thinking / think, 必须经
      chat_template_kwargs={"enable_thinking": False} 传参 (jinja 模板按请求级关闭思考);
    - 调用方显式传 extra_body 时尊重调用方 (如需保留思考链可自行覆盖)。
    """

    def __init__(self, **kwargs):
        if not kwargs.get("api_key"):
            kwargs["api_key"] = _LLAMACPP_DEFAULT_API_KEY
        super().__init__(**kwargs)
        self.provider = "llamacpp"


__all__ = ["LlamaCppLLM"]
