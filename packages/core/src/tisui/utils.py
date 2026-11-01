from __future__ import annotations

from typing import TypedDict

from tisui.shared.utils import relative_to_absolute_coord


class BBoxConversionResult(TypedDict):
    absolute_bbox: list[int]
    relative_bbox: list[float]


def convert_bbox_to_original_image(
    relative_bbox: list[float],
    *,
    image_width: int,
    image_height: int,
    start_coordinate: list[int],
    original_width: int | None = None,
    original_height: int | None = None,
) -> BBoxConversionResult:
    absolute_bbox = relative_to_absolute_coord(
        image_width,
        image_height,
        relative_bbox,
        start_coordinate,
    )
    if len(absolute_bbox) != 4:
        raise ValueError("relative_bbox 必须是 [x1, y1, x2, y2]")

    target_width = int(original_width if original_width is not None else image_width)
    target_height = int(original_height if original_height is not None else image_height)

    relative_bbox_on_original = [
        round(absolute_bbox[0] / max(1, target_width), 6),
        round(absolute_bbox[1] / max(1, target_height), 6),
        round(absolute_bbox[2] / max(1, target_width), 6),
        round(absolute_bbox[3] / max(1, target_height), 6),
    ]

    return {
        "absolute_bbox": absolute_bbox,
        "relative_bbox": relative_bbox_on_original,
    }


__all__ = [
    "BBoxConversionResult",
    "convert_bbox_to_original_image",
]
