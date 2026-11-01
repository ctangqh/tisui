"""report.json 渲染器 —— 报告的唯一事实源。"""

from __future__ import annotations

import json
from pathlib import Path

from tisui.report.types import ReportRun


def render_json(run: ReportRun, out_path: Path) -> Path:
    """把运行模型序列化为 report.json, 返回写入路径。"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(run.to_dict(), ensure_ascii=False, indent=2, default=_fallback),
        encoding="utf-8",
    )
    return out_path


# ---- 内部 ---------------------------------------------------------------

def _fallback(value: object) -> str:
    return str(value)


__all__ = ["render_json"]
