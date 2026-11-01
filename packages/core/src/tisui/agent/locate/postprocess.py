"""
⑤ 后处理 (v2)

跨区域汇总 → NMS 去重 → 阈值过滤(但绝不清空) → 排序 → 分配 id → 判定状态。

修复 v1/v2 两个已知缺陷:
1. "兜底被过滤为空": 过滤后若无元素, 保留最高分候选而非直接 failed。
2. "partial 死分支": decide_status 顺序为 failed → fallback → partial → success,
   partial 分支真实可达 (保留了最高分但整体低于阈值时命中)。
"""

from __future__ import annotations

from .coords import compute_iou
from .types import LocatedElement, LocateOptions


def postprocess_elements(
    elements: list[LocatedElement],
    options: LocateOptions,
    *,
    fallback_used: bool,
) -> tuple[list[LocatedElement], str, int]:
    """
    汇总所有区域的精定位结果 → 最终元素列表 + status + primary_index。

    fallback_used: pipeline 是否走了整图/盲区兜底路径。
    """
    if not elements:
        return [], "failed", 0

    nmsed = _nms(elements, options.nms_iou_threshold)
    ranked = sorted(nmsed, key=lambda e: e.confidence, reverse=True)

    filtered = [e for e in ranked if e.confidence >= options.confidence_threshold]
    low_confidence = False
    if not filtered:
        # 绝不清空: 至少保留最高分候选
        filtered = [ranked[0]]
        low_confidence = True

    filtered = filtered[: options.max_candidates]
    for i, elem in enumerate(filtered):
        if not elem.element_id:
            elem.element_id = f"elem_{i}"

    status = decide_status(
        filtered,
        threshold=options.confidence_threshold,
        fallback_used=fallback_used,
        low_confidence=low_confidence,
    )
    return filtered, status, 0


def decide_status(
    elements: list[LocatedElement],
    *,
    threshold: float,
    fallback_used: bool,
    low_confidence: bool,
) -> str:
    """状态判定 (顺序敏感, 保证 partial 可达)。"""
    if not elements:
        return "failed"
    if fallback_used:
        return "fallback"
    if low_confidence or elements[0].confidence < threshold:
        return "partial"
    return "success"


# ---- helpers ----

def _nms(elements: list[LocatedElement], iou_threshold: float) -> list[LocatedElement]:
    """按置信度降序贪心去重 (跨区域 bbox 均为 raw 坐标, 可直接比 IoU)。"""
    ordered = sorted(elements, key=lambda e: e.confidence, reverse=True)
    kept: list[LocatedElement] = []
    for elem in ordered:
        if all(compute_iou(elem.bbox, k.bbox) < iou_threshold for k in kept):
            kept.append(elem)
    return kept


__all__ = ["postprocess_elements", "decide_status"]
