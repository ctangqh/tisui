"""视觉调用的公共 IO 工具。

供 query / task_builder 等需要"截图喂给 VLM + 解析 JSON 回复"的模块复用:
    - image_to_data_url: 截图字节 → 降采样 → base64 data URL (invoke_vision_llm 入参)
    - parse_json_loose : 容错解析模型返回的 JSON (裸 JSON / ```json 围栏 / 截取 {})
单一来源, 避免各处重复实现导致行为不一致。
"""

from __future__ import annotations

import base64
import json
import re
from io import BytesIO
from typing import Any

from PIL import Image


def image_to_data_url(image: bytes, *, max_side: int = 1024) -> str:
    """把截图字节编码为 PNG data URL; 超过 max_side 时等比降采样。"""
    with Image.open(BytesIO(image)) as pil_image:
        pil_image.load()
        width, height = pil_image.size
        if max(width, height) > max_side:
            scale = max_side / float(max(width, height))
            pil_image = pil_image.resize(
                (max(1, round(width * scale)), max(1, round(height * scale))),
                Image.Resampling.LANCZOS,
            )
        save_image = (
            pil_image if pil_image.mode in ("RGB", "L", "RGBA") else pil_image.convert("RGB")
        )
        buffer = BytesIO()
        save_image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def parse_json_loose(text: str) -> Any:
    """容错解析模型返回文本为 JSON; 无法解析时返回 None。"""
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    fenced = re.search(r"```(?:json)?\s*([\[{][\s\S]*[\]}])\s*```", raw)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except Exception:
            pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except Exception:
            return None
    return None


__all__ = ["image_to_data_url", "parse_json_loose"]
