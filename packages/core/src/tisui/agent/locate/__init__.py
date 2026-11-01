"""
区域感知 · 多尺度视觉定位 (v2)

五阶段: ① 预处理 → ② 布局分区 → ③ 意图选区 → ④ 聚焦精定位 → ⑤ 后处理

对外统一入口:
    run_pipeline(image_bytes, action_text, *, options=None) → LocateResult

策略: 缩略图分区 + 意图选区 + 从 raw 裁 patch 精定位, 消除坐标盲猜。
视觉调用仅 2 类: overview 分区(便宜) + 小 patch 精定位(精准)。
"""

from .pipeline import run_pipeline
from .types import (
    LayoutRegion,
    LayoutResult,
    LocatedElement,
    LocateOptions,
    LocateResult,
    RegionSelection,
)

__all__ = [
    "run_pipeline",
    "LocateOptions",
    "LocateResult",
    "LocatedElement",
    "LayoutRegion",
    "LayoutResult",
    "RegionSelection",
]
