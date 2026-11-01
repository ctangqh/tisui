"""
区域感知 · 多尺度视觉定位 (v2) 管道编排。

五阶段: ① 预处理 → ② 布局分区 → ③ 意图选区 → ④ 聚焦精定位 → ⑤ 后处理。

要点:
- 全程同步 (真实 invoke_* 均为同步), 不搞伪并行。
- 视觉调用只 2 类: overview 分区(便宜) + 小 patch 精定位(精准)。
- 消除盲猜: 选区约束在真实区域内; 兜底也走"整图精定位", 而非坐标空猜。
- 两级内存缓存: L1(hash+action → 结果), L2(hash → 布局, 意图无关)。
"""

from __future__ import annotations

import base64
import time
from collections import OrderedDict
from datetime import datetime, timezone
from io import BytesIO

from tisui.shared.config import settings
from tisui.shared.logger import logger

from .coords import crop_patch_from_raw, map_region_base_to_raw
from .fine import fine_locate_region
from .layout import perform_layout
from .postprocess import postprocess_elements
from .preprocess import perform_preprocessing
from .region_select import perform_region_selection
from .types import (
    CroppedPatch,
    FallbackRecord,
    LayoutResult,
    LocatedElement,
    LocateOptions,
    LocateResult,
    RegionSelection,
    StageDebugBbox,
    StageDebugImage,
    StageTrace,
)

_CACHE_CAP = 64
_L2_LAYOUT_CACHE: "OrderedDict[str, LayoutResult]" = OrderedDict()

# 小图直连阈值: raw 最长边 <= 该值时, overview 缩略图与原图同尺寸,
# 布局分区/意图选区零增益 → 跳过 ②③, 直接对整图做精定位。
# 取值对齐 overview 的 max_side (见 shared.utils.images.resize_image_by_max_side)。
_SMALL_IMAGE_MAX_SIDE = 500


