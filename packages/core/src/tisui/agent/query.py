"""SDK 视觉问答 (一期同步) —— ai_query 的执行层。

纯读取: 截图 → 一次 VLM 调用 → 解析 JSON。不涉及定位管道与坐标缩放。
按自然语言需求从当前界面截图中提取结构化数据。

模型调用复用 locate 已验证的路径: shared.models.invoker.invoke_vision_llm
(接收 image_data_url + 文本 prompt, 内部处理 vision 模式与 json fallback)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tisui.agent.vision_io import image_to_data_url, parse_json_loose
from tisui.shared.models.invoker import invoke_vision_llm


@dataclass
class QueryResult:
    data: Any
    raw_response: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


def run_query(image: bytes, query: str, *, max_image_side: int = 1024) -> QueryResult:
    """从截图中按 query 提取数据, 返回 QueryResult (data 为解析后的结果)。"""
    image_data_url = image_to_data_url(image, max_side=max_image_side)
    result = invoke_vision_llm(image_data_url=image_data_url, content=_build_prompt(query))
    raw = str(result.get("content") or "")
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    return QueryResult(data=_extract_data(raw), raw_response=raw, usage=dict(usage or {}))


# ---- 内部 ---------------------------------------------------------------

def _build_prompt(query: str) -> str:
    return (
        "你是一个从界面截图中提取信息的视觉助手。\n"
        "请根据用户的数据需求, 仔细观察截图并提取信息。\n"
        '只输出一个 JSON 对象, 且必须包含唯一键 "data", 其值为提取到的结果 '
        "(可以是字符串/数字/布尔/数组/对象)。\n"
        '如果截图中找不到, 将 "data" 置为 null。\n'
        "不要输出任何解释或多余文字, 只输出 JSON。\n\n"
        f"用户的数据需求:\n{query.strip()}"
    )


def _extract_data(raw: str) -> Any:
    parsed = parse_json_loose(raw)
    if isinstance(parsed, dict) and "data" in parsed:
        return parsed["data"]
    return parsed  # 容错: 模型未包裹 data 时直接返回解析结果


__all__ = ["run_query", "QueryResult"]
