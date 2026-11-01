"""
坐标映射与几何工具 (v2)。

核心约定:
- 布局区域 bbox 存 base 坐标。
- 精定位从 raw 裁 patch: region(base) --scale--> raw, 外扩后裁 raw。
- patch 内模型输出直接 + patch_origin 回到 raw。
- 对外 bbox_relative 一律用 raw_size 归一化。
"""

from __future__ import annotations

from typing import Any

from PIL import Image

from .types import BBox, CroppedPatch, RelativeBBox


def normalize_bbox(value: Any) -> BBox | None:
    """把模型输出的 bbox 规整为 [left, top, right, bottom] 且左上<右下; 非法返回 None。"""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        left = int(round(float(value[0])))
        top = int(round(float(value[1])))
        right = int(round(float(value[2])))
        bottom = int(round(float(value[3])))
    except (TypeError, ValueError):
        return None
    if right < left:
        left, right = right, left
    if bottom < top:
        top, bottom = bottom, top
    if right <= left or bottom <= top:
        return None
    return [left, top, right, bottom]


def to_relative(bbox_raw: BBox, raw_size: tuple[int, int]) -> RelativeBBox:
    """按 raw 尺寸归一化 (v1 的头号坐标 bug 在此固定用 raw)。"""
    w = max(1, raw_size[0])
    h = max(1, raw_size[1])
    return [bbox_raw[0] / w, bbox_raw[1] / h, bbox_raw[2] / w, bbox_raw[3] / h]


def normalize_relative_bbox(
    value: Any,
    *,
    patch_size: tuple[int, int] | None = None,
) -> RelativeBBox | None:
    """把模型输出的相对 bbox 规整为 [x1,y1,x2,y2] 且 ∈[0,1] 且左上<右下; 非法返回 None。

    容错 (仅当传入 patch_size 时启用, 供精定位使用; 不传时行为与旧版完全一致):
    - 疑似绝对像素 (任一坐标 > 1.5): 先按 patch 尺寸归一化再 clamp, 避免整框被 clamp
      塌缩而误判为非法 (模型偶发把像素坐标填进 relative_bbox 的情况)。
    - 退化框 (clamp 后零宽/零高但中心在图内): 以中心给最小尺寸而非直接判非法,
      保住这一次可点击的命中。
    """
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x1, y1, x2, y2 = float(value[0]), float(value[1]), float(value[2]), float(value[3])
    except (TypeError, ValueError):
        return None
    if patch_size is not None and max(x1, y1, x2, y2) > 1.5:
        pw, ph = max(1, patch_size[0]), max(1, patch_size[1])
        x1, x2 = x1 / pw, x2 / pw
        y1, y2 = y1 / ph, y2 / ph
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    x1, y1 = max(0.0, min(1.0, x1)), max(0.0, min(1.0, y1))
    x2, y2 = max(0.0, min(1.0, x2)), max(0.0, min(1.0, y2))
    if x2 <= x1 or y2 <= y1:
        if patch_size is None:
            return None
        # 退化框保底: 取中心 + 最小尺寸 (约 1px), 避免把模型命中直接丢掉。
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        hw, hh = 1.0 / max(1, patch_size[0]), 1.0 / max(1, patch_size[1])
        x1, x2 = max(0.0, cx - hw), min(1.0, cx + hw)
        y1, y2 = max(0.0, cy - hh), min(1.0, cy + hh)
        if x2 <= x1 or y2 <= y1:
            return None
    return [x1, y1, x2, y2]


def relative_to_abs(rel: RelativeBBox, size: tuple[int, int]) -> BBox:
    """相对 bbox(0~1) → 绝对像素 bbox (按给定图片尺寸)。"""
    w = max(1, size[0])
    h = max(1, size[1])
    return [
        int(round(rel[0] * w)),
        int(round(rel[1] * h)),
        int(round(rel[2] * w)),
        int(round(rel[3] * h)),
    ]


def map_region_base_to_raw(
    bbox_base: BBox,
    base_size: tuple[int, int],
    raw_size: tuple[int, int],
) -> BBox:
    """区域 bbox: base 坐标 → raw 坐标。"""
    sx = raw_size[0] / max(1, base_size[0])
    sy = raw_size[1] / max(1, base_size[1])
    return [
        int(bbox_base[0] * sx),
        int(bbox_base[1] * sy),
        int(bbox_base[2] * sx),
        int(bbox_base[3] * sy),
    ]


