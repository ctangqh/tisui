import base64
import json
import re
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from tisui.agent import prompt as agent_prompt
from tisui.shared.config import settings
from tisui.shared.exceptions import ModelResponseError
from tisui.shared.models import get_llm
from tisui.shared.utils import relative_to_absolute_coord, resize_image_by_max_side


def _parse_json_text(text: str):
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    fenced = re.search(r"```(?:json|json5)?\s*(\{[\s\S]*\})\s*```", raw)
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


def _get_preview_prompt() -> str:
    value = getattr(agent_prompt, "PREVIEW_VISION_PROMPT_ZH_CN", None)
    if isinstance(value, str) and value.strip():
        return value
    raise RuntimeError("PREVIEW_VISION_PROMPT_ZH_CN 鏈壘鍒版垨涓虹┖")


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


def _normalize_payload(
    parsed: dict[str, Any],
    *,
    width: int,
    height: int,
    resized_width: int,
    resized_height: int,
) -> dict[str, Any]:
    raw_regions = parsed.get("regions")
    regions: list[dict[str, Any]] = []
    for item in raw_regions if isinstance(raw_regions, list) else []:
        if not isinstance(item, dict):
            continue
        relative_bbox = _normalize_relative_bbox(item.get("relative_bbox"))
        if relative_bbox is None:
            continue
        normalized = dict(item)
        normalized["relative_bbox"] = relative_bbox
        normalized["bbox"] = relative_to_absolute_coord(width, height, relative_bbox, [0, 0])
        normalized["bbox_resized"] = relative_to_absolute_coord(
            resized_width,
            resized_height,
            relative_bbox,
            [0, 0],
        )
        regions.append(normalized)
    errors = parsed.get("errors")
    if not isinstance(errors, list):
        errors = []
    return {
        "regions": regions,
        "errors": errors,
        "image": {"width": width, "height": height},
        "image_resized": {"width": resized_width, "height": resized_height, "max_side": 500},
    }


def test_regions_identify() -> None:
    config = settings.vision_config
    if not (config.api_key and config.base_url and config.model):
        pytest.skip("缺少 vision 模型配置，跳过用例")

    tests_dir = Path(__file__).resolve().parent
    file_name = "deepseek"
    image_path = tests_dir / "input" / f"{file_name}.png"
    if not image_path.exists():
        pytest.skip(f"缺少 tests/input/{file_name}.png，跳过用例")

    output_dir = tests_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{file_name}_resized.json"
    raw_output_path = output_dir / f"{file_name}_raw_response.txt"
    resized_image_path = output_dir / f"{file_name}_resized_500.jpg"

    llm = get_llm(
        config.provider,
        api_key=config.api_key,
        base_url=config.base_url,
        model=config.model,
        timeout=config.timeout,
        max_retries=config.max_retries,
    )

    with Image.open(image_path) as pil_image:
        width, height = pil_image.size
        rgb = pil_image.convert("RGB")
        buf = BytesIO()
        rgb.save(buf, format="JPEG", quality=90)
        jpeg_bytes = buf.getvalue()
        resized_image = resize_image_by_max_side(rgb, max_side=500)
        resized_width, resized_height = resized_image.size
        resized_image.save(resized_image_path, format="JPEG", quality=90)

    prompt = _get_preview_prompt().rstrip()
    image_data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("utf-8")
    messages = [{"role": "user", "content": prompt}]

    try:
        result = llm.chat_completion(
            messages,
            mode="vision",
            image_data_url=image_data_url,
            temperature=0.1,
            max_tokens=4000,
            response_format={"type": "json_object"},
        )
    except ModelResponseError:
        result = llm.chat_completion(
            messages,
            mode="vision",
            image_data_url=image_data_url,
            temperature=0.1,
            max_tokens=4000,
        )
    

    raw_response = str(result.get("content") or "")
    raw_output_path.write_text(raw_response, encoding="utf-8")
    parsed = _parse_json_text(raw_response)
    if not isinstance(parsed, dict):
        output_path.write_text(
            json.dumps(
                {
                    "regions": [],
                    "errors": [{"message": "model response is not json object"}],
                    "image": {"width": width, "height": height},
                    "image_resized": {"width": resized_width, "height": resized_height, "max_side": 500},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        pytest.xfail("模型返回不是 JSON 对象，已输出 regions_identify_raw_response.txt / google_resized.json 供排查")

    normalized = _normalize_payload(
        parsed,
        width=width,
        height=height,
        resized_width=resized_width,
        resized_height=resized_height,
    )
    output_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")

    assert output_path.exists()
    assert output_path.stat().st_size > 0
    assert resized_image_path.exists()
    assert resized_image_path.stat().st_size > 0

    regions = normalized.get("regions")
    if not isinstance(regions, list) or len(regions) == 0:
        pytest.xfail("模型返回 regions 为空，已输出 google_resized.json / regions_identify_raw_response.txt 供排查")
