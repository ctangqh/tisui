"""ai_* 调用记录器 —— 零侵入包装 tisui 门面。

instrument(app, collector) 返回一个代理对象: 拦截 ai_* 方法, 每次调用自动记一步
(动作/目标/参数/耗时/结果或错误 + 一张关键截图), 其余属性/方法透传给原 app。
不修改 sdk/tisui.py 与 agent/executor.py。
"""

from __future__ import annotations

from typing import Any

from tisui.report.collector import ReportCollector
from tisui.report.types import ReportError
from tisui.shared.models.invoker import read_token_meter, reset_token_meter

_AI_METHODS = frozenset(
    {
        "ai_locate",
        "ai_tap",
        "ai_click",
        "ai_doubleclick",
        "ai_rightclick",
        "ai_input",
        "ai_clear",
        "ai_scroll",
        "ai_keyboard_press",
        "ai_query",
        "ai_boolean",
        "ai_number",
        "ai_string",
        "ai_assert",
        "ai_wait_for",
        "ai_act",
        "ai_explore",
    }
)

# 动作类方法: 会改变页面状态, 需要采集操作前截图用于回放
_ACTION_METHODS = frozenset(
    {"ai_tap", "ai_click", "ai_doubleclick", "ai_rightclick", "ai_input", "ai_clear", "ai_scroll", "ai_keyboard_press", "ai_act", "ai_wait_for", "ai_explore"}
)


def instrument(app: Any, collector: ReportCollector) -> "_RecordingProxy":
    """包装 tisui 实例, 使其 ai_* 调用自动写入报告。返回代理, 用法与原 app 一致。"""
    return _RecordingProxy(app, collector)


class _RecordingProxy:
    def __init__(self, app: Any, collector: ReportCollector) -> None:
        self._app = app
        self._collector = collector

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._app, name)
        if name in _AI_METHODS and callable(attr):
            return self._wrap(name, attr)
        return attr

    def _wrap(self, action: str, func: Any) -> Any:
        def recorded(*args: Any, **kwargs: Any) -> Any:
            target, params = _describe_call(action, args, kwargs)
            step = self._collector.start_step(action, target=target, params=params)
            reset_token_meter()

            # 操作前截图 (仅动作类方法)
            before = self._safe_screenshot() if action in _ACTION_METHODS else None
            cycle_screenshots: list[bytes] = []
            cycle_bboxes: list[list[list[int]]] = []
            cycle_actions: list[Any] = []

            try:
                if action == "ai_act":
                    merged = dict(kwargs)
                    merged["_cycle_screenshots"] = cycle_screenshots
                    merged["_cycle_bboxes"] = cycle_bboxes
                    merged["_cycle_actions"] = cycle_actions
                    result = func(*args, **merged)
                elif action == "ai_explore":
                    merged = dict(kwargs)
                    merged["_cycle_screenshots"] = cycle_screenshots
                    merged["_cycle_bboxes"] = cycle_bboxes
                    merged["_cycle_actions"] = cycle_actions
                    result = func(*args, **merged)
                else:
                    result = func(*args, **kwargs)
            except BaseException as exc:  # noqa: BLE001 - 记录失败后原样抛出
                after = self._safe_screenshot()
                sub = _build_sub_screenshots(before, cycle_screenshots)
                sub_bboxes_data = _build_sub_bboxes(before, cycle_bboxes) if action in ("ai_act", "ai_explore") else None
                sub_actions_data = _build_sub_actions(before, cycle_actions) if action in ("ai_act", "ai_explore") else None
                self._collector.finish_step(
                    step,
                    status="failed",
                    error=ReportError(type=type(exc).__name__, message=str(exc)),
                    screenshot=after,
                    token_usage=read_token_meter(),
                    sub_screenshots=sub,
                    sub_bboxes=sub_bboxes_data,
                    sub_actions=sub_actions_data,
                )
                raise

            after = self._safe_screenshot()
            sub = _build_sub_screenshots(before, cycle_screenshots)
            sub_bboxes_data = _build_sub_bboxes(before, cycle_bboxes) if action in ("ai_act", "ai_explore") else None
            sub_actions_data = _build_sub_actions(before, cycle_actions) if action in ("ai_act", "ai_explore") else None
            self._collector.finish_step(
                step,
                status="success",
                result_summary=_summarize(action, result),
                screenshot=after,
                token_usage=read_token_meter(),
                sub_screenshots=sub,
                sub_bboxes=sub_bboxes_data,
                sub_actions=sub_actions_data,
            )
            return result

        return recorded

    def _safe_screenshot(self) -> Any:
        try:
            return self._app.device.screenshot()
        except Exception:  # noqa: BLE001 - 截图失败不影响主流程与报告
            return None


