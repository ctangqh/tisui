"""
③ 意图选区 (v2)

**纯文本**: 只把 ② 布局分区的区域清单 (type/tags/description/bbox) 连同 action_text
交给文本 LLM, 让它选出目标最可能所在的 1~max_regions_to_fine 个区域。
不看图 → 便宜; 真正的像素级判断留给 ④ 精定位。

消除盲猜: 选区结果永远约束在"已存在的区域"内; 模型无有效输出时退化为
"按面积挑最大的 content/list 区域", 而不是对整图盲猜。
"""

from __future__ import annotations

import json
import time
from typing import Any

from tisui.shared.logger import logger
from tisui.shared.models.invoker import invoke_text_llm

from .types import LayoutRegion, LayoutResult, LocateOptions, RegionSelection

_REGION_SELECT_PROMPT = """\
You are choosing which page region(s) most likely contain a UI target.
You are given a target instruction and a list of regions (NO image).

Target instruction:
{action_text}

Regions (region_id | type | tags | description | bbox=[l,t,r,b] in base pixels):
{regions_block}

Pick the region(s) where the target most likely is. Prefer ONE region; pick a
second only if genuinely ambiguous. Choose at most {max_regions}.

Output JSON only:
{{
  "selected_region_ids": ["region_2"],
  "reasoning": "why these regions",
  "confidence": 0.0-1.0
}}

Rules:
1. Only use region_id values that appear in the list above.
2. If nothing clearly matches, still pick the single most plausible region.
"""


def perform_region_selection(
    layout: LayoutResult,
    action_text: str,
    options: LocateOptions,
) -> RegionSelection:
    """从布局区域中挑出目标最可能所在的区域 (纯文本, 无图)。"""
    start = time.time()
    regions = layout.regions

    if not regions:
        # 无区域可选 → 交给 pipeline 做整图兜底
        return RegionSelection(selected=[], reasoning="no regions from layout", is_fallback=True)

    if len(regions) == 1:
        return RegionSelection(selected=list(regions), reasoning="single region", confidence=regions[0].confidence)

    prompt = _REGION_SELECT_PROMPT.format(
        action_text=action_text or "(unspecified)",
        regions_block=_render_regions(regions),
        max_regions=options.max_regions_to_fine,
    )

    try:
        result = invoke_text_llm(content=prompt)
        raw = _parse_json_object(str(result.get("content") or ""))
    except Exception as exc:
        logger.warning(f"意图选区 LLM 调用失败: {exc}")
        return _fallback_selection(regions, reason=f"llm error: {exc}", start=start)

    by_id = {r.region_id: r for r in regions}
    selected_ids = raw.get("selected_region_ids") if isinstance(raw, dict) else None
    selected: list[LayoutRegion] = []
    if isinstance(selected_ids, list):
        for rid in selected_ids:
            region = by_id.get(str(rid))
            if region is not None and region not in selected:
                selected.append(region)
            if len(selected) >= options.max_regions_to_fine:
                break

    if not selected:
        return _fallback_selection(regions, reason="model selected no valid region", start=start)

    return RegionSelection(
        selected=selected,
        reasoning=str(raw.get("reasoning") or "") if isinstance(raw, dict) else "",
        confidence=_normalize_confidence(raw.get("confidence") if isinstance(raw, dict) else None),
        is_fallback=False,
    )


# ---- helpers ----

def _fallback_selection(
    regions: list[LayoutRegion],
    *,
    reason: str,
    start: float,
) -> RegionSelection:
    """退化: 挑面积最大的 content/list 区域 (仍是真实区域, 非整图盲猜)。"""
    _ = start
    preferred = [r for r in regions if r.region_type in ("content", "list", "form")]
    pool = preferred or regions
    best = max(pool, key=_area)
    return RegionSelection(
        selected=[best],
        reasoning=f"fallback ({reason}); picked largest {best.region_type}",
        confidence=0.2,
        is_fallback=True,
    )


def _area(region: LayoutRegion) -> int:
    l, t, r, b = region.bbox
    return max(0, r - l) * max(0, b - t)


def _render_regions(regions: list[LayoutRegion]) -> str:
    lines: list[str] = []
    for r in regions:
        tags = ",".join(r.semantic_tags) if r.semantic_tags else "-"
        desc = (r.description or "-").replace("\n", " ")
        lines.append(f"{r.region_id} | {r.region_type} | {tags} | {desc} | {r.bbox}")
    return "\n".join(lines)


def _normalize_confidence(value: Any) -> float:
    try:
        c = float(value)
    except (TypeError, ValueError):
        return 0.5
    if c > 1 and c <= 100:
        c = c / 100.0
    return max(0.0, min(1.0, c))


def _parse_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[0].strip().lower() == "json":
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(raw[start:end + 1])
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
    return {}


__all__ = ["perform_region_selection"]
