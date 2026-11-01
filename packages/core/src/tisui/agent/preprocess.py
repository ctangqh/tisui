from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from tisui.shared.config import load_runtime_config, settings
from tisui.shared.utils import (
    generate_nine_grid_anchors,
    infer_element_position,
    relative_to_absolute_coord,
    resize_image_by_max_side,
)

from .cache import load_preprocess_cache, save_preprocess_cache
from .debug import init_debug, output_debug_data
from .prompt import (
    build_action_locate_prompt,
    build_intention_decomposition_prompt,
    build_preview_vision_prompt,
)


GridAnchor = tuple[list[int], list[int]]
BBox = list[int]
RelativeBBox = list[float]


@dataclass
class ImageData:
    image: bytes
    width: int
    height: int
    compression_ratio: float


@dataclass
class RegionInfo:
    id: str
    name: str
    description: str
    z_index: int = 1
    relative_bbox: RelativeBBox = field(default_factory=list)
    bbox: BBox = field(default_factory=list)
    bbox_resized: BBox = field(default_factory=list)
    page_grid_position: str | None = None
    anchors: list[GridAnchor] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreprocessContext:
    image_hash: str
    image_width: int
    image_height: int
    resized_width: int
    resized_height: int
    resize_max_side: int
    image_data_url: str
    image_resized_data_url: str
    page_anchors: list[GridAnchor] = field(default_factory=list)
    regions: list[RegionInfo] = field(default_factory=list)
    raw_regions_payload: dict[str, Any] = field(default_factory=dict)
    source_file_name: str | None = None
    raw_image_data: ImageData | None = None
    resize_image_data: ImageData | None = None
    infer_image_data: ImageData | None = None
    config_data: dict[str, Any] = field(default_factory=dict)
    matrix_data: dict[str, Any] = field(default_factory=dict)
    context_data: dict[str, Any] = field(default_factory=dict)

    def get_raw_image(self) -> bytes:
        return self.raw_image_data.image if self.raw_image_data else b""

    def get_resize_image(self) -> bytes:
        return self.resize_image_data.image if self.resize_image_data else b""

    def get_infer_image(self) -> bytes:
        return self.infer_image_data.image if self.infer_image_data else b""

    def get_run_config(self) -> dict[str, Any]:
        return dict(self.config_data)

    def get_nine_matrix(self) -> dict[str, Any]:
        return dict(self.matrix_data.get("nine_matrix") or {})

    def get_nice_matrix(self) -> dict[str, Any]:
        return self.get_nine_matrix()

    def get_refer_line_matrix(self) -> dict[str, Any]:
        return dict(self.matrix_data.get("refer_line_matrix") or {})

    def get_action_context(self) -> dict[str, Any]:
        return dict(self.context_data)


@dataclass
class TargetCandidate:
    region_id: str | None = None
    region_name: str | None = None
    grid_position: str | None = None
    confidence: float | None = None
    reason: str | None = None


@dataclass
class TargetLocateHint:
    action_text: str
    target_region_id: str | None = None
    target_region_name: str | None = None
    target_grid_position: str | None = None
    target_grid_index: int | None = None
    target_grid_bbox: BBox | None = None
    intersect_bbox: BBox | None = None
    confidence: float | None = None
    reasoning: str | None = None
    candidates: list[TargetCandidate] = field(default_factory=list)
    raw_llm_result: dict[str, Any] = field(default_factory=dict)
    normalized_summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreprocessResult:
    preprocess: PreprocessContext
    target_hint: TargetLocateHint | None = None


def preprocess_image(
    image_bytes: bytes,
    *,
    action_text: str | None = None,
    resize_max_side: int = 500,
    debug: bool | None = None,
    debug_output_path: str | Path | None = None,
    **legacy_kwargs: object,
) -> PreprocessContext:
    """
    预处理图片，生成后续操作定位所需的上下文数据。

    目标流程：
    1. 对原始图片计算 hash。
    2. 等比缩放图片到最长边不超过 `resize_max_side`。
    3. 调用预览区域 prompt 识别大致可操作区域。
    4. 对整张图生成 9 宫格锚点。
    5. 对每个区域生成区域内 9 宫格锚点，并补充原图/缩放图绝对 `bbox`。

    说明：
    - 当前函数负责定义预处理流程，不在这里展开更细的业务规则。
    - 缓存逻辑统一放在 `agent/cache.py` 中，这里只负责读写调用。
    """
    debug_enabled = _is_debug_enabled(debug)
    legacy_kwargs.pop("file_name", None)
    image_hash = _sha256_hex(image_bytes)
    cached = load_preprocess_cache(image_hash)
    if isinstance(cached, dict):
        ctx = _preprocess_context_from_payload(cached)
        _hydrate_step1_context(
            ctx,
            image_bytes=image_bytes,
            action_text=action_text,
            debug_enabled=debug_enabled,
            output_dir=debug_output_path,
        )
        _output_step1_debug(
            ctx,
            debug=debug_enabled,
            debug_output_path=debug_output_path,
        )
        if debug_enabled:
            debug_info_output(
                "regions_identify",
                preprocess_ctx=ctx,
                output_path=debug_output_path,
            )
        return ctx

    (
        original_data_url,
        resized_data_url,
        original_image_bytes,
        resized_image_bytes,
        width,
        height,
        resized_width,
        resized_height,
    ) = _build_image_data_urls(
        image_bytes,
        resize_max_side=resize_max_side,
    )
    raw_payload = _call_preview_regions_llm(resized_data_url)
    regions = _normalize_regions_payload(
        raw_payload,
        width=width,
        height=height,
        resized_width=resized_width,
        resized_height=resized_height,
    )

    ctx = PreprocessContext(
        source_file_name=None,
        image_hash=image_hash,
        image_width=width,
        image_height=height,
        resized_width=resized_width,
        resized_height=resized_height,
        resize_max_side=resize_max_side,
        image_data_url=original_data_url,
        image_resized_data_url=resized_data_url,
        page_anchors=generate_nine_grid_anchors(width, height),
        regions=regions,
        raw_regions_payload=raw_payload,
    )
    _hydrate_step1_context(
        ctx,
        image_bytes=image_bytes,
        action_text=action_text,
        debug_enabled=debug_enabled,
        output_dir=debug_output_path,
        original_image_bytes=original_image_bytes,
        resized_image_bytes=resized_image_bytes,
    )
    _output_step1_debug(
        ctx,
        debug=debug_enabled,
        debug_output_path=debug_output_path,
    )
    save_preprocess_cache(image_hash, _preprocess_context_to_payload(ctx))
    if debug_enabled:
        debug_info_output(
            "regions_identify",
            preprocess_ctx=ctx,
            output_path=debug_output_path,
        )
    return ctx


