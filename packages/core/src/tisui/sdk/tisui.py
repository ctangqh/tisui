"""tisui 调用 SDK (一期同步门面)。

薄门面: 持有一个 BaseDevice, 把即时操作委托给 agent.executor。
编排逻辑不在此处 —— 见 agent/executor.py。异步 / 任务分解为后续阶段。
"""

from __future__ import annotations

from typing import Any, Optional

from tisui.agent import executor
from tisui.agent import task_builder
from tisui.agent.explore import ExploreResult, run_explore
from tisui.agent.locate import LocateOptions, LocatedElement
from tisui.device.base import BaseDevice


class tisui:
    def __init__(
        self,
        device: BaseDevice,
        models: Optional[dict[str, Any]] = None,
        debug: bool = False,
        *,
        wait_after_action: float = executor.DEFAULT_WAIT_AFTER_ACTION,
        options: Optional[LocateOptions] = None,
    ) -> None:
        self.device = device
        self.models = models or {}
        self.debug = debug
        self.wait_after_action = wait_after_action
        self.options = options

    # ---- 交互 (即时操作) -----------------------------------------------
    def ai_locate(self, action_text: str, **kwargs: Any) -> LocatedElement:
        return executor.run_locate(
            self.device, action_text, options=self._options(kwargs)
        )

    def ai_tap(self, action_text: str, **kwargs: Any) -> LocatedElement:
        return executor.run_tap(
            self.device,
            action_text,
            options=self._options(kwargs),
            wait_after=kwargs.get("wait_after", self.wait_after_action),
        )

    ai_click = ai_tap  # 别名, 对齐 Midscene aiTap

    def ai_doubleclick(self, action_text: str, **kwargs: Any) -> LocatedElement:
        """定位元素并双击 (触摸设备为双击手势)。"""
        return executor.run_double_click(
            self.device,
            action_text,
            options=self._options(kwargs),
            wait_after=kwargs.get("wait_after", self.wait_after_action),
        )

    def ai_rightclick(self, action_text: str, **kwargs: Any) -> LocatedElement:
        """定位元素并右键单击 (呼出上下文菜单)。"""
        return executor.run_right_click(
            self.device,
            action_text,
            options=self._options(kwargs),
            wait_after=kwargs.get("wait_after", self.wait_after_action),
        )

    def ai_input(self, action_text: str, text: str, **kwargs: Any) -> LocatedElement:
        return executor.run_input(
            self.device,
            action_text,
            text,
            options=self._options(kwargs),
            wait_after=kwargs.get("wait_after", self.wait_after_action),
        )

    def ai_clear(self, action_text: str, **kwargs: Any) -> LocatedElement:
        """定位输入框并清空内容 (聚焦 → 全选 → 删除)。"""
        return executor.run_clear(
            self.device,
            action_text,
            options=self._options(kwargs),
            wait_after=kwargs.get("wait_after", self.wait_after_action),
        )

    def ai_scroll(
        self,
        direction: str = "down",
        distance: int = executor.DEFAULT_SCROLL_DISTANCE,
        action_text: Optional[str] = None,
        **kwargs: Any,
    ) -> executor.ScrollResult:
        """四向滚动 (up/down/left/right), 带滚动边界识别。

        返回 ScrollResult: moved=False 表示已在边界 (如在顶部时向上滚)。
        action_text 可选, 传入时先定位并在目标元素区域内滚动。
        """
        return executor.run_scroll(
            self.device,
            direction,
            distance=distance,
            action_text=action_text,
            options=self._options(kwargs),
            wait_after=kwargs.get("wait_after", self.wait_after_action),
            check_boundary=kwargs.get("check_boundary", True),
        )

    def ai_keyboard_press(
        self, key: str, action_text: Optional[str] = None, **kwargs: Any
    ) -> Optional[LocatedElement]:
        return executor.run_keyboard_press(
            self.device,
            key,
            action_text=action_text,
            options=self._options(kwargs),
            wait_after=kwargs.get("wait_after", self.wait_after_action),
        )

    # ---- 查询 (读取) -----------------------------------------------------
    def ai_query(self, query: str, **kwargs: Any) -> Any:
        """从当前界面截图中按自然语言需求提取结构化数据, 返回提取结果。"""
        return executor.run_query(self.device, query).data

    def ai_boolean(self, query: str, **kwargs: Any) -> bool:
        """按自然语言判断一个是/否条件, 返回布尔值 (对标 Midscene aiBoolean)。"""
        return executor.run_boolean(self.device, query)

    def ai_number(self, query: str, **kwargs: Any) -> float:
        """从当前界面按自然语言提取一个数值 (对标 Midscene aiNumber)。"""
        return executor.run_number(self.device, query)

    def ai_string(self, query: str, **kwargs: Any) -> str:
        """从当前界面按自然语言提取一个字符串 (对标 Midscene aiString)。"""
        return executor.run_string(self.device, query)

    # ---- 等待 / 断言 -----------------------------------------------------
    def ai_wait_for(
        self, condition: str, *, timeout: float = 15.0, interval: float = 1.0, **kwargs: Any
    ) -> None:
        """轮询截图并用视觉模型判断条件是否满足, 超时抛出 (对标 Midscene aiWaitFor)。"""
        executor.run_wait_for(self.device, condition, timeout=timeout, interval=interval)

    def ai_assert(self, condition: str, **kwargs: Any) -> None:
        """对当前界面做一次视觉断言, 不满足则抛出 (对标 Midscene aiAssert)。"""
        executor.run_assert(self.device, condition)

    # ---- 动作编排 (后续阶段) --------------------------------------------
    def ai_act(self, instruction: str, **kwargs: Any) -> Any:
        """把一句自然语言指令自动拆解为多步操作并执行 (对标 Midscene aiAct)。"""
        _cycle_screenshots = kwargs.pop("_cycle_screenshots", None)
        _cycle_bboxes = kwargs.pop("_cycle_bboxes", None)
        _cycle_actions = kwargs.pop("_cycle_actions", None)
        return task_builder.run_act(
            self.device,
            instruction,
            context=kwargs.get("context", ""),
            cycle_limit=kwargs.get("cycle_limit"),
            total_timeout=kwargs.get("total_timeout"),
            _cycle_screenshots=_cycle_screenshots,
            _cycle_bboxes=_cycle_bboxes,
            _cycle_actions=_cycle_actions,
        )

    def ai_explore(self, goal: str, **kwargs: Any) -> ExploreResult:
        """自主探索: 给定目标后自主遍历界面并收集发现 (见 design/loop-design.md)。"""
        _cycle_screenshots = kwargs.pop("_cycle_screenshots", None)
        _cycle_bboxes = kwargs.pop("_cycle_bboxes", None)
        _cycle_actions = kwargs.pop("_cycle_actions", None)
        return run_explore(
            self.device,
            goal,
            end_condition=kwargs.get("end_condition", ""),
            strategy=kwargs.get("strategy", "coverage"),
            max_cycles=kwargs.get("max_cycles"),
            total_timeout=kwargs.get("total_timeout"),
            max_tokens=kwargs.get("max_tokens"),
            context=kwargs.get("context", ""),
            forbidden=kwargs.get("forbidden"),
            backtrack=kwargs.get("backtrack", True),
            max_depth=kwargs.get("max_depth"),
            memory_cache=kwargs.get("memory_cache"),
            reset_memory=kwargs.get("reset_memory", False),
            _cycle_screenshots=_cycle_screenshots,
            _cycle_bboxes=_cycle_bboxes,
            _cycle_actions=_cycle_actions,
        )

    # ---- 生命周期 -------------------------------------------------------
    def launch(self) -> "tisui":
        self.device.launch()
        return self

    def close(self) -> None:
        self.device.close()

    def __enter__(self) -> "tisui":
        return self.launch()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    # ---- 内部 -----------------------------------------------------------
    def _options(self, kwargs: dict[str, Any]) -> Optional[LocateOptions]:
        opts = kwargs.get("options", self.options)
        if opts is not None:
            return opts
        if self.debug:
            return LocateOptions(debug_mode=True)
        return None


__all__ = ["tisui"]