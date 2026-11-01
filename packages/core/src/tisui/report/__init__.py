"""SDK 测试报告子系统。

采集一次运行中每个 ai_* 操作步骤 (粗粒度), 输出 report.json + report.html 与关键截图。

对外最小接口:
    start_run(name, *, device=None)   运行上下文 (自动 finalize, 失败也落报告)
    instrument(app, collector)        零侵入包装 tisui, 使 ai_* 自动记步
"""

from __future__ import annotations

from tisui.report.collector import ReportCollector, start_run
from tisui.report.recorder import instrument

__all__ = ["start_run", "instrument", "ReportCollector"]
