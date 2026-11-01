"""
① 预处理 (v2)

解码 → RGB → EXIF 方向校正 → base(约束 max_image_size) → overview(缩略图) → xxhash。
不做灰度/去色: 概览图保持 RGB, 降 token 只靠 overview 最长边 (<=500) 控分辨率。
"""

from __future__ import annotations

import time
from io import BytesIO

import xxhash

from PIL import Image, ImageOps

from tisui.shared.utils.images import resize_image_by_max_side

from .types import LocateOptions, PreprocessingResult


def perform_preprocessing(
    image_bytes: bytes,
    options: LocateOptions,
) -> PreprocessingResult:
    """从原始字节生成 raw / base / overview 三图 + 精确哈希。"""
    import time
    from tisui.shared.logger import logger

    start = time.time()
    ops: list[str] = []

    t0 = time.time()
    with Image.open(BytesIO(image_bytes)) as img:
        img.load()
        image = ImageOps.exif_transpose(img)      # EXIF 方向校正
        if image is not img:
            ops.append("exif_transpose")
    t1 = time.time()

    if image.mode != "RGB":
        image = image.convert("RGB")
        ops.append("to_rgb")
    t2 = time.time()

    raw_image = image
    raw_size = raw_image.size

    # base: 约束到 max_image_size
    base_image = _fit_within(raw_image, options.max_image_size)
    if base_image.size != raw_size:
        ops.append("fit_base")
    base_size = base_image.size
    t3 = time.time()

    # overview: 缩略图, 仅用于分区 (最长边 <=500, 复用 shared 工具)
    overview_image = resize_image_by_max_side(base_image)
    if overview_image.size != base_size:
        ops.append("fit_overview")
    overview_size = overview_image.size
    t4 = time.time()

    image_hash = xxhash.xxh64(image_bytes).hexdigest()
    t5 = time.time()

    # 详细耗时日志
    logger.debug(
        f"[Preprocess] 耗时: {(t5-start)*1000:.1f}ms, "
        f"decode+exif: {(t1-t0)*1000:.1f}ms, "
        f"convert_rgb: {(t2-t1)*1000:.1f}ms, "
        f"fit_base: {(t3-t2)*1000:.1f}ms, "
        f"fit_overview: {(t4-t3)*1000:.1f}ms, "
        f"hash: {(t5-t4)*1000:.1f}ms, "
        f"size: {len(image_bytes)/1024:.1f}KB, "
        f"raw_size: {raw_size}"
    )

    return PreprocessingResult(
        raw_image=raw_image,
        base_image=base_image,
        overview_image=overview_image,
        raw_size=raw_size,
        base_size=base_size,
        overview_size=overview_size,
        image_hash=image_hash,
        operations=ops,
        duration_ms=(time.time() - start) * 1000,
    )


# ---- helpers ----

def _fit_within(image: Image.Image, max_size: tuple[int, int]) -> Image.Image:
    """等比缩放使宽高分别不超过 max_size; 不放大。"""
    max_w, max_h = max_size
    w, h = image.size
    if w <= max_w and h <= max_h:
        return image
    scale = min(max_w / w, max_h / h)
    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
    return image.resize(new_size, Image.LANCZOS)


__all__ = ["perform_preprocessing"]