def infer_operation_target(
    preprocess_ctx: PreprocessContext,
    action_text: str,
    *,
    debug: bool | None = None,
    debug_output_path: str | Path | None = None,
) -> TargetLocateHint:
    """
    根据操作语言，推断目标控件大致位于哪个区域、哪个 9 宫格位置。

    目标流程：
    1. 读取 `preprocess_ctx` 中的区域列表和整图区域 9 宫格锚点。
    2. 调用 LLM，结合以下信息对 `action_text` 做粗定位：
       - 可操作区域名称与描述
       - 区域 z-index
       - 区域 bbox
       - 区域在整图中的 9 宫格位置
       - 区域内部 9 宫格
    3. 得到目标区域和目标 9 宫格位置。
    4. 取目标 9 宫格 bbox 与目标区域 bbox 做交集。
    5. 返回 `TargetLocateHint`。

    当前默认策略：
    - 优先调用文本 LLM 完成“区域 + 九宫格”的粗定位。
    - 如果 LLM 返回异常或无法解析，则回退到基于关键词的规则兜底。
    """
    debug_enabled = _is_debug_enabled(debug)
    normalized_action = (action_text or "").strip()
    if not normalized_action:
        target_hint = TargetLocateHint(
            action_text="",
            normalized_summary={
                "source_format": "empty_action",
                "fallback_used": False,
                "selected_region_id": None,
                "selected_region_name": None,
                "selected_grid_position": None,
                "selected_grid_indices": [],
                "selected_confidence": None,
                "selected_reason": "",
                "selected_relative_bbox": None,
                "selected_bbox": None,
                "candidate_count": 0,
                "candidate_regions": [],
            },
        )
        if debug_enabled:
            debug_info_output(
                "action_regions",
                preprocess_ctx=preprocess_ctx,
                target_hint=target_hint,
                output_path=debug_output_path,
            )
            debug_info_output(
                "action_target",
                preprocess_ctx=preprocess_ctx,
                target_hint=target_hint,
                output_path=debug_output_path,
            )
        return target_hint

    if not preprocess_ctx.regions:
        target_hint = TargetLocateHint(
            action_text=normalized_action,
            reasoning="预处理结果中没有可用区域，无法推断目标位置。",
            normalized_summary={
                "source_format": "empty_regions",
                "fallback_used": False,
                "selected_region_id": None,
                "selected_region_name": None,
                "selected_grid_position": None,
                "selected_grid_indices": [],
                "selected_confidence": None,
                "selected_reason": "预处理结果中没有可用区域，无法推断目标位置。",
                "selected_relative_bbox": None,
                "selected_bbox": None,
                "candidate_count": 0,
                "candidate_regions": [],
            },
        )
        if debug_enabled:
            debug_info_output(
                "action_regions",
                preprocess_ctx=preprocess_ctx,
                target_hint=target_hint,
                output_path=debug_output_path,
            )
            debug_info_output(
                "action_target",
                preprocess_ctx=preprocess_ctx,
                target_hint=target_hint,
                output_path=debug_output_path,
            )
        return target_hint

    prompt = _build_action_locate_prompt(normalized_action, preprocess_ctx)
    llm_result = _call_action_locate_llm(prompt)
    llm_result = _normalize_action_locate_result(llm_result, preprocess_ctx)
    if not llm_result:
        llm_result = _build_action_locate_fallback(normalized_action, preprocess_ctx)
    elif not llm_result.get("target_region_id") and not llm_result.get("target_region_name"):
        llm_result = _build_action_locate_fallback(normalized_action, preprocess_ctx, raw_llm_result=llm_result)

    target_hint = _resolve_target_bbox(
        preprocess_ctx,
        llm_result,
        action_text=normalized_action,
    )
    if debug_enabled:
        debug_info_output(
            "action_regions",
            preprocess_ctx=preprocess_ctx,
            target_hint=target_hint,
            output_path=debug_output_path,
        )
        debug_info_output(
            "action_target",
            preprocess_ctx=preprocess_ctx,
            target_hint=target_hint,
            output_path=debug_output_path,
        )
    return target_hint


def preprocess_for_action(
    image_bytes: bytes,
    action_text: str | None = None,
    *,
    resize_max_side: int = 500,
    debug: bool | None = None,
    debug_output_path: str | Path | None = None,
    **legacy_kwargs: object,
) -> PreprocessResult:
    """
    对外统一入口。

    推荐调用流程：
    - 只有图片：只返回 `PreprocessContext`
    - 图片 + 操作语言：同时返回 `TargetLocateHint`
    """
    preprocess_ctx = preprocess_image(
        image_bytes,
        action_text=action_text,
        resize_max_side=resize_max_side,
        debug=debug,
        debug_output_path=debug_output_path,
        **legacy_kwargs,
    )
    if not action_text or not action_text.strip():
        return PreprocessResult(preprocess=preprocess_ctx)

    target_hint = infer_operation_target(
        preprocess_ctx,
        action_text.strip(),
        debug=debug,
        debug_output_path=debug_output_path,
    )
    return PreprocessResult(preprocess=preprocess_ctx, target_hint=target_hint)


def _is_debug_enabled(debug: bool | None) -> bool:
    if debug is not None:
        return debug
    return settings.debug


def _sha256_hex(image_bytes: bytes) -> str:
    """
    内部方法：根据原始图片字节计算 hash。
    """
    return hashlib.sha256(image_bytes).hexdigest()


def _hydrate_step1_context(
    preprocess_ctx: PreprocessContext,
    *,
    image_bytes: bytes,
    action_text: str | None,
    debug_enabled: bool | None = None,
    output_dir: str | Path | None = None,
    original_image_bytes: bytes | None = None,
    resized_image_bytes: bytes | None = None,
) -> None:
    config_data = _build_run_config()
    config_data["resize_max_side"] = preprocess_ctx.resize_max_side
    if debug_enabled is not None:
        config_data["debug"] = debug_enabled
    if output_dir is not None:
        config_data["output_dir"] = str(output_dir)
    raw_image_data, resize_image_data, infer_image_data = _build_step1_image_data(
        image_bytes=image_bytes,
        resize_max_side=preprocess_ctx.resize_max_side,
        original_image_bytes=original_image_bytes,
        resized_image_bytes=resized_image_bytes,
    )
    matrix_data = _build_step1_matrix_data(
        width=preprocess_ctx.image_width,
        height=preprocess_ctx.image_height,
        target_cell_size=int(config_data.get("target_cell_size") or 160),
        half_cell=int(config_data.get("half_cell") or 80),
    )
    context_data = _build_action_context(
        action_text=action_text,
        preprocess_ctx=preprocess_ctx,
        raw_image_data=raw_image_data,
        resize_image_data=resize_image_data,
        config_data=config_data,
        matrix_data=matrix_data,
    )

    preprocess_ctx.raw_image_data = raw_image_data
    preprocess_ctx.resize_image_data = resize_image_data
    preprocess_ctx.infer_image_data = infer_image_data
    preprocess_ctx.config_data = config_data
    preprocess_ctx.matrix_data = matrix_data
    preprocess_ctx.context_data = context_data


def _build_step1_image_data(
    *,
    image_bytes: bytes,
    resize_max_side: int,
    original_image_bytes: bytes | None = None,
    resized_image_bytes: bytes | None = None,
) -> tuple[ImageData, ImageData, ImageData]:
    raw_image_bytes = image_bytes
    with Image.open(BytesIO(image_bytes)) as pil_image:
        rgb = pil_image.convert("RGB")
        raw_width, raw_height = rgb.size
        resized_image = resize_image_by_max_side(rgb, max_side=resize_max_side)
        resize_width, resize_height = resized_image.size
        if resized_image_bytes is None:
            resize_buffer = BytesIO()
            resized_image.save(resize_buffer, format="JPEG", quality=90)
            resized_image_bytes = resize_buffer.getvalue()

    resize_ratio = round(resize_width / max(1, raw_width), 6)
    raw_image_data = ImageData(
        image=raw_image_bytes,
        width=raw_width,
        height=raw_height,
        compression_ratio=1.0,
    )
    resize_image_data = ImageData(
        image=resized_image_bytes or b"",
        width=resize_width,
        height=resize_height,
        compression_ratio=resize_ratio,
    )
    infer_image_data = ImageData(
        image=resize_image_data.image,
        width=resize_image_data.width,
        height=resize_image_data.height,
        compression_ratio=resize_image_data.compression_ratio,
    )
    return raw_image_data, resize_image_data, infer_image_data


def _build_run_config() -> dict[str, Any]:
    runtime_config = load_runtime_config()
    platform = str(runtime_config.get("platform") or "pc").strip().lower()
    if platform not in {"pc", "mobile"}:
        platform = "pc"
    target_cell_size = 80 if platform == "pc" else 120
    return {
        "platform": platform,
        "debug": settings.debug,
        "prompt_locale": str(runtime_config.get("prompt_locale") or "zh-CN").strip() or "zh-CN",
        "log_level": settings.logging_config.level,
        "output_dir": None,
        "resize_max_side": None,
        "target_cell_size": target_cell_size,
        "half_cell": target_cell_size // 2,
    }