def run_pipeline(
    image_bytes: bytes,
    action_text: str,
    *,
    options: LocateOptions | None = None,
) -> LocateResult:
    """v2 定位主入口 (签名与 core_bridge 约定保持不变)。"""
    opts = options or LocateOptions()
    debug_mode = opts.debug_mode if opts.debug_mode is not None else settings.debug
    t0 = time.time()
    traces: list[StageTrace] = []
    fallbacks: list[FallbackRecord] = []
    debug_stages: list[StageDebugImage] = []

    # ---- ① 预处理 ----
    logger.debug(f"[Pipeline] 开始: action='{action_text[:50]}'")
    stage_start = time.time()
    pre = perform_preprocessing(image_bytes, opts)
    traces.append(StageTrace(
        stage_name="preprocess",
        duration_ms=(time.time() - stage_start) * 1000,
        input_size=pre.raw_size,
        output_count=1,
        decisions=list(pre.operations),
    ))
    base_zoom = (pre.base_size[0] / pre.raw_size[0]) if pre.raw_size[0] else 1.0
    if debug_mode:
        debug_stages.append(_encode_stage_image(
            pre.base_image, stage="preprocess", bboxes=[],
            zoom_scale=base_zoom, duration_ms=traces[-1].duration_ms,
            decisions=list(pre.operations),
        ))

    # ---- L1 已移除: 精定位结果不做缓存 (VLM 随机性导致错误结果被锁死) ----
    # 保留 L2 (布局分区缓存) — 确定性强, 是主要提速来源。

    # ---- 小图直连判定 ----
    small_image = max(pre.raw_size) <= _SMALL_IMAGE_MAX_SIDE
    t1 = time.time()

    # ---- ② 布局分区 + ③ 意图选区 (小图直连时整体跳过) ----
    cache_hit: str | None = None
    layout = LayoutResult(layout_type="single_view")
    selection = RegionSelection()
    if small_image:
        logger.debug("[Pipeline] 小图，跳过 layout 和 region select")
    else:
        # ② 布局分区
        stage_start = time.time()
        if opts.enable_cache and pre.image_hash in _L2_LAYOUT_CACHE:
            layout = _L2_LAYOUT_CACHE[pre.image_hash]
            _L2_LAYOUT_CACHE.move_to_end(pre.image_hash)
            cache_hit = "l2"
        else:
            layout = perform_layout(
                pre.overview_image, opts,
                base_size=pre.base_size,
            )
            if opts.enable_cache:
                _store(_L2_LAYOUT_CACHE, pre.image_hash, layout)
        traces.append(StageTrace(
            stage_name="layout",
            duration_ms=(time.time() - stage_start) * 1000,
            model_calls=0 if cache_hit == "l2" else 1,
            model_name="vlm",
            input_size=pre.overview_size,
            output_count=len(layout.regions),
            decisions=[f"layout_type={layout.layout_type}", f"cache={cache_hit or 'miss'}"],
        ))
        if debug_mode:
            debug_stages.append(_encode_stage_image(
                pre.raw_image, stage="layout",
                bboxes=[
                    _region_debug_bbox(r, "candidate", base_size=pre.base_size, raw_size=pre.raw_size)
                    for r in layout.regions
                ],
                zoom_scale=1.0,
                duration_ms=traces[-1].duration_ms,
                model_calls=traces[-1].model_calls,
                decisions=list(traces[-1].decisions),
            ))
        t2 = time.time()

        # ③ 意图选区 (纯文本)
        stage_start = time.time()
        selection = perform_region_selection(layout, action_text, opts)
        if selection.is_fallback:
            fallbacks.append(FallbackRecord(
                stage="region_select",
                reason=selection.reasoning,
                fallback_to="largest_region" if selection.selected else "full_image",
                timestamp=_now(),
            ))
        traces.append(StageTrace(
            stage_name="region_select",
            duration_ms=(time.time() - stage_start) * 1000,
            model_calls=0 if len(layout.regions) <= 1 else 1,
            model_name="text_llm",
            output_count=len(selection.selected),
            decisions=[f"is_fallback={selection.is_fallback}"],
        ))
        if debug_mode:
            selected_ids = {r.region_id for r in selection.selected}
            debug_stages.append(_encode_stage_image(
                pre.raw_image, stage="region_select",
                bboxes=[
                    _region_debug_bbox(
                        r, "primary" if r.region_id in selected_ids else "candidate",
                        base_size=pre.base_size, raw_size=pre.raw_size,
                    )
                    for r in layout.regions
                ],
                zoom_scale=1.0,
                duration_ms=traces[-1].duration_ms,
                model_calls=traces[-1].model_calls,
                decisions=list(traces[-1].decisions),
            ))
        t3 = time.time()
        logger.debug(
            f"[Pipeline] Layout+RegionSelect耗时: layout={(t2-t1)*1000:.1f}ms, "
            f"region_select={(t3-t2)*1000:.1f}ms"
        )

    # ---- ④ 聚焦精定位 ----
    t4 = time.time()
    stage_start = time.time()
    raw_image = pre.raw_image
    selected_regions = selection.selected[: opts.max_regions_to_fine]
    all_elements: list[LocatedElement] = []
    fine_calls = 0
    for region in selected_regions:
        patch: CroppedPatch = crop_patch_from_raw(
            raw_image, region.bbox,
            base_size=pre.base_size,
            raw_size=pre.raw_size,
            expand_ratio=opts.region_expand_ratio,
            source_region_id=region.region_id,
        )
        fine_calls += 1
        region_elems = fine_locate_region(
            patch, action_text, opts, raw_size=pre.raw_size,
        )
        all_elements.extend(region_elems)
        if debug_mode:
            debug_stages.append(_build_fine_stage(patch, region_elems))

    # 整图精定位兜底
    fallback_used = False
    if not all_elements:
        direct_full = small_image
        if not direct_full:
            fallback_used = True
            fallbacks.append(FallbackRecord(
                stage="fine",
                reason="no elements from selected regions",
                fallback_to="full_image",
                timestamp=_now(),
            ))
        full_patch = CroppedPatch(
            patch_image=raw_image,
            bbox_in_raw=[0, 0, pre.raw_size[0], pre.raw_size[1]],
            source_region_id="full_image",
        )
        fine_calls += 1
        full_elems = fine_locate_region(full_patch, action_text, opts, raw_size=pre.raw_size)
        for elem in full_elems:
            if not direct_full:
                elem.locator_way = "region_fallback"
                elem.is_fallback = True
            all_elements.append(elem)
        if debug_mode:
            debug_stages.append(_build_fine_stage(full_patch, full_elems, fallback=not direct_full))

    traces.append(StageTrace(
        stage_name="fine",
        duration_ms=(time.time() - stage_start) * 1000,
        model_calls=fine_calls,
        model_name="vlm",
        input_size=pre.raw_size,
        output_count=len(all_elements),
        decisions=[
            f"regions={len(selected_regions)}",
            f"small_image={small_image}",
            f"fallback={fallback_used}",
        ],
    ))
    t5 = time.time()

    # ---- ⑤ 后处理 ----
    stage_start = time.time()
    elements, status, primary_index = postprocess_elements(
        all_elements, opts, fallback_used=fallback_used,
    )
    traces.append(StageTrace(
        stage_name="postprocess",
        duration_ms=(time.time() - stage_start) * 1000,
        output_count=len(elements),
        decisions=[f"status={status}"],
    ))
    if debug_mode:
        final_bboxes: list[StageDebugBbox] = []
        for i, e in enumerate(elements):
            style = "primary" if i == primary_index else ("fallback" if e.is_fallback else "candidate")
            final_bboxes.append(StageDebugBbox(
                bbox=list(e.bbox), label=e.text or e.type, style=style, confidence=float(e.confidence),
            ))
        debug_stages.append(_encode_stage_image(
            pre.raw_image, stage="result", bboxes=final_bboxes,
            duration_ms=traces[-1].duration_ms, decisions=list(traces[-1].decisions),
        ))

    total_ms = (time.time() - t0)*1000
    logger.info(
        f"[Pipeline] 总耗时: {total_ms:.1f}ms, "
        f"status={status}, elements={len(elements)}, "
        f"layout+region: {(t3-t1)*1000:.1f}ms, fine={(t5-t4)*1000:.1f}ms"
    )

    result = LocateResult(
        status=status,
        elements=elements,
        primary_index=primary_index,
        error=None if elements else "no element located",
        trace=traces if debug_mode else [],
        fallbacks=fallbacks,
        total_duration_ms=(time.time() - t0) * 1000,
        raw_size=pre.raw_size,
        base_size=pre.base_size,
        layout_type=layout.layout_type,
        cache_hit=cache_hit,
        debug_stages=debug_stages if debug_mode else [],
    )

    logger.info(
        f"locate v2 done: status={status} elements={len(elements)} "
        f"cache={cache_hit or 'miss'} {result.total_duration_ms:.0f}ms"
    )
    return result