# ---- 内部 ---------------------------------------------------------------

def _describe_call(action: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if action == "ai_input":
        target = str(args[0]) if args else str(kwargs.get("action_text", ""))
        text = args[1] if len(args) > 1 else kwargs.get("text", "")
        return target, {"text": text}
    if action == "ai_keyboard_press":
        key = args[0] if args else kwargs.get("key", "")
        target = str(args[1]) if len(args) > 1 else str(kwargs.get("action_text") or "")
        return target, {"key": key}
    if action == "ai_scroll":
        direction = args[0] if args else kwargs.get("direction", "down")
        distance = args[1] if len(args) > 1 else kwargs.get("distance", "")
        target = str(args[2]) if len(args) > 2 else str(kwargs.get("action_text") or "")
        return target, {"direction": direction, "distance": distance}
    if action in ("ai_query", "ai_boolean", "ai_number", "ai_string"):
        query = args[0] if args else kwargs.get("query", "")
        return "", {"query": query}
    if action in ("ai_assert", "ai_wait_for"):
        condition = args[0] if args else kwargs.get("condition", "")
        return str(condition), {}
    if action == "ai_act":
        instruction = args[0] if args else kwargs.get("instruction", "")
        return str(instruction), {}
    if action == "ai_explore":
        goal = args[0] if args else kwargs.get("goal", "")
        params: dict[str, Any] = {}
        if kwargs.get("strategy"):
            params["strategy"] = kwargs["strategy"]
        if kwargs.get("end_condition"):
            params["end_condition"] = kwargs["end_condition"]
        return str(goal), params
    # ai_locate / ai_tap / ai_click / ai_doubleclick / ai_rightclick
    target = str(args[0]) if args else str(kwargs.get("action_text", ""))
    return target, {}


def _summarize(action: str, result: Any) -> Any:
    if action in ("ai_query", "ai_boolean", "ai_number", "ai_string"):
        return result
    if result is None:
        return None
    if action == "ai_explore" and hasattr(result, "coverage"):
        coverage = result.coverage
        return {
            "status": getattr(result, "status", ""),
            "total_cycles": getattr(result, "total_cycles", 0),
            "findings": len(getattr(result, "findings", []) or []),
            "pages_visited": getattr(coverage, "pages_visited", 0),
            "elements_interacted": getattr(coverage, "elements_interacted", 0),
            "anomalies": getattr(coverage, "anomalies", 0),
        }
    if action == "ai_scroll" and hasattr(result, "moved"):
        element = getattr(result, "element", None)
        return {
            "moved": bool(result.moved),
            "direction": getattr(result, "direction", ""),
            "distance": getattr(result, "distance", 0),
            "bbox": getattr(element, "bbox", None) if element is not None else None,
        }
    if hasattr(result, "action_point") and hasattr(result, "confidence"):
        return {
            "text": getattr(result, "text", ""),
            "action_point": getattr(result, "action_point", None),
            "confidence": round(float(getattr(result, "confidence", 0.0)), 3),
            "bbox": getattr(result, "bbox", None),
        }
    return str(result)


def _build_sub_screenshots(
    before: bytes | None, cycles: list[bytes]
) -> list[bytes] | None:
    """拼接操作前截图 + ai_act 每轮截图, 过滤 None。"""
    sub: list[bytes] = []
    if before:
        sub.append(before)
    sub.extend(s for s in cycles if s)
    return sub or None


def _build_sub_bboxes(
    before: bytes | None,
    cycle_bboxes: list[list[list[int]]],
) -> list[list[list[int]]] | None:
    """构建与 sub_screenshots 对应的 bbox 列表:
    [ [] (before 帧无 bbox), cycle_0_bboxes, cycle_1_bboxes, ... ]
    """
    result: list[list[list[int]]] = []
    if before:
        result.append([])  # before 帧无动作
    result.extend(cycle_bboxes)
    return result or None


def _build_sub_actions(
    before: bytes | None,
    cycle_actions: list[Any],
) -> list[Any] | None:
    """构建与 sub_screenshots 对应的动作信息列表 (指令/点击坐标/下一步规则):
    [ None (before 帧无动作), cycle_0_actions, cycle_1_actions, ... ]
    """
    result: list[Any] = []
    if before:
        result.append(None)  # before 帧无动作
    result.extend(cycle_actions)
    return result or None


__all__ = ["instrument"]