def _output_step1_debug(
    preprocess_ctx: PreprocessContext,
    *,
    debug: bool,
    debug_output_path: str | Path | None = None,
) -> None:
    debug_config = init_debug()
    if debug:
        debug_config["debug"] = True
    if debug_output_path is not None:
        provided = Path(debug_output_path)
        debug_config["debug_output_dir"] = str(provided.parent if provided.suffix.lower() == ".json" else provided)
    output_debug_data(preprocess_ctx.get_action_context(), debug_config)


def _build_step1_matrix_data(
    *,
    width: int,
    height: int,
    target_cell_size: int,
    half_cell: int,
) -> dict[str, Any]:
    nine_absolute_matrix = _reshape_anchor_grid(generate_nine_grid_anchors(width, height), rows=3, cols=3)
    refer_absolute_matrix = _build_refer_line_matrix(
        width=width,
        height=height,
        target_cell_size=target_cell_size,
        half_cell=half_cell,
    )
    return {
        "nine_matrix": {
            "absolute_matrix": nine_absolute_matrix,
            "relative_matrix": _build_relative_anchor_matrix(nine_absolute_matrix, width=width, height=height),
        },
        "refer_line_matrix": {
            "absolute_matrix": refer_absolute_matrix,
            "relative_matrix": _build_relative_anchor_matrix(refer_absolute_matrix, width=width, height=height),
        },
    }


def _build_action_context(
    *,
    action_text: str | None,
    preprocess_ctx: PreprocessContext | None = None,
    raw_image_data: ImageData,
    resize_image_data: ImageData,
    config_data: dict[str, Any],
    matrix_data: dict[str, Any],
) -> dict[str, Any]:
    normalized_action_text = _normalize_action_text(action_text)
    nine_absolute = matrix_data.get("nine_matrix", {}).get("absolute_matrix") or []
    refer_absolute = matrix_data.get("refer_line_matrix", {}).get("absolute_matrix") or []
    preview_usage = _extract_usage_summary(preprocess_ctx.raw_regions_payload if preprocess_ctx else None)
    return {
        "action": action_text or "",
        "meta": {
            "cache_image_hash": preprocess_ctx.image_hash if preprocess_ctx else "",
            "image_raw_width": raw_image_data.width,
            "image_raw_height": raw_image_data.height,
            "image_raw_compression_ratio": raw_image_data.compression_ratio,
            "image_resize_width": resize_image_data.width,
            "image_resize_height": resize_image_data.height,
            "image_resize_compression_ratio": resize_image_data.compression_ratio,
            "config_platform": config_data.get("platform"),
            "config_debug": config_data.get("debug"),
            "config_prompt_locale": config_data.get("prompt_locale"),
            "config_log_level": config_data.get("log_level"),
            "config_output_dir": config_data.get("output_dir"),
            "config_resize_max_side": config_data.get("resize_max_side"),
            "config_target_cell_size": config_data.get("target_cell_size"),
            "config_half_cell": config_data.get("half_cell"),
            "matrix_nine_rows": len(nine_absolute),
            "matrix_nine_cols": len(nine_absolute[0]) if nine_absolute else 0,
            "matrix_refer_line_rows": len(refer_absolute),
            "matrix_refer_line_cols": len(refer_absolute[0]) if refer_absolute else 0,
            "matrix_refer_line_merge_remainder_rule": "lt_half_merge_prev",
            "token_preview_prompt_tokens": preview_usage.get("prompt_tokens"),
            "token_preview_completion_tokens": preview_usage.get("completion_tokens"),
            "token_preview_total_tokens": preview_usage.get("total_tokens"),
        },
        "steps": [
            {
                "name": "normalize_action_text",
                "description": "对输入动作语言进行预处理和标准化",
                "input": {
                    "context_action_raw_text": action_text or "",
                },
                "output": {
                    "context_action_normalized_text": normalized_action_text,
                    "context_action_is_empty": normalized_action_text == "",
                },
            },
            {
                "name": "prepare_resize_image",
                "description": "对原始图片按最大边进行压缩",
                "input": {
                    "image_raw_width": raw_image_data.width,
                    "image_raw_height": raw_image_data.height,
                    "config_resize_max_side": config_data.get("resize_max_side"),
                },
                "output": {
                    "image_resize_width": resize_image_data.width,
                    "image_resize_height": resize_image_data.height,
                    "image_resize_compression_ratio": resize_image_data.compression_ratio,
                },
            },
            {
                "name": "build_nine_matrix",
                "description": "生成整图 3x3 九宫格锚点矩阵",
                "input": {
                    "image_raw_width": raw_image_data.width,
                    "image_raw_height": raw_image_data.height,
                },
                "output": {
                    "matrix_nine_rows": len(nine_absolute),
                    "matrix_nine_cols": len(nine_absolute[0]) if nine_absolute else 0,
                },
            },
            {
                "name": "build_refer_line_matrix",
                "description": "基于原图坐标系生成基础细网格矩阵",
                "input": {
                    "image_raw_width": raw_image_data.width,
                    "image_raw_height": raw_image_data.height,
                    "config_platform": config_data.get("platform"),
                    "config_target_cell_size": config_data.get("target_cell_size"),
                    "config_half_cell": config_data.get("half_cell"),
                },
                "output": {
                    "matrix_refer_line_rows": len(refer_absolute),
                    "matrix_refer_line_cols": len(refer_absolute[0]) if refer_absolute else 0,
                    "matrix_refer_line_merge_remainder_rule": "lt_half_merge_prev",
                },
            },
        ],
    }


def _normalize_action_text(action_text: str | None) -> str:
    return str(action_text or "").strip()


def _extract_usage_summary(payload: dict[str, Any] | None) -> dict[str, int | None]:
    usage = {}
    if isinstance(payload, dict):
        candidate = payload.get("usage")
        if isinstance(candidate, dict):
            usage = candidate
    return {
        "prompt_tokens": _normalize_int(usage.get("prompt_tokens")),
        "completion_tokens": _normalize_int(usage.get("completion_tokens")),
        "total_tokens": _normalize_int(usage.get("total_tokens")),
    }


def _normalize_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _reshape_anchor_grid(
    anchors: list[GridAnchor],
    *,
    rows: int,
    cols: int,
) -> list[list[GridAnchor]]:
    matrix: list[list[GridAnchor]] = []
    for row in range(rows):
        start = row * cols
        matrix.append(anchors[start : start + cols])
    return matrix


def _build_relative_anchor_matrix(
    absolute_matrix: list[list[GridAnchor]],
    *,
    width: int,
    height: int,
) -> list[list[tuple[list[float], list[float]]]]:
    relative_matrix: list[list[tuple[list[float], list[float]]]] = []
    for row in absolute_matrix:
        relative_row: list[tuple[list[float], list[float]]] = []
        for anchor in row:
            left_top, right_bottom = anchor
            relative_row.append(
                (
                    [round(left_top[0] / max(1, width), 6), round(left_top[1] / max(1, height), 6)],
                    [round(right_bottom[0] / max(1, width), 6), round(right_bottom[1] / max(1, height), 6)],
                )
            )
        relative_matrix.append(relative_row)
    return relative_matrix


def _build_refer_line_matrix(
    *,
    width: int,
    height: int,
    target_cell_size: int,
    half_cell: int,
) -> list[list[GridAnchor]]:
    x_ranges = _build_axis_ranges(length=width, target_cell_size=target_cell_size, half_cell=half_cell)
    y_ranges = _build_axis_ranges(length=height, target_cell_size=target_cell_size, half_cell=half_cell)
    matrix: list[list[GridAnchor]] = []
    for top, bottom in y_ranges:
        row: list[GridAnchor] = []
        for left, right in x_ranges:
            row.append(([left, top], [right, bottom]))
        matrix.append(row)
    return matrix


