from __future__ import annotations

import base64
import hashlib
import mimetypes
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from tisui.shared.config import CACHE_ROOT

if TYPE_CHECKING:
    from .preprocess import PreprocessContext, PreprocessResult, RegionInfo, TargetLocateHint


ImageVariant = Literal["raw", "resized"]
PlaygroundStage = Literal["regions_identify", "action_regions", "action_target"]
CURRENT_FRAME_FILE_NAME = "playground.png"
CURRENT_FRAME_DIR_NAME = str(CACHE_ROOT.name)


@dataclass
class PlaygroundImageSnapshot:
    image_hash: str
    source_file_name: str | None
    image_url: str
    image_variant: ImageVariant
    width: int
    height: int
    raw_width: int
    raw_height: int
    resized_width: int
    resized_height: int
    resize_max_side: int


@dataclass
class PlaygroundRegionSnapshot:
    id: str
    name: str
    description: str
    z_index: int
    relative_bbox: list[float] = field(default_factory=list)
    bbox: list[int] = field(default_factory=list)
    bbox_resized: list[int] = field(default_factory=list)
    page_grid_position: str | None = None
    anchors: list[Any] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlaygroundTargetCandidateSnapshot:
    region_id: str | None = None
    region_name: str | None = None
    grid_position: str | None = None
    confidence: float | None = None
    reason: str | None = None


@dataclass
class PlaygroundTargetHintSnapshot:
    action_text: str
    target_region_id: str | None = None
    target_region_name: str | None = None
    target_grid_position: str | None = None
    target_grid_index: int | None = None
    target_grid_bbox: list[int] | None = None
    intersect_bbox: list[int] | None = None
    confidence: float | None = None
    reasoning: str | None = None
    candidates: list[PlaygroundTargetCandidateSnapshot] = field(default_factory=list)
    raw_llm_result: dict[str, Any] = field(default_factory=dict)
    normalized_summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlaygroundCurrentFrame:
    frame_id: str
    image_url: str
    mime_type: str
    image_path: str
    image_name: str
    image_hash: str
    width: int | None = None
    height: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlaygroundSnapshot:
    type: Literal["playground.snapshot"] = "playground.snapshot"
    stage: PlaygroundStage = "regions_identify"
    image: PlaygroundImageSnapshot | None = None
    regions: list[PlaygroundRegionSnapshot] = field(default_factory=list)
    page_anchors: list[Any] = field(default_factory=list)
    target_hint: PlaygroundTargetHintSnapshot | None = None
    config: dict[str, Any] = field(default_factory=dict)
    matrix: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    errors: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_playground_snapshot(
    preprocess_ctx: PreprocessContext,
    target_hint: TargetLocateHint | None = None,
    *,
    stage: PlaygroundStage | None = None,
    image_variant: ImageVariant = "raw",
) -> PlaygroundSnapshot:
    resolved_stage = stage or _infer_stage(target_hint)
    return PlaygroundSnapshot(
        stage=resolved_stage,
        image=_build_image_snapshot(preprocess_ctx, image_variant=image_variant),
        regions=[_build_region_snapshot(item) for item in preprocess_ctx.regions],
        page_anchors=list(preprocess_ctx.page_anchors),
        target_hint=_build_target_hint_snapshot(target_hint),
        config=preprocess_ctx.get_run_config(),
        matrix={
            "nine_matrix": preprocess_ctx.get_nine_matrix(),
            "refer_line_matrix": preprocess_ctx.get_refer_line_matrix(),
        },
        context=preprocess_ctx.get_action_context(),
        errors=list(preprocess_ctx.raw_regions_payload.get("errors") or []),
    )


def build_playground_snapshot_from_result(
    result: PreprocessResult,
    *,
    stage: PlaygroundStage | None = None,
    image_variant: ImageVariant = "raw",
) -> PlaygroundSnapshot:
    return build_playground_snapshot(
        result.preprocess,
        result.target_hint,
        stage=stage,
        image_variant=image_variant,
    )


def build_playground_payload(
    preprocess_ctx: PreprocessContext,
    target_hint: TargetLocateHint | None = None,
    *,
    stage: PlaygroundStage | None = None,
    image_variant: ImageVariant = "raw",
) -> dict[str, Any]:
    return build_playground_snapshot(
        preprocess_ctx,
        target_hint,
        stage=stage,
        image_variant=image_variant,
    ).to_dict()


def build_playground_payload_from_result(
    result: PreprocessResult,
    *,
    stage: PlaygroundStage | None = None,
    image_variant: ImageVariant = "raw",
) -> dict[str, Any]:
    return build_playground_snapshot_from_result(
        result,
        stage=stage,
        image_variant=image_variant,
    ).to_dict()


