import json
from pathlib import Path

import pytest

from tisui.agent.preprocess import infer_operation_target, preprocess_image
from tisui.shared.config import settings


def _serialize_preprocess_context(ctx) -> dict:
    return {
        "image_hash": ctx.image_hash,
        "image": {
            "width": ctx.image_width,
            "height": ctx.image_height,
        },
        "image_resized": {
            "width": ctx.resized_width,
            "height": ctx.resized_height,
            "max_side": ctx.resize_max_side,
        },
        "page_anchors": ctx.page_anchors,
        "regions": [
            {
                "id": region.id,
                "name": region.name,
                "description": region.description,
                "z_index": region.z_index,
                "relative_bbox": region.relative_bbox,
                "bbox": region.bbox,
                "bbox_resized": region.bbox_resized,
                "page_grid_position": region.page_grid_position,
                "anchors": region.anchors,
                "raw": region.raw,
            }
            for region in ctx.regions
        ],
        "raw_regions_payload": ctx.raw_regions_payload,
    }


def _serialize_target_hint(result) -> dict:
    return {
        "action_text": result.action_text,
        "target_region_id": result.target_region_id,
        "target_region_name": result.target_region_name,
        "target_grid_position": result.target_grid_position,
        "target_grid_index": result.target_grid_index,
        "target_grid_bbox": result.target_grid_bbox,
        "intersect_bbox": result.intersect_bbox,
        "confidence": result.confidence,
        "reasoning": result.reasoning,
        "candidates": [
            {
                "region_id": item.region_id,
                "region_name": item.region_name,
                "grid_position": item.grid_position,
                "confidence": item.confidence,
                "reason": item.reason,
            }
            for item in result.candidates
        ],
        "raw_llm_result": result.raw_llm_result,
    }


def test_preprocess_infer_google_search_pymidscene() -> None:
    config = settings.vision_config
    if not (config.api_key and config.base_url and config.model):
        pytest.skip("缺少 vision 模型配置，跳过用例")

    tests_dir = Path(__file__).resolve().parent
    image_path = tests_dir / "input" / "google.png"
    if not image_path.exists():
        pytest.skip("缺少 tests/input/google.png，跳过用例")

    output_dir = tests_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "google_search_pymidscene_infer.json"

    action_text = "搜索 pymidscene 看看定位在哪里?"
    image_bytes = image_path.read_bytes()

    preprocess_ctx = preprocess_image(image_bytes, resize_max_side=500)
    if not preprocess_ctx.regions:
        output_path.write_text(
            json.dumps(
                {
                    "action_text": action_text,
                    "preprocess": _serialize_preprocess_context(preprocess_ctx),
                    "target_hint": None,
                    "errors": [{"message": "preprocess returned empty regions"}],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        pytest.xfail("预处理未识别到区域，已输出 google_search_pymidscene_infer.json 供排查")

    target_hint = infer_operation_target(preprocess_ctx, action_text)
    output_path.write_text(
        json.dumps(
            {
                "action_text": action_text,
                "preprocess": _serialize_preprocess_context(preprocess_ctx),
                "target_hint": _serialize_target_hint(target_hint),
                "errors": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    assert output_path.exists()
    assert output_path.stat().st_size > 0
    assert target_hint.target_region_name
    assert target_hint.intersect_bbox
