"""ai_act 自动规划执行 (一期同步)。

把一句自然语言指令交给规划器 (VLM): 看当前截图 → 输出下一批动作 + 状态。
每轮执行完动作后重新观察并重规划 (plan-act-observe), 直到规划器判定 finished /
failed, 或触达轮次 / 墙钟上限。动作复用 executor 的即时操作原语, 不重复实现
定位与执行逻辑。query 动作的结果会回流给规划器, 支撑"依据页面数据再操作"。

不使用 VLM 轮询等待: 需要等页面变化时规划器发 sleep, 下一轮重新观察即可, 省 token。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from tisui.agent import executor
from tisui.agent.explore import execute_dialog_decision
from tisui.agent.vision_io import image_to_data_url, parse_json_loose
from tisui.device.base import BaseDevice
from tisui.shared.config import settings
from tisui.shared.logger import logger
from tisui.shared.models.invoker import invoke_vision_llm


class ActError(RuntimeError):
    """ai_act 规划或执行失败。"""


_DIALOG_FAIL_LIMIT = 3            # 同一弹窗连续处理失败次数 -> ActError (任务被阻塞)
_MAX_DIALOG_ONLY_CYCLES = 4       # 同一弹窗累计出现轮数上限 -> ActError (防卡死; 按 target 计数, 交替轮不可绕过)


def run_act(
    device: BaseDevice,
    instruction: str,
    *,
    context: str = "",
    cycle_limit: int | None = None,
    total_timeout: float | None = None,
    _cycle_screenshots: list[bytes] | None = None,
    _cycle_bboxes: list[list[list[int]]] | None = None,
    _cycle_actions: list[list[dict[str, Any]]] | None = None,
) -> str | None:
    """自然语言指令 → 自动规划并逐步执行; 返回完成结论 (数据类任务含提取结果)。

    终止条件: 规划器 finished/failed、达到 cycle_limit 轮、或超过 total_timeout 秒。
    未显式传参时取 config.yaml 的 act.cycle_limit / act.total_timeout。

    _cycle_screenshots: 如果传入一个列表, 每轮规划截图会追加到该列表中, 供报告采集。
    _cycle_bboxes: 如果传入一个列表, 每轮每步的 bbox 会按 [[a1_bbox, a2_bbox], ...] 追加。
    _cycle_actions: 如果传入一个列表, 每轮每步的指令/点击坐标/错误会按列表追加
                    (与 _cycle_screenshots 一一对应): [[{"action": ..., "click": ..., "error": ...}, ...]]。
    """
    act_config = settings.act_config
    max_cycles = max(1, cycle_limit if cycle_limit is not None else act_config.cycle_limit)
    budget = total_timeout if total_timeout is not None else act_config.total_timeout
    deadline = time.monotonic() + max(0.0, budget)

    history: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    dialog_failures: dict[str, int] = {}            # 弹窗 target -> 连续执行失败次数
    dialog_seen: dict[str, int] = {}                # 弹窗 target -> 累计出现轮数 (普通轮不清零)

    for _ in range(max_cycles):
        if time.monotonic() >= deadline:
            raise ActError(f"ai_act 超过总时长上限 ({budget}s) 仍未完成")
        image = device.screenshot()
        if _cycle_screenshots is not None:
            _cycle_screenshots.append(image)
        if _cycle_bboxes is not None:
            _cycle_bboxes.append([])                # 本轮占位: 动作执行后填充; 弹窗/结束轮保持空组
        if _cycle_actions is not None:
            _cycle_actions.append([])               # 本轮占位: 动作执行后填充; 弹窗/结束轮保持空组
        plan = _plan_next(image, instruction, context, history, observations)
        if plan.status == "finished":
            return plan.summary or None
        if plan.status == "failed":
            raise ActError(plan.reason or "规划器判定任务无法完成")
        if plan.dialog_detected:                    # 弹窗全周期监听: 本轮只处理弹窗
            target = str((plan.dialog_decision or {}).get("target") or "")
            count = dialog_seen.get(target, 0) + 1
            dialog_seen[target] = count
            if count >= _MAX_DIALOG_ONLY_CYCLES:
                raise ActError(
                    f"弹窗持续出现 {_MAX_DIALOG_ONLY_CYCLES} 轮仍未解决, 任务被阻塞: {target or '未知按钮'}"
                )
            _dispatch_dialog(device, image, plan, dialog_failures)
            continue
        if not plan.actions:
            raise ActError("规划器未给出任何动作且未标记结束")
        cycle_bboxes: list[list[int]] = []
        cycle_actions: list[dict[str, Any]] = []
        for action in plan.actions:
            data = _dispatch(device, action)
            history.append(action)
            # 采集 bbox (LocatedElement 有 .bbox)
            b = getattr(data, "bbox", None)
            if isinstance(b, list) and len(b) == 4:
                cycle_bboxes.append([int(v) for v in b])
            # 采集指令/点击坐标/错误 (报告指令面板用)
            cycle_actions.append({
                "action": dict(action),
                "click": list(data.action_point) if getattr(data, "action_point", None) else None,
                "error": None,
                "reason": plan.reason,
            })
            if action.get("type") == "query":
                observations.append({"query": action.get("query", ""), "data": data})
        if _cycle_bboxes is not None:
            _cycle_bboxes[-1] = cycle_bboxes        # 填充本轮 bbox (占位见循环开头)
        if _cycle_actions is not None:
            _cycle_actions[-1] = cycle_actions      # 填充本轮动作信息 (占位见循环开头)
    raise ActError(f"ai_act 超过重规划轮次上限 ({max_cycles}) 仍未完成")


# ---- 内部 ---------------------------------------------------------------


@dataclass
class _ActPlan:
    status: str
    actions: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    summary: str = ""
    dialog_detected: bool = False                   # 模态弹窗检测 (全周期监听)
    dialog_decision: dict[str, Any] | None = None   # 弹窗处理决策


def _plan_next(
    image: bytes,
    instruction: str,
    context: str,
    history: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> _ActPlan:
    prompt = _build_planner_prompt(instruction, context, history, observations)
    result = invoke_vision_llm(image_data_url=image_to_data_url(image), content=prompt)
    parsed = parse_json_loose(str(result.get("content") or ""))
    if not isinstance(parsed, dict):
        raise ActError(f"规划器返回非法 JSON: {parsed!r}")
    status = str(parsed.get("status") or "").strip().lower()
    if status not in ("continue", "finished", "failed"):
        raise ActError(f"规划器返回未知 status: {status!r}")
    raw_actions = parsed.get("actions")
    actions = (
        [a for a in raw_actions if isinstance(a, dict)] if isinstance(raw_actions, list) else []
    )
    raw_dialog = parsed.get("dialog_decision")
    return _ActPlan(
        status=status,
        actions=actions,
        reason=str(parsed.get("reason") or ""),
        summary=str(parsed.get("summary") or ""),
        dialog_detected=bool(parsed.get("dialog_detected", False)),
        dialog_decision=raw_dialog if isinstance(raw_dialog, dict) else None,
    )


def _dispatch(device: BaseDevice, action: dict[str, Any]) -> Any:
    action_type = action.get("type")
    if action_type == "tap":
        return executor.run_tap(device, str(action.get("locate", "")))
    if action_type == "double_click":
        return executor.run_double_click(device, str(action.get("locate", "")))
    if action_type == "right_click":
        return executor.run_right_click(device, str(action.get("locate", "")))
    if action_type == "input":
        return executor.run_input(
            device, str(action.get("locate", "")), str(action.get("value", ""))
        )
    if action_type == "clear":
        return executor.run_clear(device, str(action.get("locate", "")))
    if action_type == "keyboard_press":
        locate = str(action.get("locate", "")).strip()
        return executor.run_keyboard_press(
            device, str(action.get("key", "")), action_text=locate or None
        )
    if action_type == "scroll":
        return executor.run_scroll(device, str(action.get("direction") or "down"))
    if action_type == "swipe":
        return executor.run_swipe(device, str(action.get("direction") or "left"))
    if action_type == "back":
        return executor.run_back(device)
    if action_type == "query":
        return executor.run_query(device, str(action.get("query", ""))).data
    if action_type == "sleep":
        time.sleep(max(0.0, _as_float(action.get("seconds"), 1.0)))
        return None
    raise ActError(f"未知动作类型: {action_type!r}")


def _dispatch_dialog(
    device: BaseDevice,
    image: bytes,
    plan: _ActPlan,
    dialog_failures: dict[str, int],
) -> None:
    """执行弹窗处理决策 (全周期监听)。成功/安全跳过/危险拦截直接继续;
    同一弹窗连续处理失败达阈值抛 ActError (任务被弹窗阻塞视为失败)。
    纯执行逻辑复用 explore.execute_dialog_decision (内置黑名单拦截)。
    """
    error, finding, intercepted = execute_dialog_decision(device, image, plan.dialog_decision)
    target = str((plan.dialog_decision or {}).get("target") or "")
    if finding:
        logger.warning(f"ai_act 弹窗异常: {finding.get('description', '')}")
    if intercepted or error is None:                # 本轮处理完毕, 清零该弹窗失败计数
        dialog_failures.pop(target, None)
        return
    count = dialog_failures.get(target, 0) + 1
    dialog_failures[target] = count
    if count >= _DIALOG_FAIL_LIMIT:
        raise ActError(f"弹窗连续 {_DIALOG_FAIL_LIMIT} 轮处理失败, 任务被阻塞: {error}")


def _build_planner_prompt(
    instruction: str,
    context: str,
    history: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> str:
    parts = [
        "你是一个 UI 自动化规划器。你会看到当前界面截图, 需要规划完成目标的下一步操作。",
        f"\n【总目标】\n{instruction.strip()}",
    ]
    if context.strip():
        parts.append(f"\n【背景知识】\n{context.strip()}")
    if history:
        parts.append(
            "\n【已执行动作】\n"
            + json.dumps(history, ensure_ascii=False, default=str)
        )
    if observations:
        parts.append(
            "\n【已获取的页面数据】\n"
            + json.dumps(observations, ensure_ascii=False, default=str)
        )
    parts.append(
        "\n【可用动作】(只能使用以下类型; locate 用自然语言描述目标, 不要输出坐标)\n"
        '- {"type":"tap","locate":"要点击的元素"}\n'
        '- {"type":"double_click","locate":"要双击的元素"}\n'
        '- {"type":"right_click","locate":"要右键的元素"}\n'
        '- {"type":"input","locate":"输入框","value":"要输入的文本"}\n'
        '- {"type":"clear","locate":"要清空的输入框"}\n'
        '- {"type":"keyboard_press","key":"Enter","locate":"可选, 先定位再按键"}\n'
        '- {"type":"scroll","direction":"up|down|left|right"}\n'
        '- {"type":"swipe","direction":"left|right"}\n'
        '- {"type":"back"}  (返回上一页)\n'
        '- {"type":"query","query":"要从当前界面提取的数据需求"}\n'
        '- {"type":"sleep","seconds":2}'
    )
    parts.append(
        "\n【规划规则】\n"
        "1. 只规划到需要重新观察页面为止 (例如提交后要等结果, 就先用 sleep, 本轮到此)。\n"
        "2. 需要页面数据才能决策时, 先发 query, 下一轮根据【已获取的页面数据】再规划。\n"
        "3. 目标已达成时 status=finished; 数据类目标把最终结果写进 summary。\n"
        "4. 无法完成时 status=failed 并在 reason 说明原因。\n"
        "5. 弹窗优先处理: 界面被模态弹窗/对话框遮挡时, 本轮不执行 actions, 只输出弹窗处理方案:\n"
        "   - dialog_detected=true, dialog_decision 给处理方案: action 可选 close(关闭)/confirm"
        "(确认/同意)/cancel(取消)/skip(跳过不操作), target 为要点击的按钮文字 (locate 格式, 同 tap)\n"
        "   - 协议/条款/隐私政策/EULA 等同意类弹窗一律 action=confirm\n"
        "   - 删除/支付/退出登录等危险弹窗 action=skip, 在 anomaly 中说明原因\n"
        "   - 弹窗处理完后的下一轮再继续任务动作; 任务目标本身就在弹窗按钮上时直接用 "
        "dialog_decision 表达 (如目标按钮是'确定'则 action=confirm)\n"
    )
    parts.append(
        '\n只输出一个 JSON 对象: '
        '{"status":"continue|finished|failed","reason":"","summary":"",'
        '"dialog_detected":false,"dialog_decision":null 或 '
        '{"action":"close|confirm|cancel|skip","target":"按钮文字",'
        '"anomaly":"危险弹窗描述(仅skip时)"},"actions":[...]}。'
        "不要输出任何解释或多余文字。"
    )
    return "\n".join(parts)


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = ["run_act", "ActError"]