def _build_axis_ranges(
    *,
    length: int,
    target_cell_size: int,
    half_cell: int,
) -> list[tuple[int, int]]:
    if length <= 0:
        raise ValueError("length 必须大于 0")
    if target_cell_size <= 0:
        raise ValueError("target_cell_size 必须大于 0")
    if half_cell <= 0:
        raise ValueError("half_cell 必须大于 0")

    base_count = length // target_cell_size
    remainder = length % target_cell_size
    count = max(1, base_count + (1 if remainder >= half_cell else 0))

    ranges: list[tuple[int, int]] = []
    start = 0
    for index in range(count):
        if index == count - 1:
            end = length
        else:
            end = min(length, start + target_cell_size)
        ranges.append((start, end))
        start = end
    return ranges


def _build_image_data_urls(
    image_bytes: bytes,
    *,
    resize_max_side: int,
) -> tuple[str, str, bytes, bytes, int, int, int, int]:
    """
    内部方法：构建原图与缩放图的 data url，并返回对应宽高。

    返回顺序为：
    - original_data_url
    - resized_data_url
    - original_image_bytes
    - resized_image_bytes
    - image_width
    - image_height
    - resized_width
    - resized_height
    """
    with Image.open(BytesIO(image_bytes)) as pil_image:
        rgb = pil_image.convert("RGB")
        width, height = rgb.size
        resized_image = resize_image_by_max_side(rgb, max_side=resize_max_side)
        resized_width, resized_height = resized_image.size

        original_buffer = BytesIO()
        rgb.save(original_buffer, format="JPEG", quality=90)
        original_data_url = "data:image/jpeg;base64," + base64.b64encode(original_buffer.getvalue()).decode("utf-8")

        resized_buffer = BytesIO()
        resized_image.save(resized_buffer, format="JPEG", quality=90)
        resized_data_url = "data:image/jpeg;base64," + base64.b64encode(resized_buffer.getvalue()).decode("utf-8")

    return (
        original_data_url,
        resized_data_url,
        original_buffer.getvalue(),
        resized_buffer.getvalue(),
        width,
        height,
        resized_width,
        resized_height,
    )


def _call_preview_regions_llm(image_data_url: str) -> dict[str, Any]:
    """
    内部方法：调用区域预览识别 prompt，返回区域识别结果。
    """
    from tisui.shared.models.invoker import invoke_vision_llm

    config = settings.vision_config
    if not (config.api_key and config.base_url and config.model):
        return {
            "regions": [],
            "errors": [{"message": "vision config is not set"}],
        }

    try:
        result = invoke_vision_llm(
            image_data_url=image_data_url,
            content=build_preview_vision_prompt(),
        )
    except Exception as e:
        return {
            "regions": [],
            "errors": [{"message": str(e)}],
        }

    raw_response = str(result.get("content") or "")
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    parsed = _parse_json_text(raw_response)
    if isinstance(parsed, dict):
        parsed.setdefault("usage", usage)
        return parsed
    return {
        "regions": [],
        "usage": usage,
        "errors": [{"message": "model response is not json object", "raw_response": raw_response}],
    }


def _normalize_regions_payload(
    parsed: dict[str, Any],
    *,
    width: int,
    height: int,
    resized_width: int,
    resized_height: int,
) -> list[RegionInfo]:
    """
    内部方法：把 LLM 返回的 `regions` 归一化为 `RegionInfo` 列表。

    需要补充的数据包括：
    - `relative_bbox`
    - `bbox`
    - `bbox_resized`
    - `page_grid_position`
    - `anchors`
    """
    raw_regions = parsed.get("regions")
    normalized_regions: list[RegionInfo] = []

    for index, item in enumerate(raw_regions if isinstance(raw_regions, list) else []):
        if not isinstance(item, dict):
            continue
        relative_bbox = _normalize_relative_bbox(item.get("relative_bbox"))
        if relative_bbox is None:
            continue

        bbox = relative_to_absolute_coord(width, height, relative_bbox, [0, 0])
        bbox_resized = relative_to_absolute_coord(resized_width, resized_height, relative_bbox, [0, 0])
        page_grid_position = infer_element_position(
            width,
            height,
            ([bbox[0], bbox[1]], [bbox[2], bbox[3]]),
        )

        normalized_regions.append(
            RegionInfo(
                id=str(item.get("id") or f"region-{index + 1}"),
                name=str(item.get("name") or f"region-{index + 1}"),
                description=str(item.get("description") or ""),
                z_index=_normalize_z_index(item.get("z-index")),
                relative_bbox=relative_bbox,
                bbox=bbox,
                bbox_resized=bbox_resized,
                page_grid_position=page_grid_position,
                anchors=_build_region_anchors(bbox),
                raw=dict(item),
            )
        )

    return normalized_regions


def _build_region_anchors(region_bbox: BBox) -> list[GridAnchor]:
    """
    内部方法：根据区域 bbox 构建区域内部 9 宫格锚点。

    建议流程：
    - 先基于区域宽高生成 9 宫格
    - 再平移到页面绝对坐标系
    """
    if len(region_bbox) != 4:
        raise ValueError("region_bbox 必须是 [left, top, right, bottom]")

    left, top, right, bottom = region_bbox
    region_width = max(1, int(right) - int(left))
    region_height = max(1, int(bottom) - int(top))
    anchors = generate_nine_grid_anchors(region_width, region_height)

    absolute_anchors: list[GridAnchor] = []
    for left_top, right_bottom in anchors:
        absolute_anchors.append(
            (
                [left + left_top[0], top + left_top[1]],
                [left + right_bottom[0], top + right_bottom[1]],
            )
        )
    return absolute_anchors


def _build_action_locate_prompt(
    action_text: str,
    preprocess_ctx: PreprocessContext,
) -> str:
    """
    内部方法：构造“操作语言 -> 区域 + 9 宫格”的定位 prompt。
    """
    page_grid_lines: list[str] = []
    for index, anchor in enumerate(preprocess_ctx.page_anchors):
        page_grid_lines.append(
            f"{index + 1}({_grid_index_to_label(index)})="
            f"{{relative_bbox={_bbox_to_relative_bbox(_anchor_to_bbox(anchor), preprocess_ctx.image_width, preprocess_ctx.image_height)}, "
            f"bbox={_anchor_to_bbox(anchor)}}}"
        )

    region_blocks: list[str] = [
        "# 页面九宫格",
        "; ".join(page_grid_lines),
        "",
        "# 识别区域",
    ]
    for region in sorted(preprocess_ctx.regions, key=lambda item: (item.z_index, item.name)):
        grid_labels = []
        for index, anchor in enumerate(region.anchors):
            grid_bbox = _anchor_to_bbox(anchor)
            grid_labels.append(
                f"{index + 1}({_grid_index_to_label(index)})="
                f"{{relative_bbox={_bbox_to_relative_bbox(grid_bbox, preprocess_ctx.image_width, preprocess_ctx.image_height)}, "
                f"bbox={grid_bbox}}}"
            )

        region_blocks.append(
            "\n".join(
                [
                    f"- region_id: {region.id}",
                    f"  name: {region.name}",
                    f"  description: {region.description or '-'}",
                    f"  z_index: {region.z_index}",
                    f"  page_grid_position: {region.page_grid_position or '-'}",
                    f"  relative_bbox: {region.relative_bbox}",
                    f"  bbox: {region.bbox}",
                    f"  bbox_resized: {region.bbox_resized}",
                    f"  inner_grids: {'; '.join(grid_labels)}",
                ]
            )
        )
    return build_action_locate_prompt(action_text, "\n".join(region_blocks))


def _call_action_locate_llm(prompt: str) -> dict[str, Any]:
    """
    内部方法：调用 LLM 推断操作语言对应的目标区域与 9 宫格位置。
    """
    from tisui.shared.models.invoker import invoke_text_llm

    config = settings.llm_config
    if not (config.api_key and config.base_url and config.model):
        return {}

    try:
        result = invoke_text_llm(content=prompt)
    except Exception:
        return {}

    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    parsed = _parse_json_text(str(result.get("content") or ""))
    if isinstance(parsed, dict):
        parsed.setdefault("usage", usage)
        return parsed
    if usage:
        return {"usage": usage}
    return {}


