import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw

from tisui.agent.preprocess import preprocess_for_action
from tisui.shared.config import settings


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _draw_boxes(
    image_path: Path,
    items: list[dict[str, Any]],
    *,
    bbox_key: str,
    label_key: str,
    output_path: Path,
) -> None:
    with Image.open(image_path) as image:
        canvas = image.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        for item in items:
            bbox = item.get(bbox_key)
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue
            try:
                left, top, right, bottom = [int(value) for value in bbox]
            except (TypeError, ValueError):
                continue
            if right <= left or bottom <= top:
                continue
            draw.rectangle([left, top, right, bottom], outline="red", width=3)
            label = str(item.get(label_key) or "").strip()
            if label:
                draw.text((left + 4, max(0, top - 16)), label, fill="red")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path, format="PNG")


def test_preprocess_debug_pipeline_google_png() -> None:
    config = settings.vision_config
    if not (config.api_key and config.base_url and config.model):
        pytest.skip("缺少 vision 模型配置，跳过用例")

    tests_dir = Path(__file__).resolve().parent
    image_path = tests_dir / "input" / "google.png"
    if not image_path.exists():
        pytest.skip("缺少 tests/input/google.png，跳过用例")

    output_dir = tests_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    image_bytes = image_path.read_bytes()
    action_text = "搜索 pymidscene 看看定位在哪里?"

    result = preprocess_for_action(
        image_bytes,
        action_text,
        resize_max_side=500,
        debug=True,
        debug_output_path=output_dir / "google.json",
    )

    regions_json_path = output_dir / "google_resized.json"
    action_regions_json_path = output_dir / "google_action_regions.json"
    target_json_path = output_dir / "google.json"

    assert result.preprocess.regions
    assert result.target_hint is not None
    assert result.target_hint.intersect_bbox
    assert regions_json_path.exists()
    assert action_regions_json_path.exists()
    assert target_json_path.exists()

    regions_payload = _load_json(regions_json_path)
    action_regions_payload = _load_json(action_regions_json_path)
    target_payload = _load_json(target_json_path)

    assert isinstance(regions_payload.get("regions"), list)
    assert len(regions_payload["regions"]) > 0
    assert isinstance(action_regions_payload.get("regions"), list)
    assert len(action_regions_payload["regions"]) > 0
    assert isinstance(target_payload.get("elements"), list)
    assert len(target_payload["elements"]) > 0

    resized_image_output = output_dir / "google_resized.png"
    action_regions_image_output = output_dir / "google_action_regions.png"
    target_image_output = output_dir / "google.png"

    _draw_boxes(
        image_path,
        regions_payload["regions"],
        bbox_key="bbox",
        label_key="name",
        output_path=resized_image_output,
    )
    _draw_boxes(
        image_path,
        action_regions_payload["regions"],
        bbox_key="bbox",
        label_key="name",
        output_path=action_regions_image_output,
    )
    _draw_boxes(
        image_path,
        target_payload["elements"],
        bbox_key="bbox",
        label_key="type",
        output_path=target_image_output,
    )

    assert resized_image_output.exists()
    assert resized_image_output.stat().st_size > 0
    assert action_regions_image_output.exists()
    assert action_regions_image_output.stat().st_size > 0
    assert target_image_output.exists()
    assert target_image_output.stat().st_size > 0
