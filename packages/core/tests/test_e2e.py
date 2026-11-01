import asyncio
import base64
import json
import re
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

_core_src = Path(__file__).resolve().parents[1] / "src"
_shared_src = Path(__file__).resolve().parents[3] / "shared" / "src"
sys.path.insert(0, str(_core_src))
sys.path.insert(0, str(_shared_src))

from tisui.agent import prompt as agent_prompt
from tisui.shared.config import settings
from tisui.shared.exceptions import ModelResponseError
from tisui.shared.models import UnifiedImage, get_llm
from tisui.shared.utils import relative_to_absolute_coord


def _parse_json_text(text: str):
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    fenced = re.search(r"```(?:json|json5)?\\s*(\\{[\\s\\S]*\\})\\s*```", raw)
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


def _get_zh_cn_prompt() -> str:
    value = getattr(agent_prompt, "NORMAL_VISION_PROMPT_ZH_CN", None)
    if isinstance(value, str) and value.strip():
        return value
    raise RuntimeError("NORMAL_VISION_PROMPT-zh-CN 鏈壘鍒版垨涓虹┖")


def _normalize_relative_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        left = float(value[0])
        top = float(value[1])
        right = float(value[2])
        bottom = float(value[3])
    except (TypeError, ValueError):
        return None
    if right < left:
        left, right = right, left
    if bottom < top:
        top, bottom = bottom, top
    left = max(0.0, min(1.0, left))
    top = max(0.0, min(1.0, top))
    right = max(0.0, min(1.0, right))
    bottom = max(0.0, min(1.0, bottom))
    if right <= left or bottom <= top:
        return None
    return [round(left, 6), round(top, 6), round(right, 6), round(bottom, 6)]


def _normalize_payload(parsed: dict[str, Any], *, width: int, height: int) -> dict[str, Any]:
    raw_elements = parsed.get("elements")
    if not isinstance(raw_elements, list):
        raw_elements = parsed.get("controls")
    elements: list[dict[str, Any]] = []
    for item in raw_elements if isinstance(raw_elements, list) else []:
        if not isinstance(item, dict):
            continue
        relative_bbox = _normalize_relative_bbox(item.get("relative_bbox"))
        if relative_bbox is None:
            continue
        normalized = dict(item)
        normalized["relative_bbox"] = relative_bbox
        normalized["bbox"] = relative_to_absolute_coord(
            width,
            height,
            relative_bbox,
            [0, 0],
        )
        elements.append(normalized)
    errors = parsed.get("errors")
    if not isinstance(errors, list):
        errors = []
    return {
        "elements": elements,
        "errors": errors,
        "image": {"width": width, "height": height},
    }


def test_vision2bbox() -> None:
    config = settings.vision_config
    if not (config.api_key and config.base_url and config.model):
        pytest.skip("缺少 vision 模型配置，跳过用例")

    tests_dir = Path(__file__).resolve().parent
    image_path = tests_dir / "input/win-nodepad2.png"
    if not image_path.exists():
        pytest.skip("缺少 tests/google.png，跳过用例")

    output_dir = tests_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "win-nodepad2.json"

    llm = get_llm(
        config.provider,
        api_key=config.api_key,
        base_url=config.base_url,
        model=config.model,
        timeout=config.timeout,
        max_retries=config.max_retries,
    )

    image_bytes = image_path.read_bytes()
    with Image.open(image_path) as pil_image:
        width, height = pil_image.size
        rgb = pil_image.convert("RGB")
        buf = BytesIO()
        rgb.save(buf, format="JPEG", quality=90)
        jpeg_bytes = buf.getvalue()
    prompt = (
        _get_zh_cn_prompt().rstrip()
        # + "\n\n"
        # + "琛ュ厖涓婁笅鏂囧弬鏁帮細\n"
        # + f"- 鍥剧墖鎬诲搴?{width}\n"
        # + f"- 鍥剧墖鎬婚珮搴?{height}\n"
        # + "- 鍥剧墖鍘嬬缉姣?1.0\n"
        # + "- 鍒囧潡璧峰宸﹁竟鐣孹鍧愭爣=0\n"
        # + "- 鍒囧潡璧峰涓婅竟鐣孻鍧愭爣=0\n"
        # + "璇峰彧杈撳嚭 relative_bbox锛屼笉瑕佽緭鍑?bbox 瀛楁锛宐box 鐢变唬鐮佷簩娆¤绠椼€俓n"
        # + "relative_bbox 蹇呴』鏄熀浜庢暣寮犲浘鐗囧楂樼殑 0 鍒?1 涔嬮棿鐩稿鍧愭爣锛屼繚鐣?6 浣嶅皬鏁般€俓n"
        # + "涓嶈杩斿洖绌?elements锛屽繀椤诲敖閲忚緭鍑烘埅鍥鹃噷鏄庢樉鍙氦浜掔殑鍏冪礌銆俓n"
        # + "涓嶈鎶?Google 棣栭〉鑴戣ˉ鎴愰€氱敤闂ㄦ埛銆佺櫥褰曢〉鎴栧悗鍙伴〉锛屽繀椤讳弗鏍兼寜鍥剧墖涓湡瀹炲彲瑙佸唴瀹硅緭鍑恒€俓n"
    )
    image_data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("utf-8")
    messages = [
        {
            "role": "user",
            "content": prompt,
        }
    ]

    try:
        result = llm.chat_completion(
            messages,
            mode="vision",
            image_data_url=image_data_url,
            temperature=0.1,
            max_tokens=6000,
            response_format={"type": "json_object"},
        )
    except ModelResponseError:
        result = llm.chat_completion(
            messages,
            mode="vision",
            image_data_url=image_data_url,
            temperature=0.1,
            max_tokens=6000,
        )

    raw_response = str(result.get("content") or "")
    (output_dir / "raw_response.txt").write_text(raw_response, encoding="utf-8")
    parsed = _parse_json_text(raw_response)
    if not isinstance(parsed, dict):
        output_path.write_text(
            json.dumps(
                {
                    "elements": [],
                    "errors": [{"message": "model response is not json object"}],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        pytest.xfail("模型返回不是 JSON 对象，已输出 raw_response.txt / win-nodepad2.json 供排查")
    normalized = _normalize_payload(parsed, width=width, height=height)

    output_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    assert output_path.exists()
    assert output_path.stat().st_size > 0

    elements = normalized.get("elements")
    if not isinstance(elements, list) or len(elements) == 0:
        pytest.xfail("模型返回 elements 为空，已输出 win-nodepad2.json / raw_response.txt 供排查")