def map_overview_bbox_to_base(
    bbox_overview: BBox,
    overview_size: tuple[int, int],
    base_size: tuple[int, int],
) -> BBox:
    """区域 bbox: overview 坐标 → base 坐标。"""
    sx = base_size[0] / max(1, overview_size[0])
    sy = base_size[1] / max(1, overview_size[1])
    return [
        int(bbox_overview[0] * sx),
        int(bbox_overview[1] * sy),
        int(bbox_overview[2] * sx),
        int(bbox_overview[3] * sy),
    ]


def expand_bbox_by_image(
    bbox: BBox,
    image_size: tuple[int, int],
    ratio: float,
) -> BBox:
    """按【图像尺寸】外扩并 clamp (v2 修正: 不按 bbox 自身尺寸外扩)。"""
    ex = int(image_size[0] * ratio)
    ey = int(image_size[1] * ratio)
    left = max(0, bbox[0] - ex)
    top = max(0, bbox[1] - ey)
    right = min(image_size[0], bbox[2] + ex)
    bottom = min(image_size[1], bbox[3] + ey)
    if right <= left:
        right = min(image_size[0], left + 1)
    if bottom <= top:
        bottom = min(image_size[1], top + 1)
    return [left, top, right, bottom]


def crop_patch_from_raw(
    raw_image: Image.Image,
    region_bbox_base: BBox,
    *,
    base_size: tuple[int, int],
    raw_size: tuple[int, int],
    expand_ratio: float,
    source_region_id: str = "",
) -> CroppedPatch:
    """
    区域 base bbox → raw bbox → 外扩 → 从 raw 原分辨率裁剪。

    高分辨率只花在目标区域: patch 保留原生像素。
    """
    bbox_raw = map_region_base_to_raw(region_bbox_base, base_size, raw_size)
    l, t, r, b = expand_bbox_by_image(bbox_raw, raw_size, expand_ratio)
    patch_image = raw_image.crop((l, t, r, b))
    return CroppedPatch(
        patch_image=patch_image,
        bbox_in_raw=[l, t, r, b],
        source_region_id=source_region_id,
    )


def map_patch_bbox_to_raw(bbox_patch: BBox, patch_origin: tuple[int, int]) -> BBox:
    """patch 内 bbox → raw (patch 直接从 raw 裁, 只需平移)。"""
    ox, oy = patch_origin
    return [
        bbox_patch[0] + ox,
        bbox_patch[1] + oy,
        bbox_patch[2] + ox,
        bbox_patch[3] + oy,
    ]


def compute_action_point(bbox: BBox, hint: str) -> list[int]:
    """根据 action_point_hint 计算操作点 (bbox 与结果同一坐标系)。"""
    left, top, right, bottom = bbox
    w = right - left
    h = bottom - top
    mapping = {
        "center": (left + w // 2, top + h // 2),
        "left_side": (left + w // 4, top + h // 2),
        "right_side": (left + 3 * w // 4, top + h // 2),
        "icon_area": (left + w // 4, top + h // 2),
        "text_area": (left + w // 3, top + h // 2),
    }
    x, y = mapping.get(hint, mapping["center"])
    return [int(x), int(y)]


def compute_iou(a: BBox, b: BBox) -> float:
    """两个 bbox 的 IoU。"""
    left = max(a[0], b[0])
    top = max(a[1], b[1])
    right = min(a[2], b[2])
    bottom = min(a[3], b[3])
    if left >= right or top >= bottom:
        return 0.0
    inter = (right - left) * (bottom - top)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / max(area_a + area_b - inter, 1)


__all__ = [
    "normalize_bbox",
    "to_relative",
    "normalize_relative_bbox",
    "relative_to_abs",
    "map_region_base_to_raw",
    "map_overview_bbox_to_base",
    "expand_bbox_by_image",
    "crop_patch_from_raw",
    "map_patch_bbox_to_raw",
    "compute_action_point",
    "compute_iou",
]
