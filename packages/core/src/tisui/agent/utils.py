from __future__ import annotations

import base64
from io import BytesIO

from PIL import Image as PILImage

from .types import ImageInfo, BBox, RelativeBBox, Coordinate, BBoxConversionResult

from tisui.shared.utils import relative_to_absolute_coord, resize_image_by_max_side

def get_bbox_action_point(bbox: BBox) -> Coordinate:
    left, top, right, bottom = bbox
    return [int((left + right) / 2), int((top + bottom) / 2)]

def resize_image_bbox_to_original_image_bbox(
    relative_bbox: RelativeBBox,
    *,
    resize_image_width: int,
    resize_image_height: int,
    start_coordinate: Coordinate,
    original_width: int | None = None,
    original_height: int | None = None,
) -> BBoxConversionResult:
    absolute_bbox = relative_to_absolute_coord(
        resize_image_width,
        resize_image_height,
        relative_bbox,
        start_coordinate,
    )
    if len(absolute_bbox) != 4:
        raise ValueError("relative_bbox 必须是 [x1, y1, x2, y2]")

    target_width = int(original_width if original_width is not None else resize_image_width)
    target_height = int(original_height if original_height is not None else resize_image_height)

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


def instant_image(image_bytes: bytes) -> ImageInfo:
    with PILImage.open(BytesIO(image_bytes)) as pil_image:
        pil_image.load()
        image_format = str(pil_image.format or "").upper()
        if image_format == "JPEG":
            image_format = "JPG"

        return {
            "height": pil_image.height,
            "width": pil_image.width,
            "image_format": image_format or "PNG",
            "byte_size": len(image_bytes),
            "image_bytes": image_bytes,
            "zoom_ratio": 1.0,
        }

def image_to_base64(image: ImageInfo) -> str:
    image_bytes = image.get("image_bytes") or b""
    if not image_bytes:
        return ""

    image_format = str(image.get("image_format") or "").upper()
    mime_type = {
        "PNG": "image/png",
        "JPG": "image/jpeg",
        "JPEG": "image/jpeg",
        "WEBP": "image/webp",
    }.get(image_format, "application/octet-stream")

    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"

__all__ = [
    "instant_image",
    "image_to_base64",
    "get_bbox_action_point",
    "resize_image_bbox_to_original_image_bbox",
    "resize_image_by_max_side",
]