def intention_decomposition(action_text: str) -> list[dict[str, Any]]:
    """
    对操作语言做语义拆解，返回按顺序排列的原子操作步骤。
    标记：已人工确认
    """
    from tisui.shared.models.invoker import invoke_text_llm

    normalized_action = action_text.strip()
    if not normalized_action:
        return []

    config = settings.llm_config
    if not (config.api_key and config.base_url and config.model):
        return []

    prompt = build_intention_decomposition_prompt(
        params=[{"text": normalized_action}],
    )
    try:
        result = invoke_text_llm(content=prompt)
    except Exception:
        return []

    parsed = _parse_json_value(str(result.get("content") or ""))
    if not isinstance(parsed, list):
        return []

    steps: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        action = str(item.get("action") or "").strip()
        if not action:
            continue
        steps.append(
            {
                "name": name or f"step{len(steps) + 1}",
                "action": action,
            }
        )
    return steps


def _resolve_target_bbox(
    preprocess_ctx: PreprocessContext,
    llm_result: dict[str, Any],
    *,
    action_text: str,
) -> TargetLocateHint:
    """
    内部方法：把 LLM 的区域/格子定位结果转换成 `TargetLocateHint`。

    关键步骤：
    - 找到目标区域
    - 把格子标签映射到区域锚点索引
    - 计算区域 bbox 与目标格子 bbox 的交集
    """
    region = _find_region(
        preprocess_ctx.regions,
        region_id=llm_result.get("target_region_id"),
        region_name=llm_result.get("target_region_name"),
    )
    if region is None:
        candidates = _parse_target_candidates(llm_result.get("candidates"), preprocess_ctx.regions)
        return TargetLocateHint(
            action_text=action_text,
            reasoning=str(llm_result.get("reasoning") or "未能匹配到目标区域。"),
            confidence=_normalize_confidence(llm_result.get("confidence")),
            candidates=candidates,
            raw_llm_result=llm_result,
            normalized_summary=_build_action_locate_summary(
                llm_result,
                candidates=candidates,
                target_bbox=_normalize_bbox(llm_result.get("target_bbox")),
            ),
        )

    target_grid_indices = _normalize_target_grid_indices(llm_result.get("target_grid_indices"))
    grid_position = _normalize_grid_position_label(llm_result.get("target_grid_position"))
    if not grid_position:
        grid_position = _infer_grid_position_from_indices(target_grid_indices)

    grid_index = _grid_position_to_index(grid_position or "")
    if not target_grid_indices and grid_index is not None:
        target_grid_indices = [grid_index]

    if not target_grid_indices and (grid_index is None or grid_index >= len(region.anchors)):
        fallback_grid_position = _infer_grid_from_action_text(action_text)
        grid_index = _grid_position_to_index(fallback_grid_position or "")
        grid_position = fallback_grid_position
        if grid_index is not None:
            target_grid_indices = [grid_index]
    elif len(target_grid_indices) == 1:
        grid_index = target_grid_indices[0]

    target_grid_bbox: BBox | None = None
    intersect_bbox: BBox | None = None
    if target_grid_indices:
        target_grid_bbox = _merge_region_grid_bboxes(region, target_grid_indices)
    elif grid_index is not None and 0 <= grid_index < len(region.anchors):
        target_grid_bbox = _anchor_to_bbox(region.anchors[grid_index])

    target_bbox = _normalize_bbox(llm_result.get("target_bbox"))
    if target_bbox is not None:
        intersect_bbox = _intersect_bbox(region.bbox, target_bbox) or target_bbox
    elif target_grid_bbox is not None:
        intersect_bbox = _intersect_bbox(region.bbox, target_grid_bbox)

    candidates = _parse_target_candidates(llm_result.get("candidates"), preprocess_ctx.regions)
    target_hint = TargetLocateHint(
        action_text=action_text,
        target_region_id=region.id,
        target_region_name=region.name,
        target_grid_position=grid_position,
        target_grid_index=grid_index,
        target_grid_bbox=target_grid_bbox,
        intersect_bbox=intersect_bbox or region.bbox,
        confidence=_normalize_confidence(llm_result.get("confidence")),
        reasoning=str(llm_result.get("reasoning") or ""),
        candidates=candidates,
        raw_llm_result=llm_result,
    )
    target_hint.normalized_summary = _build_action_locate_summary(
        llm_result,
        region=region,
        candidates=candidates,
        target_bbox=target_hint.target_grid_bbox,
        intersect_bbox=target_hint.intersect_bbox,
    )
    return target_hint


def _intersect_bbox(a: BBox, b: BBox) -> BBox | None:
    """
    内部方法：求两个 bbox 的交集。
    """
    left = max(a[0], b[0])
    top = max(a[1], b[1])
    right = min(a[2], b[2])
    bottom = min(a[3], b[3])
    if right <= left or bottom <= top:
        return None
    return [left, top, right, bottom]


def _merge_bboxes(bboxes: list[BBox]) -> BBox | None:
    if not bboxes:
        return None

    left = min(bbox[0] for bbox in bboxes)
    top = min(bbox[1] for bbox in bboxes)
    right = max(bbox[2] for bbox in bboxes)
    bottom = max(bbox[3] for bbox in bboxes)
    return [left, top, right, bottom]


def _grid_position_to_index(label: str) -> int | None:
    """
    内部方法：把九宫格标签映射到索引。

    推荐顺序：
    0 左上, 1 上中, 2 右上,
    3 左中, 4 中,   5 右中,
    6 左下, 7 下中, 8 右下
    """
    mapping = {
        "左上": 0,
        "上中": 1,
        "右上": 2,
        "左中": 3,
        "中": 4,
        "右中": 5,
        "左下": 6,
        "下中": 7,
        "右下": 8,
    }
    return mapping.get(label.strip())


def _grid_index_to_label(index: int) -> str:
    mapping = {
        0: "左上",
        1: "上中",
        2: "右上",
        3: "左中",
        4: "中",
        5: "右中",
        6: "左下",
        7: "下中",
        8: "右下",
    }
    return mapping[index]


def _anchor_to_bbox(anchor: GridAnchor) -> BBox:
    return [anchor[0][0], anchor[0][1], anchor[1][0], anchor[1][1]]


def _find_region(
    regions: list[RegionInfo],
    *,
    region_id: Any,
    region_name: Any,
) -> RegionInfo | None:
    normalized_region_id = str(region_id or "").strip().lower()
    normalized_region_name = str(region_name or "").strip().lower()

    if normalized_region_id:
        for region in regions:
            if region.id.strip().lower() == normalized_region_id:
                return region

    if normalized_region_name:
        for region in regions:
            if region.name.strip().lower() == normalized_region_name:
                return region
        for region in regions:
            if normalized_region_name in region.name.strip().lower():
                return region

    return None