# ---- helpers ----

def _encode_stage_image(
    pil_image,
    *,
    stage: str,
    bboxes: list[StageDebugBbox],
    crop_on_raw: list[int] | None = None,
    zoom_scale: float = 1.0,
    duration_ms: float = 0.0,
    model_calls: int = 0,
    decisions: list[str] | None = None,
) -> StageDebugImage:
    """将 PIL 图编码为 data-uri 并组装为阶段可视化产物 (框交由前端叠加)。"""
    from tisui.shared.models.types import UnifiedImage
    buf = BytesIO()
    pil_image.save(buf, format="PNG")
    png_data = buf.getvalue()
    
    img = UnifiedImage.from_bytes(png_data, mime_type="image/png")
    try:
        optimized_img = img.convert_to_format("image/jpeg", quality=85)
        data_url = optimized_img.to_data_url()
    except Exception:
        data_url = f"data:image/png;base64,{base64.b64encode(png_data).decode('utf-8')}"
    
    width, height = pil_image.size
    return StageDebugImage(
        stage=stage,
        image_base64=data_url,
        image_width=int(width),
        image_height=int(height),
        crop_on_raw=list(crop_on_raw) if crop_on_raw is not None else None,
        bboxes=bboxes,
        zoom_scale=float(zoom_scale),
        duration_ms=float(duration_ms),
        model_calls=int(model_calls),
        decisions=list(decisions or []),
    )


def _region_debug_bbox(
    region,
    style: str,
    *,
    base_size: tuple[int, int],
    raw_size: tuple[int, int],
) -> StageDebugBbox:
    """区域 bbox: base 坐标 → raw 坐标 (debug 展示叠在 raw 原图上)。"""
    z_index = int(getattr(region, "z_index", 0) or 0)
    label = region.region_type if z_index <= 0 else f"{region.region_type} (overlay z{z_index})"
    return StageDebugBbox(
        bbox=map_region_base_to_raw(region.bbox, base_size, raw_size),
        label=label,
        style=style,
        confidence=float(region.confidence),
    )


def _build_fine_stage(
    patch: CroppedPatch,
    elems: list[LocatedElement],
    *,
    fallback: bool = False,
) -> StageDebugImage:
    """fine 阶段: 展示 patch 图, 元素框换算为 patch 内坐标。"""
    origin_x, origin_y = patch.bbox_in_raw[0], patch.bbox_in_raw[1]
    style = "fallback" if fallback else "primary"
    bboxes = [
        StageDebugBbox(
            bbox=[
                e.bbox[0] - origin_x, e.bbox[1] - origin_y,
                e.bbox[2] - origin_x, e.bbox[3] - origin_y,
            ],
            label=e.text or e.type,
            style=style,
            confidence=float(e.confidence),
        )
        for e in elems
    ]
    stage_name = f"fine:{patch.source_region_id}" if patch.source_region_id else "fine"
    return _encode_stage_image(
        patch.patch_image,
        stage=stage_name,
        bboxes=bboxes,
        crop_on_raw=list(patch.bbox_in_raw),
        model_calls=1,
    )


def _store(cache: OrderedDict, key, value) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > _CACHE_CAP:
        cache.popitem(last=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clear_caches() -> None:
    """清空内存缓存 (测试用)。"""
    _L2_LAYOUT_CACHE.clear()


__all__ = ["run_pipeline", "clear_caches"]
