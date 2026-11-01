"""SDK 测试报告数据模型 (第一版)。

粒度约定: 一次 SDK 层 ai_* 调用 = 一个 ReportStep (粗粒度, 不下探定位子步骤)。
report.json 为唯一事实源, HTML 由同一模型渲染。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

REPORT_VERSION = "1.0"


@dataclass
class ReportError:
    """步骤/运行的错误信息 (不含堆栈原文, 只留类型与摘要)。"""

    type: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "message": self.message}


@dataclass
class ReportStep:
    """单个 ai_* 操作步骤。"""

    step_id: str
    index: int
    action: str                                   # ai_locate / ai_tap / ai_input / ...
    status: str = "success"                       # success / failed
    target: str = ""                              # 自然语言目标 (action_text)
    params: dict[str, Any] = field(default_factory=dict)
    started_at: str = ""
    finished_at: str = ""
    duration_ms: float = 0.0
    result_summary: Any = None
    screenshot_id: str | None = None
    sub_screenshot_ids: list[str] = field(default_factory=list)  # 操作前/操作中截图 ID 列表
    sub_bboxes: list[list[list[int]]] = field(default_factory=list)  # 每帧的 bbox 列表, 与 sub_screenshot_ids 一一对应
    sub_actions: list[Any] = field(default_factory=list)  # 每帧的指令/点击坐标/错误, 与 sub_screenshot_ids 一一对应
    error: ReportError | None = None
    token_usage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "index": self.index,
            "action": self.action,
            "status": self.status,
            "target": self.target,
            "params": self.params,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": round(self.duration_ms, 1),
            "result_summary": self.result_summary,
            "screenshot_id": self.screenshot_id,
            "sub_screenshot_ids": self.sub_screenshot_ids,
            "sub_bboxes": self.sub_bboxes,
            "sub_actions": self.sub_actions,
            "token_usage": self.token_usage,
            "error": self.error.to_dict() if self.error else None,
        }


@dataclass
class ReportEnvironment:
    """模型与运行环境摘要 (不含任何密钥)。"""

    report_version: str = REPORT_VERSION
    os: str = ""
    python_version: str = ""
    device_type: str = ""
    provider: str = ""
    model: str = ""
    vision_provider: str = ""
    vision_model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": self.report_version,
            "os": self.os,
            "python_version": self.python_version,
            "device_type": self.device_type,
            "provider": self.provider,
            "model": self.model,
            "vision_provider": self.vision_provider,
            "vision_model": self.vision_model,
        }


@dataclass
class ReportRun:
    """一次运行 (= 一个报告目录)。"""

    run_id: str
    name: str = ""
    status: str = "running"                       # running / success / failed
    started_at: str = ""
    finished_at: str = ""
    duration_ms: float = 0.0
    failure_reason: str = ""
    steps: list[ReportStep] = field(default_factory=list)
    environment: ReportEnvironment = field(default_factory=ReportEnvironment)

    def to_dict(self) -> dict[str, Any]:
        total = len(self.steps)
        failed = sum(1 for s in self.steps if s.status == "failed")
        token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        for s in self.steps:
            for key in token_usage:
                token_usage[key] += int((s.token_usage or {}).get(key) or 0)
        return {
            "run_id": self.run_id,
            "name": self.name,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": round(self.duration_ms, 1),
            "failure_reason": self.failure_reason,
            "step_count": total,
            "failed_count": failed,
            "token_usage": token_usage,
            "steps": [s.to_dict() for s in self.steps],
            "environment": self.environment.to_dict(),
        }


__all__ = ["REPORT_VERSION", "ReportError", "ReportStep", "ReportEnvironment", "ReportRun"]
