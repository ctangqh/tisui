"""报告采集器与运行上下文。

用法:
    from tisui.report import start_run, instrument
    with tisui(device) as app, start_run("bing 搜索", device=device) as run:
        app = instrument(app, run)
        app.ai_input(...); app.ai_query(...)
    # 退出 with 时自动 finalize, 成功/失败都会落 report.json + report.html

采集粒度: 一次 ai_* 调用 = 一个步骤 (由 recorder.instrument 负责调用本采集器)。
"""

from __future__ import annotations

import platform
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

from tisui.report.renderer_html import render_html
from tisui.report.renderer_json import render_json
from tisui.report.screenshot_store import ScreenshotStore
from tisui.report.types import ReportEnvironment, ReportError, ReportRun, ReportStep


class ReportCollector:
    """持有一次运行的报告模型, 提供步骤记录与截图落盘, finalize 时渲染产物。"""

    def __init__(self, run: ReportRun, run_dir: Path, screenshots: ScreenshotStore) -> None:
        self.run = run
        self.run_dir = Path(run_dir)
        self._screenshots = screenshots
        self._finalized = False

    def start_step(
        self, action: str, *, target: str = "", params: Optional[dict[str, Any]] = None
    ) -> ReportStep:
        """开启一个步骤并加入时间线, 返回该步骤 (供 finish_step 收尾)。"""
        index = len(self.run.steps) + 1
        step = ReportStep(
            step_id=f"step_{index:03d}",
            index=index,
            action=action,
            target=target,
            params=dict(params or {}),
            started_at=_now(),
        )
        step._monotonic_start = time.perf_counter()  # type: ignore[attr-defined]
        self.run.steps.append(step)
        return step

    def finish_step(
        self,
        step: ReportStep,
        *,
        status: str = "success",
        result_summary: Any = None,
        error: Optional[ReportError] = None,
        screenshot: Optional[bytes] = None,
        token_usage: Optional[dict[str, Any]] = None,
        sub_screenshots: Optional[list[bytes]] = None,
        sub_bboxes: Optional[list[list[list[int]]]] = None,
        sub_actions: Optional[list[Any]] = None,
    ) -> None:
        """收尾一个步骤: 记录状态/结果/错误/Token 用量, 并落盘截图 (主截图 + 子截图)。"""
        start = getattr(step, "_monotonic_start", None)
        step.duration_ms = (time.perf_counter() - start) * 1000 if start else 0.0
        step.finished_at = _now()
        step.status = status
        step.result_summary = result_summary
        step.error = error
        step.token_usage = dict(token_usage) if token_usage else {}
        if screenshot:
            step.screenshot_id = self._screenshots.save(screenshot)
        if sub_screenshots:
            seen: set[str] = {step.screenshot_id} if step.screenshot_id else set()
            kept_bboxes: list[list[list[int]]] = []
            kept_actions: list[Any] = []
            for index, sub in enumerate(sub_screenshots):
                if sub:
                    sid = self._screenshots.save(sub)
                    if sid not in seen:
                        seen.add(sid)
                        step.sub_screenshot_ids.append(sid)
                        # 子截图按内容去重丢帧时, 必须同步丢弃同索引的 bbox/action,
                        # 否则三列表长度不一致, 渲染器按帧索引画框会错位到别的帧
                        if sub_bboxes and index < len(sub_bboxes):
                            kept_bboxes.append(sub_bboxes[index])
                        if sub_actions and index < len(sub_actions):
                            kept_actions.append(sub_actions[index])
            if kept_bboxes:
                step.sub_bboxes = kept_bboxes
            if kept_actions:
                step.sub_actions = kept_actions

    def finalize(self, *, status: Optional[str] = None, failure_reason: str = "") -> Path:
        """收尾运行并渲染 report.json + report.html, 返回报告目录。"""
        if self._finalized:
            return self.run_dir
        self._finalized = True
        self.run.finished_at = _now()
        start = getattr(self.run, "_monotonic_start", None)
        self.run.duration_ms = (time.perf_counter() - start) * 1000 if start else 0.0
        if status is not None:
            self.run.status = status
        elif self.run.status == "running":
            self.run.status = "failed" if any(s.status == "failed" for s in self.run.steps) else "success"
        if failure_reason:
            self.run.failure_reason = failure_reason
        render_json(self.run, self.run_dir / "report.json")
        render_html(self.run, self.run_dir / "report.html")
        return self.run_dir


@contextmanager
def start_run(
    name: str, *, device: Any = None, run_id: Optional[str] = None, output_root: Optional[Path] = None
) -> Iterator[ReportCollector]:
    """开启一次报告运行 (上下文管理器)。退出时自动 finalize, 异常也会落报告并置为 failed。"""
    run = ReportRun(
        run_id=run_id or _new_run_id(),
        name=name,
        status="running",
        started_at=_now(),
        environment=_build_environment(device),
    )
    run._monotonic_start = time.perf_counter()  # type: ignore[attr-defined]
    run_dir = _resolve_output_root(output_root) / run.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    collector = ReportCollector(run, run_dir, ScreenshotStore(run_dir / "screenshots"))
    try:
        yield collector
    except BaseException as exc:  # noqa: BLE001 - 保证失败也落报告后再抛出
        collector.finalize(status="failed", failure_reason=f"{type(exc).__name__}: {exc}")
        raise
    else:
        collector.finalize()


# ---- 内部 ---------------------------------------------------------------

def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def _new_run_id() -> str:
    return f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"


def _resolve_output_root(output_root: Optional[Path]) -> Path:
    if output_root is not None:
        return Path(output_root)
    try:
        from tisui.shared.config import settings

        # 优先读 config.yaml 的 runtime.report_path (已解析为绝对路径)
        report_path = settings.runtime_environment.report_path
        if report_path:
            return Path(report_path)
        # 未配置时退化到 <workspace>/output/reports
        workspace = settings.runtime_environment.workspace_root
        if workspace:
            return Path(workspace) / "output" / "reports"
    except Exception:  # noqa: BLE001 - 配置不可用时退化到当前工作目录
        pass
    return Path.cwd() / "output" / "reports"


def _build_environment(device: Any) -> ReportEnvironment:
    env = ReportEnvironment(
        os=platform.platform(),
        python_version=platform.python_version(),
        device_type=type(device).__name__ if device is not None else "",
    )
    try:
        from tisui.shared.config import settings

        llm = settings.llm_config
        vision = settings.vision_config
        env.provider, env.model = llm.provider, llm.model
        env.vision_provider, env.vision_model = vision.provider, vision.model
    except Exception:  # noqa: BLE001 - 模型配置不可用时留空
        pass
    return env


__all__ = ["ReportCollector", "start_run"]
