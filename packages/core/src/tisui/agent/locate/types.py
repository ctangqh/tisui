"""
区域感知 · 多尺度视觉定位 (v2) 数据结构定义。

坐标空间约定 (见 design/locator-logic-v2.md §2):
- raw:  原始输入图像素坐标 (对外输出)
- base: 原图约束到 max_image_size 后的基准图坐标 (布局区域存这里)
- overview: base 的缩略图, 仅用于布局分区
- patch: 从 raw 裁出的局部块 (精定位在此进行, 输出直接 +origin 回 raw)
"""

from __future__ import annotations

from dataclasses import dataclass, field

BBox = list[int]                # [left, top, right, bottom]
RelativeBBox = list[float]
Coordinate = list[int]          # [x, y]


# =============================================================================
# Options
# =============================================================================

@dataclass
class LocateOptions:
    """v2 定位选项"""
    # 尺寸
    max_image_size: tuple[int, int] = (2048, 2048)   # base 上限

    # 区域选择 / 裁剪
    region_expand_ratio: float = 0.08                 # 裁剪区域外扩 (按图像尺寸)
    max_regions_to_fine: int = 2                      # 最多对几个候选区域做精定位

    # 结果
    confidence_threshold: float = 0.3
    nms_iou_threshold: float = 0.7
    max_candidates: int = 5

    # 缓存 / 调试
    enable_cache: bool = True
    debug_mode: bool | None = None                    # None = 跟随 config.yaml runtime.debug


# =============================================================================
# ① 预处理
# =============================================================================

@dataclass
class PreprocessingResult:
    """预处理产物; PIL 图不参与序列化。"""
    raw_image: object                       # PIL.Image (raw, 精定位从此裁剪)
    base_image: object                      # PIL.Image (base, 约束到 max_image_size)
    overview_image: object                  # PIL.Image (overview, 分区用)
    raw_size: tuple[int, int]               # (W0, H0)
    base_size: tuple[int, int]              # (Wb, Hb)
    overview_size: tuple[int, int]
    image_hash: str                         # xxhash64, 缓存 key
    operations: list[str] = field(default_factory=list)
    duration_ms: float = 0.0


# =============================================================================
# ② 布局分区
# =============================================================================

@dataclass
class LayoutRegion:
    region_id: str
    region_type: str                        # header/content/list/form/sidebar/toolbar/modal/nav/footer/unknown
    bbox: BBox = field(default_factory=lambda: [0, 0, 0, 0])   # base 坐标
    semantic_tags: list[str] = field(default_factory=list)
    description: str = ""
    confidence: float = 0.5
    z_index: int = 0                        # 0=普通页面内容(基础层); >=1=覆盖层/浮动层(数值越大越靠上)


@dataclass
class LayoutResult:
    regions: list[LayoutRegion] = field(default_factory=list)
    layout_type: str = "unknown"            # simple_form/long_list/dashboard/modal_dialog/unknown
    model_used: str = ""
    duration_ms: float = 0.0
    raw_model_response: dict | None = None


# =============================================================================
# ③ 意图选区
# =============================================================================

@dataclass
class RegionSelection:
    selected: list[LayoutRegion] = field(default_factory=list)
    reasoning: str = ""
    confidence: float = 0.5
    is_fallback: bool = False               # True 表示退化 (整图/最大区域)


# =============================================================================
# ④ 精定位
# =============================================================================

@dataclass
class CroppedPatch:
    patch_image: object                     # PIL.Image (从 raw 裁剪)
    bbox_in_raw: BBox                        # patch 在 raw 图中的位置 [l,t,r,b]
    source_region_id: str = ""


@dataclass
class LocatedElement:
    element_id: str = ""
    type: str = "other"
    refine_type: str = "unknown"
    text: str = ""
    description: str = ""
    bbox: BBox = field(default_factory=lambda: [0, 0, 0, 0])          # raw 坐标 (对外)
    bbox_relative: RelativeBBox = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    action_point: Coordinate = field(default_factory=lambda: [0, 0])  # raw 坐标 (对外)
    action_point_hint: str = "center"
    confidence: float = 0.0
    enabled: bool = True
    color: str | None = None
    action_capabilities: list[str] = field(default_factory=list)
    locator_way: str = "fine"               # fine / region_fallback
    source_region_id: str = ""
    reasoning: str = ""
    is_fallback: bool = False


# =============================================================================
# Trace / 结果
# =============================================================================

@dataclass
class StageTrace:
    """单阶段执行轨迹"""
    stage_name: str
    duration_ms: float = 0.0
    model_calls: int = 0
    model_name: str = ""
    input_size: tuple[int, int] = (0, 0)
    output_count: int = 0
    decisions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class FallbackRecord:
    stage: str
    reason: str
    fallback_to: str = ""
    timestamp: str = ""


@dataclass
class StageDebugBbox:
    """阶段调试图上的一个标注框 (坐标相对该阶段展示图)。"""
    bbox: BBox = field(default_factory=lambda: [0, 0, 0, 0])
    label: str = ""
    style: str = "candidate"                 # candidate / primary / fallback / crop_window
    confidence: float = 0.0


@dataclass
class StageDebugImage:
    """单阶段可视化产物: 该阶段展示图 + 其上的标注框 (供 playground 回放)。"""
    stage: str
    image_base64: str = ""                   # data:image/png;base64,...
    image_width: int = 0
    image_height: int = 0
    crop_on_raw: BBox | None = None          # 该图在 raw 中的裁剪窗口 (patch 阶段用)
    bboxes: list[StageDebugBbox] = field(default_factory=list)
    zoom_scale: float = 1.0
    duration_ms: float = 0.0
    model_calls: int = 0
    decisions: list[str] = field(default_factory=list)


@dataclass
class LocateResult:
    """v2 定位最终结果"""
    status: str                             # success / partial / fallback / failed
    elements: list[LocatedElement] = field(default_factory=list)
    primary_index: int = 0
    error: str | None = None
    trace: list[StageTrace] = field(default_factory=list)
    fallbacks: list[FallbackRecord] = field(default_factory=list)
    total_duration_ms: float = 0.0
    raw_size: tuple[int, int] = (0, 0)
    base_size: tuple[int, int] = (0, 0)
    layout_type: str = "unknown"
    cache_hit: str | None = None            # None / "l2" (L1 已移除)
    debug_stages: list[StageDebugImage] = field(default_factory=list)
    version: str = "2.0"


__all__ = [
    "BBox",
    "RelativeBBox",
    "Coordinate",
    "LocateOptions",
    "PreprocessingResult",
    "LayoutRegion",
    "LayoutResult",
    "RegionSelection",
    "CroppedPatch",
    "LocatedElement",
    "StageTrace",
    "StageDebugBbox",
    "StageDebugImage",
    "FallbackRecord",
    "LocateResult",
]
