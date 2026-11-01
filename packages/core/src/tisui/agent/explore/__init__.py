"""ai_explore 自主探索子包 (见 design/loop-design.md)。

对外导出: run_explore 入口 + 结果类型 + 弹窗处理共享核心
execute_dialog_decision (供 ai_act 等动作编排方法全周期复用)。
prompts / (Phase 2: memory_store / page_identity / locate_cache / memory) 为包内实现细节。
"""

from tisui.agent.explore.explorer import (
    ExploreCoverage,
    ExploreError,
    ExploreFinding,
    ExploreNode,
    ExploreResult,
    execute_dialog_decision,
    run_explore,
)

__all__ = [
    "run_explore",
    "execute_dialog_decision",
    "ExploreResult",
    "ExploreFinding",
    "ExploreNode",
    "ExploreCoverage",
    "ExploreError",
]