def get_current_frame(
    file_path: str | Path | None = None,
) -> PlaygroundCurrentFrame | None:
    target = Path(file_path) if file_path is not None else get_current_frame_path()
    if not target.exists() or not target.is_file():
        return None

    image_bytes = target.read_bytes()
    mime_type, _ = mimetypes.guess_type(target.name)
    normalized_mime_type = mime_type or "image/png"
    image_url = (
        f"data:{normalized_mime_type};base64,"
        f"{base64.b64encode(image_bytes).decode('ascii')}"
    )
    image_hash = hashlib.sha256(image_bytes).hexdigest()

    return PlaygroundCurrentFrame(
        frame_id=image_hash[:16],
        image_url=image_url,
        mime_type=normalized_mime_type,
        image_path=str(target),
        image_name=target.name,
        image_hash=image_hash,
    )


def get_current_frame_path() -> Path:
    return CACHE_ROOT / CURRENT_FRAME_FILE_NAME


def _build_image_snapshot(
    preprocess_ctx: PreprocessContext,
    *,
    image_variant: ImageVariant,
) -> PlaygroundImageSnapshot:
    if image_variant == "resized":
        image_url = preprocess_ctx.image_resized_data_url
        width = preprocess_ctx.resized_width
        height = preprocess_ctx.resized_height
    else:
        image_url = preprocess_ctx.image_data_url
        width = preprocess_ctx.image_width
        height = preprocess_ctx.image_height

    return PlaygroundImageSnapshot(
        image_hash=preprocess_ctx.image_hash,
        source_file_name=preprocess_ctx.source_file_name,
        image_url=image_url,
        image_variant=image_variant,
        width=width,
        height=height,
        raw_width=preprocess_ctx.image_width,
        raw_height=preprocess_ctx.image_height,
        resized_width=preprocess_ctx.resized_width,
        resized_height=preprocess_ctx.resized_height,
        resize_max_side=preprocess_ctx.resize_max_side,
    )


def _build_region_snapshot(region: RegionInfo) -> PlaygroundRegionSnapshot:
    return PlaygroundRegionSnapshot(
        id=region.id,
        name=region.name,
        description=region.description,
        z_index=region.z_index,
        relative_bbox=list(region.relative_bbox),
        bbox=list(region.bbox),
        bbox_resized=list(region.bbox_resized),
        page_grid_position=region.page_grid_position,
        anchors=list(region.anchors),
        raw=dict(region.raw),
    )


def _build_target_hint_snapshot(
    target_hint: TargetLocateHint | None,
) -> PlaygroundTargetHintSnapshot | None:
    if target_hint is None:
        return None

    return PlaygroundTargetHintSnapshot(
        action_text=target_hint.action_text,
        target_region_id=target_hint.target_region_id,
        target_region_name=target_hint.target_region_name,
        target_grid_position=target_hint.target_grid_position,
        target_grid_index=target_hint.target_grid_index,
        target_grid_bbox=list(target_hint.target_grid_bbox) if target_hint.target_grid_bbox else None,
        intersect_bbox=list(target_hint.intersect_bbox) if target_hint.intersect_bbox else None,
        confidence=target_hint.confidence,
        reasoning=target_hint.reasoning,
        candidates=[
            PlaygroundTargetCandidateSnapshot(
                region_id=item.region_id,
                region_name=item.region_name,
                grid_position=item.grid_position,
                confidence=item.confidence,
                reason=item.reason,
            )
            for item in target_hint.candidates
        ],
        raw_llm_result=dict(target_hint.raw_llm_result),
        normalized_summary=dict(target_hint.normalized_summary),
    )


def _infer_stage(target_hint: TargetLocateHint | None) -> PlaygroundStage:
    if target_hint is None:
        return "regions_identify"
    if target_hint.target_grid_bbox or target_hint.intersect_bbox:
        return "action_target"
    return "action_regions"


__all__ = [
    "ImageVariant",
    "CURRENT_FRAME_DIR_NAME",
    "CURRENT_FRAME_FILE_NAME",
    "PlaygroundCurrentFrame",
    "PlaygroundImageSnapshot",
    "PlaygroundRegionSnapshot",
    "PlaygroundStage",
    "PlaygroundSnapshot",
    "PlaygroundTargetCandidateSnapshot",
    "PlaygroundTargetHintSnapshot",
    "build_playground_payload",
    "build_playground_payload_from_result",
    "build_playground_snapshot",
    "build_playground_snapshot_from_result",
    "get_current_frame",
    "get_current_frame_path",
]