def _normalize_grid_position_label(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None

    mapping = {
        "左上": "左上",
        "上左": "左上",
        "左上角": "左上",
        "top-left": "左上",
        "上中": "上中",
        "顶部中间": "上中",
        "顶部居中": "上中",
        "上方中间": "上中",
        "top-center": "上中",
        "右上": "右上",
        "上右": "右上",
        "右上角": "右上",
        "top-right": "右上",
        "左中": "左中",
        "中左": "左中",
        "左边": "左中",
        "左侧": "左中",
        "left-center": "左中",
        "中": "中",
        "居中": "中",
        "中心": "中",
        "中间": "中",
        "中央": "中",
        "center": "中",
        "右中": "右中",
        "中右": "右中",
        "右边": "右中",
        "右侧": "右中",
        "right-center": "右中",
        "左下": "左下",
        "下左": "左下",
        "左下角": "左下",
        "bottom-left": "左下",
        "下中": "下中",
        "底部中间": "下中",
        "底部居中": "下中",
        "bottom-center": "下中",
        "右下": "右下",
        "下右": "右下",
        "右下角": "右下",
        "bottom-right": "右下",
    }
    normalized = mapping.get(text)
    if normalized:
        return normalized

    for key, label in mapping.items():
        if key in text:
            return label
    return None


def _normalize_confidence(value: Any) -> float | None:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if confidence < 0:
        return 0.0
    if confidence > 1:
        return 1.0
    return round(confidence, 4)


def _normalize_bbox(value: Any) -> BBox | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        left = int(round(float(value[0])))
        top = int(round(float(value[1])))
        right = int(round(float(value[2])))
        bottom = int(round(float(value[3])))
    except (TypeError, ValueError):
        return None
    if right <= left or bottom <= top:
        return None
    return [left, top, right, bottom]


def _normalize_target_grid_indices(value: Any) -> list[int]:
    normalized: list[int] = []
    for item in value if isinstance(value, list) else []:
        try:
            grid_number = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= grid_number <= 9:
            grid_index = grid_number - 1
            if grid_index not in normalized:
                normalized.append(grid_index)
    return normalized


def _infer_grid_position_from_indices(indices: list[int]) -> str | None:
    if not indices:
        return None
    avg_row = round(sum(index // 3 for index in indices) / len(indices))
    avg_col = round(sum(index % 3 for index in indices) / len(indices))
    return _grid_index_to_label(avg_row * 3 + avg_col)


def _merge_region_grid_bboxes(region: RegionInfo, grid_indices: list[int]) -> BBox | None:
    bboxes: list[BBox] = []
    for grid_index in grid_indices:
        if 0 <= grid_index < len(region.anchors):
            bboxes.append(_anchor_to_bbox(region.anchors[grid_index]))
    return _merge_bboxes(bboxes)


def _bbox_to_relative_bbox(bbox: BBox, width: int, height: int) -> RelativeBBox:
    return [
        round(bbox[0] / max(1, width), 6),
        round(bbox[1] / max(1, height), 6),
        round(bbox[2] / max(1, width), 6),
        round(bbox[3] / max(1, height), 6),
    ]


def _normalize_action_locate_result(
    raw_result: dict[str, Any],
    preprocess_ctx: PreprocessContext,
) -> dict[str, Any]:
    if not isinstance(raw_result, dict):
        return {}

    infer_regions = raw_result.get("infer_regions")
    if not isinstance(infer_regions, list):
        normalized = dict(raw_result)
        normalized.setdefault("raw_llm_result", raw_result)
        normalized.setdefault("source_format", "legacy_target_fields")
        normalized.setdefault("fallback_used", False)
        return normalized

    normalized_regions: list[dict[str, Any]] = []
    for item in infer_regions:
        if not isinstance(item, dict):
            continue

        region_id = item.get("target_region_id") or item.get("target_retion_id") or item.get("region_id")
        region_name = item.get("target_region_name") or item.get("region_name")
        region = _find_region(preprocess_ctx.regions, region_id=region_id, region_name=region_name)
        target_grid_indices = _normalize_target_grid_indices(item.get("nine_palace_grid"))
        target_grid_position = _normalize_grid_position_label(item.get("grid_position")) or _infer_grid_position_from_indices(
            target_grid_indices
        )
        target_relative_bbox = _normalize_relative_bbox(item.get("relative_bbox"))
        target_bbox = None
        if target_relative_bbox is not None:
            target_bbox = relative_to_absolute_coord(
                preprocess_ctx.image_width,
                preprocess_ctx.image_height,
                target_relative_bbox,
                [0, 0],
            )

        normalized_regions.append(
            {
                "predict_result": str(item.get("predict_result") or "").strip().lower(),
                "target_region_id": region.id if region else (str(region_id or "") or None),
                "target_region_name": region.name if region else (str(region_name or "") or None),
                "target_grid_position": target_grid_position,
                "target_grid_indices": target_grid_indices,
                "target_relative_bbox": target_relative_bbox,
                "target_bbox": target_bbox,
                "confidence": _normalize_confidence(item.get("confidence")),
                "reasoning": str(item.get("reason") or item.get("reasoning") or ""),
            }
        )

    if not normalized_regions:
        return {}

    ranked_regions = sorted(
        normalized_regions,
        key=lambda item: (
            0 if item.get("predict_result") == "recommend" else 1,
            -(item.get("confidence") if item.get("confidence") is not None else -1.0),
        ),
    )
    primary = ranked_regions[0]
    candidates = [
        {
            "region_id": item.get("target_region_id"),
            "region_name": item.get("target_region_name"),
            "grid_position": item.get("target_grid_position"),
            "confidence": item.get("confidence"),
            "reason": item.get("reasoning"),
        }
        for item in ranked_regions[:3]
    ]
    return {
        "target_region_id": primary.get("target_region_id"),
        "target_region_name": primary.get("target_region_name"),
        "target_grid_position": primary.get("target_grid_position"),
        "target_grid_indices": primary.get("target_grid_indices") or [],
        "target_relative_bbox": primary.get("target_relative_bbox"),
        "target_bbox": primary.get("target_bbox"),
        "confidence": primary.get("confidence"),
        "reasoning": primary.get("reasoning"),
        "candidates": candidates,
        "raw_llm_result": raw_result,
        "source_format": "infer_regions",
        "fallback_used": False,
    }


def _parse_target_candidates(
    value: Any,
    regions: list[RegionInfo],
) -> list[TargetCandidate]:
    candidates: list[TargetCandidate] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        region = _find_region(
            regions,
            region_id=item.get("region_id"),
            region_name=item.get("region_name"),
        )
        candidates.append(
            TargetCandidate(
                region_id=region.id if region else (str(item.get("region_id") or "") or None),
                region_name=region.name if region else (str(item.get("region_name") or "") or None),
                grid_position=_normalize_grid_position_label(item.get("grid_position")),
                confidence=_normalize_confidence(item.get("confidence")),
                reason=str(item.get("reason") or ""),
            )
        )
    return candidates[:3]


def _build_action_locate_fallback(
    action_text: str,
    preprocess_ctx: PreprocessContext,
    *,
    raw_llm_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target_region = _infer_region_from_action_text(action_text, preprocess_ctx.regions)
    target_grid_position = _infer_grid_from_action_text(action_text) or target_region.page_grid_position or "中"
    return {
        "target_region_id": target_region.id,
        "target_region_name": target_region.name,
        "target_grid_position": target_grid_position,
        "confidence": 0.35,
        "reasoning": "使用基于操作语义的规则兜底定位。",
        "candidates": [
            {
                "region_id": target_region.id,
                "region_name": target_region.name,
                "grid_position": target_grid_position,
                "confidence": 0.35,
                "reason": "关键词兜底匹配",
            }
        ],
        "raw_llm_result": raw_llm_result or {},
        "source_format": "fallback_rule",
        "fallback_used": True,
    }


def _build_action_locate_summary(
    llm_result: dict[str, Any],
    *,
    region: RegionInfo | None = None,
    candidates: list[TargetCandidate] | None = None,
    target_bbox: BBox | None = None,
    intersect_bbox: BBox | None = None,
) -> dict[str, Any]:
    target_grid_indices = _normalize_target_grid_indices(llm_result.get("target_grid_indices"))
    target_relative_bbox = _normalize_relative_bbox(llm_result.get("target_relative_bbox"))
    source_format = str(llm_result.get("source_format") or "unknown")
    fallback_used = bool(llm_result.get("fallback_used"))
    normalized_candidates = candidates or []
    selected_bbox = intersect_bbox or target_bbox or _normalize_bbox(llm_result.get("target_bbox"))

    return {
        "source_format": source_format,
        "fallback_used": fallback_used,
        "selected_region_id": region.id if region else (str(llm_result.get("target_region_id") or "") or None),
        "selected_region_name": region.name if region else (str(llm_result.get("target_region_name") or "") or None),
        "selected_grid_position": _normalize_grid_position_label(llm_result.get("target_grid_position")),
        "selected_grid_indices": target_grid_indices,
        "selected_confidence": _normalize_confidence(llm_result.get("confidence")),
        "selected_reason": str(llm_result.get("reasoning") or ""),
        "selected_relative_bbox": target_relative_bbox,
        "selected_bbox": selected_bbox,
        "candidate_count": len(normalized_candidates),
        "candidate_regions": [
            {
                "region_id": item.region_id,
                "region_name": item.region_name,
                "grid_position": item.grid_position,
                "confidence": item.confidence,
                "reason": item.reason,
            }
            for item in normalized_candidates
        ],
    }


def debug_info_output(
    stage: str,
    preprocess_ctx: PreprocessContext,
    target_hint: TargetLocateHint | None = None,
    *,
    output_path: str | Path | None = None,
) -> None:
    target = _resolve_debug_output_path(preprocess_ctx, stage=stage, output_path=output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if stage == "regions_identify":
        payload = _build_regions_identify_debug_payload(preprocess_ctx)
    elif stage == "action_regions":
        payload = _build_action_regions_debug_payload(preprocess_ctx, target_hint)
    elif stage == "action_target":
        payload = _build_action_target_debug_payload(preprocess_ctx, target_hint)
    else:
        raise ValueError(f"不支持的 debug stage: {stage}")
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_regions_identify_debug_payload(preprocess_ctx: PreprocessContext) -> dict[str, Any]:
    return {
        "regions": [
            {
                "name": region.name,
                "description": region.description,
                "z-index": region.z_index,
                "relative_bbox": region.relative_bbox,
                "bbox": region.bbox,
                "bbox_resized": region.bbox_resized,
            }
            for region in preprocess_ctx.regions
        ],
        "errors": list(preprocess_ctx.raw_regions_payload.get("errors") or []),
        "image": {
            "width": preprocess_ctx.image_width,
            "height": preprocess_ctx.image_height,
        },
        "image_resized": {
            "width": preprocess_ctx.resized_width,
            "height": preprocess_ctx.resized_height,
            "max_side": preprocess_ctx.resize_max_side,
        },
    }


def _build_action_regions_debug_payload(
    preprocess_ctx: PreprocessContext,
    target_hint: TargetLocateHint | None,
) -> dict[str, Any]:
    regions = _build_action_locate_debug_regions(
        preprocess_ctx,
        target_hint,
        include_selected_bbox=False,
        include_candidates=True,
    )
    return {
        "regions": regions,
        "errors": [],
        "image": {
            "width": preprocess_ctx.image_width,
            "height": preprocess_ctx.image_height,
        },
        "image_resized": {
            "width": preprocess_ctx.resized_width,
            "height": preprocess_ctx.resized_height,
            "max_side": preprocess_ctx.resize_max_side,
        },
        "target_hint": _serialize_target_hint(target_hint),
    }


def _build_action_target_debug_payload(
    preprocess_ctx: PreprocessContext,
    target_hint: TargetLocateHint | None,
) -> dict[str, Any]:
    return {
        "elements": _build_action_target_debug_elements(preprocess_ctx, target_hint),
        "errors": [],
        "image": {
            "width": preprocess_ctx.image_width,
            "height": preprocess_ctx.image_height,
        },
        "image_resized": {
            "width": preprocess_ctx.resized_width,
            "height": preprocess_ctx.resized_height,
            "max_side": preprocess_ctx.resize_max_side,
        },
        "target_hint": _serialize_target_hint(target_hint),
    }


def _build_action_locate_debug_regions(
    preprocess_ctx: PreprocessContext,
    target_hint: TargetLocateHint | None,
    *,
    include_selected_bbox: bool,
    include_candidates: bool,
) -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []
    if target_hint is None:
        return regions

    target_region = _find_region(
        preprocess_ctx.regions,
        region_id=target_hint.target_region_id,
        region_name=target_hint.target_region_name,
    )

    primary_bbox = target_hint.intersect_bbox if include_selected_bbox else None
    if primary_bbox is None:
        primary_bbox = target_hint.target_grid_bbox if include_selected_bbox else None
    if primary_bbox is not None:
        primary_relative_bbox = _bbox_to_relative_bbox(
            primary_bbox,
            preprocess_ctx.image_width,
            preprocess_ctx.image_height,
        )
        primary_resized_bbox = relative_to_absolute_coord(
            preprocess_ctx.resized_width,
            preprocess_ctx.resized_height,
            primary_relative_bbox,
            [0, 0],
        )
        regions.append(
            {
                "name": target_hint.target_region_name or "selected-region",
                "description": target_hint.reasoning or "infer_operation_target 选中的区域",
                "z-index": 1,
                "relative_bbox": primary_relative_bbox,
                "bbox": primary_bbox,
                "bbox_resized": primary_resized_bbox,
            }
        )

    if target_region is not None:
        regions.append(
            {
                "name": f"{target_region.name}-source",
                "description": target_region.description or "目标所属原始区域",
                "z-index": max(2, target_region.z_index),
                "relative_bbox": target_region.relative_bbox,
                "bbox": target_region.bbox,
                "bbox_resized": target_region.bbox_resized,
            }
        )

    if not include_candidates:
        return regions

    for index, candidate in enumerate(target_hint.candidates[:2], start=1):
        candidate_region = _find_region(
            preprocess_ctx.regions,
            region_id=candidate.region_id,
            region_name=candidate.region_name,
        )
        if candidate_region is None:
            continue
        regions.append(
            {
                "name": f"candidate-{index}:{candidate_region.name}",
                "description": candidate.reason or candidate_region.description or "候选区域",
                "z-index": max(3, candidate_region.z_index),
                "relative_bbox": candidate_region.relative_bbox,
                "bbox": candidate_region.bbox,
                "bbox_resized": candidate_region.bbox_resized,
            }
        )
    return regions


def _build_action_target_debug_elements(
    preprocess_ctx: PreprocessContext,
    target_hint: TargetLocateHint | None,
) -> list[dict[str, Any]]:
    if target_hint is None:
        return []

    selected_bbox = target_hint.intersect_bbox or target_hint.target_grid_bbox
    if selected_bbox is None:
        return []

    relative_bbox = _bbox_to_relative_bbox(
        selected_bbox,
        preprocess_ctx.image_width,
        preprocess_ctx.image_height,
    )
    return [
        {
            "type": "target",
            "control_type": _infer_action_control_type(target_hint.action_text),
            "relative_bbox": relative_bbox,
            "text": target_hint.action_text,
            "action_capablilities": _infer_action_capabilities(target_hint.action_text),
            "color_name": "unknown",
            "attributes": {
                "color": "",
                "enabled": True,
            },
            "bbox": selected_bbox,
            "region_name": target_hint.target_region_name,
            "grid_position": target_hint.target_grid_position,
            "confidence": target_hint.confidence,
            "reasoning": target_hint.reasoning,
        }
    ]


def _serialize_target_hint(target_hint: TargetLocateHint | None) -> dict[str, Any] | None:
    if target_hint is None:
        return None
    return {
        "action_text": target_hint.action_text,
        "target_region_id": target_hint.target_region_id,
        "target_region_name": target_hint.target_region_name,
        "target_grid_position": target_hint.target_grid_position,
        "target_grid_index": target_hint.target_grid_index,
        "target_grid_bbox": target_hint.target_grid_bbox,
        "intersect_bbox": target_hint.intersect_bbox,
        "confidence": target_hint.confidence,
        "reasoning": target_hint.reasoning,
        "normalized_summary": target_hint.normalized_summary,
    }


def _resolve_debug_output_path(
    preprocess_ctx: PreprocessContext,
    *,
    stage: str,
    output_path: str | Path | None = None,
) -> Path:
    default_dir = Path(__file__).resolve().parents[3] / "tests" / "output"
    if output_path:
        provided = Path(output_path)
        if provided.suffix.lower() == ".json":
            base_dir = provided.parent
            base_stem = _normalize_debug_base_stem(provided.stem)
        else:
            base_dir = provided
            base_stem = _normalize_debug_base_stem(_infer_debug_file_stem(preprocess_ctx))
    else:
        base_dir = default_dir
        base_stem = _normalize_debug_base_stem(_infer_debug_file_stem(preprocess_ctx))

    stage_file_names = {
        "regions_identify": f"{base_stem}_resized.json",
        "action_regions": f"{base_stem}_action_regions.json",
        "action_target": f"{base_stem}.json",
    }
    return base_dir / stage_file_names[stage]


def _infer_debug_file_stem(preprocess_ctx: PreprocessContext) -> str:
    source_file_name = str(preprocess_ctx.source_file_name or "").strip()
    if not source_file_name:
        return "debug"
    return Path(source_file_name).stem or "debug"


def _normalize_debug_base_stem(stem: str) -> str:
    normalized = str(stem or "").strip() or "debug"
    for suffix in ("_resized", "_action_regions"):
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)] or "debug"
    return normalized


def _infer_action_capabilities(action_text: str) -> list[str]:
    normalized = str(action_text or "").strip().lower()
    if any(keyword in normalized for keyword in ("输入", "填写", "键入", "搜索", "input", "type", "search")):
        return ["click", "input"]
    return ["click"]


def _infer_action_control_type(action_text: str) -> str:
    capabilities = _infer_action_capabilities(action_text)
    if "input" in capabilities:
        return "input"
    return "other"


def _infer_region_from_action_text(action_text: str, regions: list[RegionInfo]) -> RegionInfo:
    normalized_action = action_text.strip().lower()
    keyword_groups = [
        (("弹窗", "对话框", "popup", "dialog"), ("pop", "dialog")),
        (("菜单", "menu", "标题栏"), ("menu", "status-bar")),
        (("侧边栏", "sidebar", "导航"), ("sidebar", "left-sidebar", "right-sidebar")),
        (("状态栏", "status"), ("status-bar",)),
        (("主内容", "正文", "内容区", "表单", "列表"), ("main-content", "main-content-form", "main-content-table", "main-content-card")),
    ]

    for action_keywords, region_keywords in keyword_groups:
        if any(keyword in normalized_action for keyword in action_keywords):
            for region in sorted(regions, key=lambda item: item.z_index):
                normalized_name = region.name.strip().lower()
                if any(keyword in normalized_name for keyword in region_keywords):
                    return region

    sorted_regions = sorted(regions, key=lambda item: (item.z_index, -(item.bbox[2] - item.bbox[0]) * (item.bbox[3] - item.bbox[1])))
    return sorted_regions[0]


def _infer_grid_from_action_text(action_text: str) -> str | None:
    normalized_action = action_text.strip()
    if not normalized_action:
        return None

    if any(keyword in normalized_action for keyword in ("左上", "上左", "左上角")):
        return "左上"
    if any(keyword in normalized_action for keyword in ("右上", "上右", "右上角")):
        return "右上"
    if any(keyword in normalized_action for keyword in ("左下", "下左", "左下角")):
        return "左下"
    if any(keyword in normalized_action for keyword in ("右下", "下右", "右下角")):
        return "右下"
    if any(keyword in normalized_action for keyword in ("上中", "顶部中间", "顶部居中", "上方中间")):
        return "上中"
    if any(keyword in normalized_action for keyword in ("下中", "底部中间", "底部居中", "下方中间")):
        return "下中"
    if any(keyword in normalized_action for keyword in ("左中", "左侧中部", "左边中间")):
        return "左中"
    if any(keyword in normalized_action for keyword in ("右中", "右侧中部", "右边中间")):
        return "右中"
    if any(keyword in normalized_action for keyword in ("中间", "中央", "中心", "居中")):
        return "中"
    if "左" in normalized_action and "上" in normalized_action:
        return "左上"
    if "右" in normalized_action and "上" in normalized_action:
        return "右上"
    if "左" in normalized_action and "下" in normalized_action:
        return "左下"
    if "右" in normalized_action and "下" in normalized_action:
        return "右下"
    if "左" in normalized_action:
        return "左中"
    if "右" in normalized_action:
        return "右中"
    if "上" in normalized_action:
        return "上中"
    if "下" in normalized_action:
        return "下中"
    return None


def _parse_json_text(text: str) -> dict[str, Any] | None:
    parsed = _parse_json_value(text)
    if isinstance(parsed, dict):
        return parsed
    return None


def _parse_json_value(text: str) -> Any:
    raw = (text or "").strip()
    if not raw:
        return None

    try:
        return json.loads(raw)
    except Exception:
        pass

    fenced = re.search(r"```(?:json|json5)?\s*([\[\{][\s\S]*[\]\}])\s*```", raw)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except Exception:
            pass

    object_start = raw.find("{")
    object_end = raw.rfind("}")
    array_start = raw.find("[")
    array_end = raw.rfind("]")
    candidates: list[tuple[int, int]] = []
    if object_start != -1 and object_end != -1 and object_end > object_start:
        candidates.append((object_start, object_end))
    if array_start != -1 and array_end != -1 and array_end > array_start:
        candidates.append((array_start, array_end))

    for start, end in sorted(candidates, key=lambda item: item[0]):
        try:
            return json.loads(raw[start : end + 1])
        except Exception:
            continue
    return None


def _normalize_relative_bbox(value: Any) -> RelativeBBox | None:
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


def _normalize_z_index(value: Any) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, normalized)


def _preprocess_context_to_payload(ctx: PreprocessContext) -> dict[str, Any]:
    return {
        "image_hash": ctx.image_hash,
        "image_width": ctx.image_width,
        "image_height": ctx.image_height,
        "resized_width": ctx.resized_width,
        "resized_height": ctx.resized_height,
        "resize_max_side": ctx.resize_max_side,
        "image_data_url": ctx.image_data_url,
        "image_resized_data_url": ctx.image_resized_data_url,
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


def _preprocess_context_from_payload(payload: dict[str, Any]) -> PreprocessContext:
    raw_regions = payload.get("regions")
    regions: list[RegionInfo] = []
    for item in raw_regions if isinstance(raw_regions, list) else []:
        if not isinstance(item, dict):
            continue
        regions.append(
            RegionInfo(
                id=str(item.get("id") or ""),
                name=str(item.get("name") or ""),
                description=str(item.get("description") or ""),
                z_index=_normalize_z_index(item.get("z_index")),
                relative_bbox=list(item.get("relative_bbox") or []),
                bbox=list(item.get("bbox") or []),
                bbox_resized=list(item.get("bbox_resized") or []),
                page_grid_position=item.get("page_grid_position"),
                anchors=list(item.get("anchors") or []),
                raw=dict(item.get("raw") or {}),
            )
        )

    return PreprocessContext(
        image_hash=str(payload.get("image_hash") or ""),
        image_width=int(payload.get("image_width") or 0),
        image_height=int(payload.get("image_height") or 0),
        resized_width=int(payload.get("resized_width") or 0),
        resized_height=int(payload.get("resized_height") or 0),
        resize_max_side=int(payload.get("resize_max_side") or 0),
        image_data_url=str(payload.get("image_data_url") or ""),
        image_resized_data_url=str(payload.get("image_resized_data_url") or ""),
        page_anchors=list(payload.get("page_anchors") or []),
        regions=regions,
        raw_regions_payload=dict(payload.get("raw_regions_payload") or {}),
    )


__all__ = [
    "BBox",
    "GridAnchor",
    "ImageData",
    "PreprocessContext",
    "PreprocessResult",
    "RegionInfo",
    "RelativeBBox",
    "TargetCandidate",
    "TargetLocateHint",
    "infer_operation_target",
    "intention_decomposition",
    "preprocess_for_action",
    "preprocess_image",
]
