"""ai_explore 自主探索 loop (loop-design.md §4 + Phase 2 接入)。

Phase 1 (已交付): 核心 loop + coverage 策略 + 危险目标防护 + 卡死/回环/逃逸自救
Phase 2 (本次接入):
  - memory_cache 持久化 (断点续探) 通过 agent.explore.memory
  - page_identity 双闸门 (URL+pHash+标题) 替换 Phase 1 轻量 page_key
  - locate_cache 三级命中 (native_ref / 缓存 bbox / VLM), 视觉校验为守门员
  - device.resolve_native_ref / rect_by_native_ref / navigate_back 协议已接在各设备
  - resumed/new_pages 两个返回字段真实填充

Phase 3 (本次接入): depth-first 策略 — 深度状态机 + 分叉点栈 + max_depth 围栏 + exhausted 框架复核 (见 loop-design.md 3.3);
  breadth-first / random 仍待做; memory_cache 传 None 时完全不落盘, 与 Phase 1 行为一致。
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from tisui.agent import executor
from tisui.agent.explore import memory as _memory_mod
from tisui.agent.explore.locate_cache import LocateCacheStore
from tisui.agent.explore.memory_store import MemoryStoreError
from tisui.agent.explore.page_identity import (
    BBox,
    PageRegistry,
    identify_page,
    registry_from_json,
    registry_to_json,
)
from tisui.agent.explore.prompts import (
    ExploreDecision,
    EndConditionSpec,
    build_explore_prompt,
    match_forbidden,
    merge_forbidden,
    parse_end_condition,
    parse_explore_reply,
)
from tisui.agent.vision_io import image_to_data_url
from tisui.device.base import BaseDevice
from tisui.shared.config import settings
from tisui.shared.logger import logger
from tisui.shared.models.invoker import invoke_vision_llm

_SAFE_INPUT_VALUE = "test123"          # input 内容兜底: 优先用 VLM 生成的 value, 未提供时用此默认值
_DEAD_AFTER_INVALID = 2                # 同一元素连续无效次数 -> 死元素
_LOOP_WINDOW = 6                       # 回环检测窗口 (最近 N 次页面转移)
_LOOP_REPEAT = 3                       # 窗口内同一转移出现次数 -> 强制换目标
_MAX_CONSECUTIVE_FAILURES = 5          # 连续失败轮数 -> failed
# 定位型动作: 有 locate 目标, 参与黑名单拦截/交互记录/定位缓存命中 (见 4.6/4.7)
_LOCATE_ACTIONS = ("tap", "input", "double_click", "right_click", "clear")
_RESULT_CHECKED_ACTIONS = ("tap", "input", "double_click", "right_click", "clear", "scroll", "swipe", "back")  # 动作后需截图比对"页面是否变化"的动作 (见 4.7)
_NEUTRAL_ACTIONS = ("sleep", "query", "keyboard_press")  # 中性动作: 不计失败也不清零, 防 VLM 交替动作绕过失败判定
_MAX_ESCAPE_RECOVERIES = 3             # 应用逃逸连续恢复失败次数 -> failed
_MAX_SUB_FRAMES = 60                   # 报告子截图帧数上限, 超出均匀抽稀 (见 6.2)
_VLM_BBOX_GRID = 1000                  # Qwen-VL 系列 bbox: 0-1000 归一化网格, 与输入尺寸无关
_DIALOG_FAIL_LIMIT = 2                 # 同一弹窗连续处理失败次数 -> 记 anomaly 跳过
_MAX_DIALOG_ONLY_CYCLES = 10           # 连续纯弹窗轮数上限 -> failed (防止卡在弹窗循环)


class ExploreError(RuntimeError):
    """ai_explore 无法启动或不可恢复的失败 (memory_cache 锁冲突等)。"""


@dataclass
class ExploreFinding:
    id: str
    type: str                          # element | page | anomaly | data
    description: str
    page_id: str
    screenshot_id: str = ""
    occurrences: int = 1
    data: Any = None


@dataclass
class ExploreNode:
    step_id: str
    action: str
    target: str
    from_page_id: str
    to_page_id: str
    is_new_page: bool
    depth: int = 0                     # 本动作执行前的页面深度 (见 loop-design.md 3.3; 旧记录默认 0)
    findings: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    error: str | None = None


@dataclass
class BranchPoint:
    """分叉点 (depth-first, 见 loop-design.md 3.3)。剩余未访问元素数实时从页面状态计算。"""

    page_id: str
    depth: int


@dataclass
class ExploreCoverage:
    pages_visited: int = 0
    elements_interacted: int = 0
    total_findings: int = 0
    anomalies: int = 0


@dataclass
class ExploreResult:
    status: str                        # completed | exhausted | timeout | cycle_exceeded | failed
    end_condition_met: bool
    total_cycles: int
    duration_ms: float
    findings: list[ExploreFinding]
    path: list[ExploreNode]
    coverage: ExploreCoverage
    token_usage: dict[str, int]
    resumed: bool = False
    new_pages: int = 0
    error: str | None = None


def execute_dialog_decision(
    device: BaseDevice,
    image: bytes,
    dialog_decision: dict[str, Any] | None,
    *,
    forbidden: list[str] | None = None,
) -> tuple[str | None, dict[str, Any] | None, bool]:
    """执行弹窗决策并返回 (error, finding, intercepted)。

    - error:    None=处理完毕(或无弹窗), str=处理失败的描述
    - finding:  dialog_decision.anomaly (危险弹窗) 会包装为 finding dict
    - intercepted: True=命中 forbidden 黑名单, 出于安全跳过了点击

    forbidden 双保险只拦截 tap/input; skip 类永远合法通过。
    此函数供 explore (循环内) 与 ai_act (全周期弹窗监听) 共享, 不写 explore state。
    """
    if not isinstance(dialog_decision, dict) or not dialog_decision:
        return None, None, False
    action = str(dialog_decision.get("action") or "").strip().lower()
    target = str(dialog_decision.get("target") or "").strip()
    anomaly = str(dialog_decision.get("anomaly") or "").strip()
    finding: dict[str, Any] | None = {"type": "anomaly", "description": anomaly} if anomaly else None

    if action in ("skip", ""):
        return None, finding, False

    if action not in ("close", "confirm", "cancel"):
        return f"未知弹窗决策 action: {action!r}", finding, False

    forbidden_all = merge_forbidden(forbidden) if forbidden else []
    hit = match_forbidden(target, forbidden_all)
    if hit:
        logger.warning(f"弹窗目标命中黑名单: {target!r} -> {hit!r} (已拦截)")
        return f"forbidden-hit: {hit}", finding, True

    def _click_by_bbox(bbox_raw: Any, desc: str) -> str | None:
        bb = _as_bbox(bbox_raw)
        if bb is None:
            try:
                executor.run_tap(device, desc)
                return None
            except Exception as exc:  # noqa: BLE001
                return f"{type(exc).__name__}: {exc}"
        pt = _bbox_point(bbox_raw, image)
        if pt is None:
            try:
                executor.run_tap(device, desc)
                return None
            except Exception as exc:  # noqa: BLE001
                return f"{type(exc).__name__}: {exc}"
        try:
            device.click(pt)
            time.sleep(executor.DEFAULT_WAIT_AFTER_ACTION)
            return None
        except Exception as exc:  # noqa: BLE001
            return f"{type(exc).__name__}: {exc}"

    checks = dialog_decision.get("check_first") or []
    if isinstance(checks, list):
        for idx, ck in enumerate(checks):
            if not isinstance(ck, dict):
                continue
            label = str(ck.get("label") or "").strip()
            if not label:
                continue
            ck_hit = match_forbidden(label, forbidden_all)
            if ck_hit:
                logger.warning(f"弹窗复选框命中黑名单: {label!r} -> {ck_hit!r} (跳过)")
                continue
            err = _click_by_bbox(ck.get("bbox"), label)
            if err is not None:
                return f"check_first[{idx}] {label!r} 失败: {err}", finding, False

    bbox_raw = dialog_decision.get("bbox")
    desc = target or f"弹窗按钮 {action}"
    main_err = _click_by_bbox(bbox_raw, desc)
    if main_err is not None:
        return f"点击弹窗按钮 {desc!r} 失败: {main_err}", finding, False
    return None, finding, False


def run_explore(
    device: BaseDevice,
    goal: str,
    *,
    end_condition: str = "",
    strategy: str = "coverage",
    max_cycles: int | None = None,
    total_timeout: float | None = None,
    max_tokens: int | None = None,
    context: str = "",
    forbidden: list[str] | None = None,
    backtrack: bool = True,
    max_depth: int | None = None,
    memory_cache: str | None = None,
    reset_memory: bool = False,
    _cycle_screenshots: list[bytes] | None = None,
    _cycle_bboxes: list[list[list[int]]] | None = None,
    _cycle_actions: list[dict[str, Any]] | None = None,
) -> ExploreResult:
    """自主探索入口。终止: completed / exhausted / timeout / cycle_exceeded / failed。

    参数优先级: 显式参数 > config.yaml explore 节 > 内置默认值。
    max_depth: 最大探索深度 (页面跳转层级), None 不限制; 当前深度达上限时
    不再进入新页面, 只探索本页元素或回溯 (深度定义与围栏见 loop-design.md 3.3)。
    _cycle_screenshots: 报告采集用, 每轮截图追加进该列表 (超上限自动抽稀)。
    _cycle_bboxes: 报告采集用, 每轮 VLM 识别的控件 bbox (原图像素坐标) 追加进该列表,
                   与 _cycle_screenshots 一一对应 (无识别结果轮为空组)。
    _cycle_actions: 报告采集用, 每轮动作执行信息追加进该列表 (与截图一一对应):
                    {"action": 本轮指令, "click": 实际点击坐标或 None, "error": 执行错误或 None}。
    """
    if not str(goal).strip():
        raise ExploreError("goal 不能为空")
    if strategy not in ("coverage", "depth-first"):
        raise ExploreError(f"当前支持 coverage / depth-first 策略 (breadth-first/random 待做), 收到: {strategy!r}")
    if strategy == "depth-first" and not backtrack:
        raise ExploreError("depth-first 策略依赖回溯 (back), 请设置 backtrack=True")

    explore_config = settings.explore_config
    cycles_cap = max(1, max_cycles if max_cycles is not None else explore_config.max_cycles)
    budget = total_timeout if total_timeout is not None else explore_config.total_timeout
    depth_cap = max_depth if max_depth is not None else explore_config.max_depth
    if depth_cap is not None:
        depth_cap = max(1, depth_cap)
    deadline = time.monotonic() + max(0.0, budget)
    forbidden_all = merge_forbidden(forbidden)
    # Phase 4: end_condition 客观子条件解析 (见 4.5; 空 spec = 纯 VLM 判定)
    cond_spec = parse_end_condition(end_condition)

    # ---------- Phase 2: memory_cache 打开 (locate_cache 暂关闭) ----------
    mem_store, snapshot, session_id = None, None, ""
    resumed = False
    try:
        if memory_cache is not None and str(memory_cache).strip():
            mem_store, snapshot, session_id = _memory_mod.open_memory(
                str(memory_cache).strip(), reset=reset_memory,
            )
            resumed = snapshot is not None
    except MemoryStoreError as exc:
        raise ExploreError(str(exc)) from exc
    # 定位缓存暂关闭: 缓存内 bbox 需与 VLM 0-1000 网格坐标换算保持一致, 该块历史版本
    # 混入过错误坐标 (见 _to_native_bbox 换算修复), 先整体禁用稳妥验证, 稳定后再恢复。
    locate_store = LocateCacheStore(None)

    try:
        state = _State()
        if snapshot is not None:
            _hydrate_from_snapshot(state, snapshot)
        base_page_count = len(state.page_registry)
        started = time.perf_counter()
        status, error, end_met = "cycle_exceeded", None, False

        for cycle in range(1, cycles_cap + 1):
            if time.monotonic() >= deadline:
                status, error = "timeout", f"超过总时长上限 ({budget}s)"
                break
            if max_tokens is not None and state.tokens.get("total_tokens", 0) >= max_tokens:
                status, error = "exhausted", f"token 预算耗尽 (≥{max_tokens})"
                break

            # 前台保障前置 (loop-design §4.7): 失焦/逃逸检测必须在截图之前,
            # 否则失焦时截图无效 (截到遮挡窗口/桌面), VLM 基于错误输入决策
            _check_escape_and_windows(device, state)
            if state.escape_failures >= _MAX_ESCAPE_RECOVERIES:
                status, error = "failed", "应用逃逸/失焦后连续恢复失败"
                break

            image = device.screenshot()
            if _cycle_screenshots is not None:
                _cycle_screenshots.append(image)
            if _cycle_bboxes is not None:
                # 本轮占位: 动作执行后填充 (成功轮用实际执行 bbox, 见 _collect_cycle_bboxes)
                _cycle_bboxes.append([])
            if _cycle_actions is not None:
                _cycle_actions.append({})   # 本轮占位: 动作执行后填充

            # Phase 2: 双闸门页面身份 (前一轮 VLM 给的 stable regions 列表缓存使用)
            stable_bboxes = _stable_bboxes_of(state.last_observed_regions) if state.last_observed_regions else ()
            page_id, is_new = identify_page(
                state.page_registry,
                url=_current_url(device),
                title_from_vlm=state.current_page_title,
                image_bytes=image,
                stable_bboxes=stable_bboxes,
            )

            # ---- Phase 4: end_condition 框架客观判定 ① 轮首检查 (见 4.5) ----
            # identify 后、VLM 决策前: 条件已满足 (如断点续探恢复场景) → 立即收尾省一次 VLM 调用
            if cond_spec.has_objective() and not _condition_gaps(state, cond_spec):
                node = state.add_node(cycle, "completed", "框架条件满足",
                                      page_id, page_id, False, depth=state.current_depth)
                _memory_mod.append_path_node(mem_store, _node_to_dict(node, cycle), session_id)
                status, end_met = "completed", True
                _snapshot_if_needed(mem_store, state, cycle, session_id=session_id)
                break

            try:
                decision = _plan(
                    image, state, page_id, is_new,
                    goal=goal, end_condition=end_condition, strategy=strategy,
                    context=context, forbidden=forbidden_all, backtrack=backtrack,
                    max_depth=depth_cap,
                )
            except ValueError as exc:
                state.consecutive_failures += 1
                node = state.add_node(cycle, "plan", "", page_id, page_id, False, error=str(exc))
                _memory_mod.append_path_node(mem_store, _node_to_dict(node, cycle), session_id)
                _snapshot_if_needed(mem_store, state, cycle, session_id=session_id)
                if state.consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                    status, error = "failed", f"连续 {_MAX_CONSECUTIVE_FAILURES} 轮失败: {exc}"
                    break
                continue

            if _cycle_bboxes is not None:
                # 填充本轮识别框: action.bbox + regions bbox + 弹窗按钮 bbox (均换算为原图像素)
                _cycle_bboxes[-1] = _collect_cycle_bboxes(image, decision)

            state.observe(page_id, decision)
            _collect_finding(state, page_id, decision.new_finding)

            # ---- depth-first 深度状态机 + max_depth 围栏 (见 3.3) ----
            # 转移判定跨轮: 上一轮动作后已换页 (from!=to) 或本轮识别页面不同即视为转移;
            # 原生设备无 URL 快速匹配, after_action 不产生转移, 只能靠本轮 page_id 判定;
            # back 动作单独降深度。围栏: 转移后新深度超上限 → 记 finding + 立即 back 恢复。
            prev_node = state.path[-1] if state.path else None
            if prev_node is not None:
                prev_action = str(prev_node.action or "")
                if prev_action == "back":
                    state.current_depth = max(0, state.current_depth - 1)
                elif prev_node.from_page_id != prev_node.to_page_id or page_id != prev_node.to_page_id:
                    state.current_depth += 1
                    if depth_cap is not None and state.current_depth > depth_cap:
                        # 不钳制 depth: 保留实际深度, 围栏 back 恢复轮按 back 语义减 1 自然回到 cap
                        _collect_finding(state, page_id, {
                            "type": "page", "description": f"深度上限 {depth_cap} 截断, 自动返回",
                        })
                        try:
                            executor.run_back(device)
                        except Exception:  # noqa: BLE001 - 围栏返回失败不终止探索, 下轮重试
                            pass
                        node = state.add_node(
                            cycle, "back", "深度围栏恢复", prev_node.to_page_id, page_id,
                            page_id not in state.seen_before,
                            error=f"深度上限 {depth_cap} 截断", depth=state.current_depth,
                        )
                        _memory_mod.append_path_node(mem_store, _node_to_dict(node, cycle), session_id)
                        _snapshot_if_needed(mem_store, state, cycle, session_id=session_id)
                        continue
                state.update_branch_points(prev_node.to_page_id, page_id, prev_action)

            # depth-first 专属: exhausted 框架复核 (分叉点栈/本页未访问是框架侧客观状态, 见 3.3)
            if (
                strategy == "depth-first"
                and decision.status == "exhausted"
                and (state.branch_points or state.unvisited_of(page_id) > 0)
            ):
                state.exhausted_override = True
                node = state.add_node(
                    cycle, "plan", "exhausted 复核拒绝", page_id, page_id, False,
                    error=f"仍有 {len(state.branch_points)} 个分叉点未探索",
                )
                _memory_mod.append_path_node(mem_store, _node_to_dict(node, cycle), session_id)
                _snapshot_if_needed(mem_store, state, cycle, session_id=session_id)
                continue

            # Phase 4: completed 后置复核 (见 4.5) — VLM 报 completed 但客观子条件未满足 → 拒绝
            if decision.status == "completed" and cond_spec.has_objective():
                gaps = _condition_gaps(state, cond_spec)
                if gaps:
                    state.completed_override = True
                    node = state.add_node(
                        cycle, "plan", "completed 复核拒绝", page_id, page_id, False,
                        error="; ".join(gaps),
                    )
                    _memory_mod.append_path_node(mem_store, _node_to_dict(node, cycle), session_id)
                    _snapshot_if_needed(mem_store, state, cycle, session_id=session_id)
                    continue

            if decision.status in ("completed", "exhausted"):
                status = decision.status
                end_met = decision.status == "completed"
                node = state.add_node(cycle, decision.status, "", page_id, page_id, False,
                                      depth=state.current_depth)
                _memory_mod.append_path_node(mem_store, _node_to_dict(node, cycle), session_id)
                break

            # ---------- Phase 2: 弹窗优先处理 (在普通 action 之前) ----------
            dialog_error, dialog_finding, dialog_intercepted = None, None, False
            dialog_node_action = ""
            if decision.dialog_detected and decision.dialog_decision:
                dialog_error, dialog_finding, dialog_intercepted = execute_dialog_decision(
                    device, image, decision.dialog_decision, forbidden=forbidden_all,
                )
                dlg = decision.dialog_decision or {}
                dialog_node_action = f"dialog:{str(dlg.get('action') or '')}"
                if dialog_finding:
                    _collect_finding(state, page_id, dialog_finding)
                dialog_target = str((decision.dialog_decision or {}).get("target") or "")
                if dialog_intercepted or dialog_error is None:
                    state.dialog_failures.pop(dialog_target, None)
                else:
                    state.dialog_failures[dialog_target] = state.dialog_failures.get(dialog_target, 0) + 1
                    if state.dialog_failures[dialog_target] >= _DIALOG_FAIL_LIMIT:
                        state.dialog_failures.pop(dialog_target, None)
                        logger.warning(f"弹窗连续 {_DIALOG_FAIL_LIMIT} 轮失败, 跳过: {dialog_target!r} ({dialog_error})")
                        dialog_error = None

            action_blank = not str(decision.action.get("type") or "").strip()
            if decision.dialog_detected and action_blank:
                state.dialog_only_cycles += 1
                if state.dialog_only_cycles >= _MAX_DIALOG_ONLY_CYCLES:
                    status, error = "failed", f"连续 {_MAX_DIALOG_ONLY_CYCLES} 轮仅处理弹窗, 疑似卡在弹窗循环"
                    break
            else:
                state.dialog_only_cycles = 0

            if decision.dialog_detected and decision.dialog_decision and action_blank:
                node_error = dialog_error
                exec_bbox: list[int] | None = None   # 弹窗轮无动作执行 bbox
                click_pt: list[int] | None = None
            else:
                node_error, exec_bbox, click_pt = _execute(
                    device, image, state, locate_store,
                    page_id, decision, forbidden_all,
                )
                if node_error is None and dialog_error is not None and dialog_node_action:
                    node_error = f"弹窗处理: {dialog_error}"

            after = device.screenshot()
            if _cycle_bboxes is not None:
                # 填充本轮框: 动作成功轮优先用实际执行 bbox (多次尝试时取执行成功那次),
                # 失败/无执行结果轮用 VLM 识别框; 均换算为原图像素
                _cycle_bboxes[-1] = _collect_cycle_bboxes(image, decision, exec_bbox)
            if _cycle_actions is not None:
                # 填充本轮动作信息: 指令 + 实际点击坐标 + 执行错误 + 决策说明
                # (报告指令面板用); 弹窗轮无普通 action, 用 dialog_decision 包装为指令
                action_info = dict(decision.action or {})
                if not action_info and decision.dialog_detected and decision.dialog_decision:
                    dlg = decision.dialog_decision
                    action_info = {
                        "type": f"dialog:{str(dlg.get('action') or '')}",
                        "locate": str(dlg.get("target") or ""),
                    }
                    if dlg.get("anomaly"):
                        action_info["anomaly"] = dlg["anomaly"]
                _cycle_actions[-1] = {
                    "action": action_info,
                    "click": click_pt,
                    "error": node_error,
                    "reason": decision.reason,
                }
            to_key, moved = state.after_action(device, image, after, page_id, decision)
            action_type_label = dialog_node_action or str(decision.action.get("type") or "")
            action_locate_label = (
                str(decision.action.get("locate") or decision.action.get("query") or "")
                if not dialog_node_action else str((decision.dialog_decision or {}).get("target") or "")
            )
            node = state.add_node(
                cycle,
                action_type_label,
                action_locate_label,
                page_id, to_key, to_key not in state.seen_before,
                error=node_error, depth=state.current_depth,
            )
            _memory_mod.append_path_node(mem_store, _node_to_dict(node, cycle), session_id)
            state.settle_cycle(page_id, decision, moved=moved, failed=node_error is not None, locate_store=locate_store)
            _snapshot_if_needed(mem_store, state, cycle, session_id=session_id)

            # ---- Phase 4: end_condition 框架客观判定 ② 动作后检查 (见 4.5) ----
            # settle 后: 动作刚使条件满足 → 当轮立即收尾, 不等下一轮 VLM 决策 (消除滞后一拍)
            if cond_spec.has_objective() and not _condition_gaps(state, cond_spec):
                node = state.add_node(cycle, "completed", "框架条件满足",
                                      page_id, to_key, to_key not in state.seen_before,
                                      depth=state.current_depth, step_suffix="-cond")
                _memory_mod.append_path_node(mem_store, _node_to_dict(node, cycle), session_id)
                status, end_met = "completed", True
                _snapshot_if_needed(mem_store, state, cycle, session_id=session_id)
                break

            if state.consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                status, error = "failed", f"连续 {_MAX_CONSECUTIVE_FAILURES} 轮动作失败或无效"
                break

        # 循环结束: 强制写快照 + findings.json
        _snapshot_if_needed(mem_store, state, cycles_cap + 1, force=True,
                            path_override=len(state.path), session_id=session_id)
    finally:
        locate_store.close()
        _memory_mod.close_memory(mem_store)

    duration_ms = (time.perf_counter() - started) * 1000
    if _cycle_screenshots is not None:
        # 抽稀截图时同步抽稀 bbox/action 列表, 保证三列表与帧一一对应
        _thin_frames(_cycle_screenshots)
        if _cycle_bboxes is not None:
            _thin_frames(_cycle_bboxes)
        if _cycle_actions is not None:
            _thin_frames(_cycle_actions)
    new_pages_count = max(0, len(state.page_registry) - base_page_count)
    return ExploreResult(
        status=status,
        end_condition_met=end_met,
        total_cycles=len(state.path),
        duration_ms=duration_ms,
        findings=state.findings,
        path=state.path,
        coverage=state.coverage(),
        token_usage=dict(state.tokens),
        resumed=resumed,
        new_pages=new_pages_count,
        error=error,
    )


# ---- 内部: 状态 ----------------------------------------------------------


@dataclass
class _PageInfo:
    page_id: str
    title: str = ""
    url: str | None = None
    elements: list[str] = field(default_factory=list)
    interacted: set[str] = field(default_factory=set)
    discovered_at: str = ""


class _State:
    """运行时状态 + page_registry (Phase 2 持久化镜像由 memory 模块读写)。"""

    def __init__(self) -> None:
        self.page_registry: PageRegistry = PageRegistry()
        self.pages: dict[str, _PageInfo] = {}
        self.path: list[ExploreNode] = []
        self.findings: list[ExploreFinding] = []
        self.suspected: dict[tuple[str, str], ExploreFinding] = {}   # anomaly 二次确认暂存
        self.dead: set[tuple[str, str]] = set()
        self.invalid_count: dict[tuple[str, str], int] = {}
        self.retry_full: set[tuple[str, str]] = set()                # bbox 点偏 → 下次走完整 locate
        self.transitions: list[tuple[str, str]] = []
        self.tokens: dict[str, int] = {}
        self.consecutive_failures = 0
        self.escape_failures = 0
        self.seen_before: set[str] = set()
        self.allowed_domains: set[str] = set()
        self._current_key = ""
        self.dialog_failures: dict[str, int] = {}                    # 弹窗指纹 -> 连续失败次数
        self.dialog_only_cycles = 0                                  # 连续纯弹窗轮数
        self.current_page_title: str = ""                            # 上一轮 VLM 给的 page_title (identify_page 用)
        self.last_observed_regions: list[dict[str, Any]] = []        # 上一轮 VLM 给的 regions (stable 区 bbox 传 identify_page)
        self.branch_points: list[BranchPoint] = []                   # 分叉点栈 (depth-first, 见 3.3)
        self.current_depth = 0                                       # 当前页面深度 (起点页 0, 见 3.3)
        self.exhausted_override = False                              # 上轮 exhausted 被框架复核拒绝 (下轮注入提示)
        self.completed_override = False                              # 上轮 completed 被框架复核拒绝 (下轮注入提示)

    # -- 页面进出 --
    def enter_page(self, device: BaseDevice, image: bytes) -> tuple[str, bool]:
        """保留 Phase 1 接口兼容 (仅 _check_escape 之前未调用, 已废弃)。"""
        raise RuntimeError("_State.enter_page 已被 identify_page 替换 (Phase 2)")

    def observe(self, page_key: str, decision: ExploreDecision) -> None:
        page = self._ensure_page(page_key)
        if decision.page_title:
            page.title = decision.page_title
            self.current_page_title = decision.page_title
        self.last_observed_regions = list(decision.regions or [])
        for name in decision.elements:
            if name not in page.elements:
                page.elements.append(name)

    def after_action(
        self, device: BaseDevice, before: bytes, after: bytes, from_key: str, decision: ExploreDecision
    ) -> tuple[str, bool]:
        moved = _dhash(before) != _dhash(after)
        if not moved:
            return from_key, False
        # 页面视觉变化 → 下一轮 identify_page 会重新匹配双闸门, 这里先保留 from_key
        to_key = from_key
        # 下一轮 plan 之前用新截图 + 最新标题/VLM regions 再匹配, 先保守从 registry 里 URL/Web 方式尝试
        url = _current_url(device)
        if url:
            # Web: URL 变了肯定换页; 用 URL 快速匹配, 找得到就复用 page_id, 找不到下一轮 identify_page 会新建
            from tisui.agent.explore import page_identity as _pid  # 仅用 normalize_url
            norm = _pid.normalize_url(url)
            for fp in self.page_registry:
                if fp.url and _pid.normalize_url(fp.url) == norm:
                    to_key = fp.page_id
                    break
        if to_key != from_key:
            self.transitions.append((from_key, to_key))
            self.transitions = self.transitions[-_LOOP_WINDOW:]
        return to_key, moved

    def settle_cycle(
        self, page_key: str, decision: ExploreDecision, *, moved: bool, failed: bool,
        locate_store: LocateCacheStore | None = None,
    ) -> None:
        target = str(decision.action.get("locate") or "").strip()
        action_type = str(decision.action.get("type") or "")
        if target and action_type in _LOCATE_ACTIONS:
            page = self._ensure_page(page_key)
            page.interacted.add(target)
            key = (page_key, target)
            # 定位型动作统一: 执行异常或页面无变化都算无效 (点偏同样计入)
            if failed or not moved:
                self.invalid_count[key] = self.invalid_count.get(key, 0) + 1
                self.retry_full.add(key)
                if locate_store is not None:
                    locate_store.evict_element(page_key, target)
                if self.invalid_count[key] >= _DEAD_AFTER_INVALID:
                    self.dead.add(key)
            else:
                self.invalid_count.pop(key, None)
                self.retry_full.discard(key)
        if failed or (action_type in _RESULT_CHECKED_ACTIONS and not moved):
            # 失败或动作后页面无变化 (tap/input 点偏、scroll 到边界仍滚动、back 无效) 都计入失败
            self.consecutive_failures += 1
        elif action_type in _NEUTRAL_ACTIONS:
            pass                              # 中性轮: 不清零不计数, 防止 VLM 用 sleep/query 交替清零绕过
        else:
            self.consecutive_failures = 0     # 成功且有页面变化 (或弹窗处理轮) -> 清零
        self.seen_before = {fp.page_id for fp in self.page_registry}

    # -- 检测与汇总 --
    def loop_detected(self) -> bool:
        if len(self.transitions) < _LOOP_REPEAT:
            return False
        recent = self.transitions[-_LOOP_WINDOW:]
        return any(recent.count(pair) >= _LOOP_REPEAT for pair in set(recent))

    def add_node(
        self, cycle: int, action: str, target: str,
        from_key: str, to_key: str, is_new: bool, *,
        error: str | None = None, depth: int = 0, step_suffix: str = "",
    ) -> ExploreNode:
        node = ExploreNode(
            step_id=f"explore_{cycle:03d}{step_suffix}", action=action, target=target,
            from_page_id=from_key, to_page_id=to_key, is_new_page=is_new,
            depth=depth, error=error,
        )
        self.path.append(node)
        return node

    def unvisited_of(self, page_id: str) -> int:
        """页面剩余未访问元素数 (分叉点实时计算来源, 见 3.3)。"""
        page = self.pages.get(page_id)
        if page is None:
            return 0
        return max(0, len(page.elements) - len(page.interacted))

    def update_branch_points(self, from_key: str, to_key: str, action_type: str) -> None:
        """动作后同步分叉点栈 (depth-first, 见 loop-design.md 3.3)。

        进入新页面且该页有未访问元素 → 压栈 (同一 page_id 只保留一条, 重复进入更新 depth);
        back → 弹出深度大于当前深度的记录; 任何情况清理已无未访问元素的分叉点。
        本方法在 current_depth 更新之后调用, 栈内 depth 即所在页面的实际层级。
        """
        if action_type == "back":
            self.branch_points = [b for b in self.branch_points if b.depth <= self.current_depth]
        elif to_key != from_key and self.unvisited_of(to_key) > 0:
            for bp in self.branch_points:
                if bp.page_id == to_key:
                    bp.depth = self.current_depth
                    break
            else:
                self.branch_points.append(BranchPoint(page_id=to_key, depth=self.current_depth))
        self.branch_points = [b for b in self.branch_points if self.unvisited_of(b.page_id) > 0]

    def add_tokens(self, usage: dict[str, Any]) -> None:
        for key, value in (usage or {}).items():
            if isinstance(value, (int, float)):
                self.tokens[key] = self.tokens.get(key, 0) + int(value)

    def coverage(self) -> ExploreCoverage:
        return ExploreCoverage(
            pages_visited=len(self.page_registry),
            elements_interacted=sum(len(p.interacted) for p in self.pages.values()),
            total_findings=len(self.findings),
            anomalies=sum(1 for f in self.findings if f.type == "anomaly"),
        )

    def _ensure_page(self, page_id: str) -> _PageInfo:
        if page_id not in self.pages:
            # 从 page_registry 拿标题/URL 作为初始值
            title = ""; url_val = None
            fp = self.page_registry.get(page_id)
            if fp is not None:
                title = fp.title
                url_val = fp.url
            self.pages[page_id] = _PageInfo(page_id=page_id, title=title, url=url_val,
                                             discovered_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        return self.pages[page_id]


def _stable_bboxes_of(regions: list[dict[str, Any]]) -> tuple[BBox, ...]:
    """从 VLM 观察输出的 regions 中挑 stability='stable' 的 bbox 给 identify_page 拼指纹。"""
    out: list[BBox] = []
    for r in regions or []:
        if str(r.get("stability") or "").lower() != "stable":
            continue
        bb = r.get("bbox")
        if isinstance(bb, (list, tuple)) and len(bb) == 4:
            try:
                out.append((int(bb[0]), int(bb[1]), int(bb[2]), int(bb[3])))
            except (TypeError, ValueError):
                continue
    return tuple(out)


# ---- 内部: end_condition 框架客观判定 (见 4.5) ---------------------------


# 可数对象 -> 当前计数取值 (与 parse_end_condition 的映射对齐)
_COUNT_SOURCES = {
    "pages": lambda s: len(s.page_registry),
    "findings": lambda s: len(s.findings),
    "data_findings": lambda s: sum(1 for f in s.findings if f.type == "data"),
    "elements": lambda s: sum(len(p.interacted) for p in s.pages.values()),
}


def _condition_gaps(state: "_State", spec: EndConditionSpec) -> list[str]:
    """返回未满足的客观子条件原因列表; 空列表表示全部满足 (见 4.5)。"""
    gaps: list[str] = []
    for obj, target in spec.thresholds.items():
        count = _COUNT_SOURCES.get(obj, lambda _s: 0)(state)
        if count < target:
            gaps.append(f"{obj} 仅 {count}/{target}")
    if spec.keywords:
        haystack = " ".join(
            [str(n.target or "") for n in state.path]
            + [str(p.title or "") for p in state.pages.values()]
            + [str(f.description or "") for f in state.findings]
        )
        for kw in spec.keywords:
            if kw not in haystack:
                gaps.append(f"关键词 {kw!r} 未出现")
    return gaps


# ---- 内部: 规划与执行 -----------------------------------------------------


def _plan(
    image: bytes, state: _State, page_key: str, is_new: bool, *,
    goal: str, end_condition: str, strategy: str, context: str,
    forbidden: list[str], backtrack: bool, max_depth: int | None = None,
) -> ExploreDecision:
    page = state._ensure_page(page_key)
    dead_names = {t for (p, t) in state.dead if p == page_key}
    visited_summary = []
    count = 0
    for fp in list(state.page_registry)[-10:]:
        pinfo = state.pages.get(fp.page_id)
        title = fp.title or fp.page_id
        if pinfo:
            total = len(pinfo.elements) or "?"
            visited_summary.append(f"{title} → 已交互 {len(pinfo.interacted)}/{total} 个元素")
        else:
            visited_summary.append(f"{title} → 已进入")
        count += 1
        if count >= 10:
            break
    recent_ops = [
        f"{n.step_id}: {n.action} \"{n.target}\" → {n.to_page_id}"
        + (" (新页面)" if n.is_new_page else "") + (f" [失败: {n.error}]" if n.error else "")
        for n in state.path[-5:]
    ]
    branch_summary: list[str] = []
    if strategy == "depth-first":
        for bp in state.branch_points:
            pinfo = state.pages.get(bp.page_id)
            title = pinfo.title if pinfo and pinfo.title else bp.page_id
            branch_summary.append(f"{title} (剩 {state.unvisited_of(bp.page_id)} 个元素)")
    prompt = build_explore_prompt(
        goal=goal, end_condition=end_condition, strategy=strategy, context=context,
        page_key=page.title or page_key, is_new_page=is_new,
        known_elements=page.elements, interacted=page.interacted, dead_elements=dead_names,
        visited_summary=visited_summary, recent_ops=recent_ops, forbidden=forbidden,
        findings_count=len(state.findings), force_change_target=state.loop_detected(),
        backtrack=backtrack,
        current_depth=state.current_depth, max_depth=max_depth,
        branch_summary=branch_summary, exhausted_override=state.exhausted_override,
        completed_override=state.completed_override,
    )
    result = invoke_vision_llm(image_data_url=image_to_data_url(image), content=prompt)
    state.add_tokens(result.get("usage") or {})
    return parse_explore_reply(str(result.get("content") or ""))


def _execute(
    device: BaseDevice, image: bytes, state: _State, locate_store: LocateCacheStore,
    page_id: str, decision: ExploreDecision, forbidden: list[str],
) -> tuple[str | None, list[int] | None, list[int] | None]:
    """执行单轮动作; 返回 (错误消息, 动作实际执行 bbox, 实际点击坐标)。

    错误消息 None=成功。exec_bbox: tap/input 成功时本次动作实际执行的元素框
    (locate_cache 实时校验框 / 定位管线结果框 / VLM 框兜底), 供报告框选;
    click_pt: 实际点击坐标 (报告指令面板显示), 无 bbox 概念的动作返回 None。
    危险目标在此二次拦截 (见 4.6)。
    """
    action = decision.action
    action_type = str(action.get("type") or "").strip().lower()
    target = str(action.get("locate") or "").strip()

    hit = match_forbidden(target, forbidden)
    if hit and action_type in _LOCATE_ACTIONS:
        logger.warning(f"探索拦截危险目标 (forbidden-hit): {target!r} 命中 {hit!r}")
        state.dead.add((page_id, target))
        return f"forbidden-hit: {hit}", None, None

    try:
        if action_type in _LOCATE_ACTIONS:
            # Phase 2: 先走 locate_cache 三级命中 (视觉校验内置于 try_locate)
            pt = None
            exec_bbox: list[int] | None = None
            bbox_raw = action.get("bbox")
            if (page_id, target) not in state.retry_full:
                hit_result = locate_store.try_locate(
                    device, image, page_id=page_id, element_desc=target,
                    regions_from_vlm=_to_native_regions(decision.regions or [], image),
                )
                if hit_result is not None:
                    pt, exec_bbox = hit_result   # 命中: 实时校验后的精确框
            if pt is None and bbox_raw is not None:
                pt = _bbox_point(bbox_raw, image)
                exec_bbox = _to_native_bbox(bbox_raw, image)   # VLM 框兜底: 换算为原图像素
            # 都没有 or 明确需要 retry_full → 完整 locate 管线兜底
            if (page_id, target) in state.retry_full or pt is None:
                element = _exec_full_locate(device, action_type, target)
                # 兜底成功 → 用定位管线结果回写 locate_cache (含精确 bbox)
                try:
                    _rebuild_and_cache_from_locate(device, locate_store, state, page_id, target, decision,
                                                   decision.regions or [], element)
                except Exception:  # noqa: BLE001
                    pass
                bb = _as_bbox(element.bbox)
                if bb is not None:
                    exec_bbox = bb              # 定位管线最终元素框 (精确)
                click_pt = list(element.action_point) if element.action_point else None
            else:
                click_pt = [int(pt[0]), int(pt[1])]
                _exec_at_point(device, action_type, pt, str(action.get("value") or "") if action_type == "input" else None)
                time.sleep(executor.DEFAULT_WAIT_AFTER_ACTION)
                # VLM 给了 bbox 且没 retry_full → 回写
                if bbox_raw is not None:
                    try:
                        bb = _to_native_bbox(bbox_raw, image)
                        if bb is not None:
                            locate_store.record_locate_success(
                                device, image, page_id=page_id,
                                page_title=decision.page_title,
                                element_desc=target, bbox=bb,
                                regions_from_vlm=_to_native_regions(decision.regions or [], image),
                            )
                    except Exception:  # noqa: BLE001
                        pass
            return None, list(exec_bbox) if exec_bbox is not None else None, click_pt
        if action_type == "keyboard_press":
            locate = str(action.get("locate") or "").strip()
            executor.run_keyboard_press(
                device, str(action.get("key") or ""), action_text=locate or None,
            )
            return None, None, None
        if action_type == "scroll":
            executor.run_scroll(device, str(action.get("direction") or "down"))
            return None, None, None
        if action_type == "swipe":
            executor.run_swipe(device, str(action.get("direction") or "left"))
            return None, None, None
        if action_type == "back":
            executor.run_back(device)
            return None, None, None
        if action_type == "query":
            data = executor.run_query(device, str(action.get("query") or "")).data
            _collect_finding(state, page_id, {
                "type": "data", "description": str(action.get("query") or ""), "data": data,
            })
            return None, None, None
        if action_type == "sleep":
            time.sleep(max(0.0, float(action.get("seconds") or 1.0)))
            return None, None, None
        return f"未知动作类型: {action_type!r}", None, None
    except Exception as exc:  # noqa: BLE001 - 单轮动作失败不终止探索, 计入失败轮
        return f"{type(exc).__name__}: {exc}", None, None


def _exec_full_locate(device: BaseDevice, action_type: str, target: str):
    """定位型动作的完整定位管线兜底: 截图 → 定位 → 执行, 返回 LocatedElement。"""
    if action_type == "tap":
        return executor.run_tap(device, target)
    if action_type == "input":
        value = str(action.get("value") or "").strip()
        return executor.run_input(device, target, value if value else _SAFE_INPUT_VALUE)
    if action_type == "double_click":
        return executor.run_double_click(device, target)
    if action_type == "right_click":
        return executor.run_right_click(device, target)
    if action_type == "clear":
        return executor.run_clear(device, target)
    raise ValueError(f"不支持的定位型动作: {action_type!r}")


def _exec_at_point(device: BaseDevice, action_type: str, pt, text: str | None = None) -> None:
    """定位型动作在已知坐标点上的直接执行 (缓存命中/VLM bbox 直击路径)。

    input 与 executor.run_input 一致: 点击聚焦后输入 (文本优先取 VLM value,
    为空用 _SAFE_INPUT_VALUE 兜底); 其余动作各走设备层对应原语。
    """
    if action_type == "tap":
        device.click(pt)
    elif action_type == "double_click":
        device.double_click(pt)
    elif action_type == "right_click":
        device.right_click(pt)
    elif action_type == "input":
        device.click(pt)
        device.input_text(text if text and text.strip() else _SAFE_INPUT_VALUE, position=pt)
    elif action_type == "clear":
        device.clear_text(position=pt)
    else:
        raise ValueError(f"不支持的定位型动作: {action_type!r}")


def _rebuild_and_cache_from_locate(
    device: BaseDevice, locate_store: LocateCacheStore, state: _State,
    page_id: str, target: str, decision: ExploreDecision,
    regions: list[dict[str, Any]],
    element: Any = None,
) -> None:
    """兜底走了完整 run_tap/run_input 后, 用定位管线结果回写 locate_cache (失败静默)。

    定位管线返回的 LocatedElement.bbox 即动作实际执行位置 (raw 坐标); 回写后
    后续轮次 try_locate 可直接命中精确 bbox, 报告框选也复用同一来源。
    """
    if element is None:
        return
    bb = _as_bbox(element.bbox)
    if bb is None:
        return
    try:
        shot = device.screenshot()
    except Exception:  # noqa: BLE001
        return
    try:
        locate_store.record_locate_success(
            device, shot, page_id=page_id, page_title=decision.page_title,
            element_desc=target, bbox=bb,
            regions_from_vlm=_to_native_regions(regions, shot),
        )
    except Exception:  # noqa: BLE001
        pass


# ---- 内部: finding 收集 & 逃逸检测 ----------------------------------------


def _collect_finding(state: _State, page_key: str, raw: dict[str, Any] | None) -> None:
    if not raw:
        return
    ftype = str(raw.get("type") or "").strip().lower()
    desc = str(raw.get("description") or "").strip()
    if ftype not in ("element", "page", "anomaly", "data") or not desc:
        return
    for existing in state.findings:
        if existing.type == ftype and existing.page_id == page_key \
                and existing.description.lower() == desc.lower():
            existing.occurrences += 1
            return
    dedup = (f"{ftype}:{page_key}", desc.lower())
    finding = ExploreFinding(
        id=f"finding_{len(state.findings) + len(state.suspected) + 1:03d}",
        type=ftype, description=desc, page_id=page_key, data=raw.get("data"),
    )
    if ftype == "anomaly":
        if dedup in state.suspected:
            confirmed = state.suspected.pop(dedup)
            confirmed.occurrences += 1
            state.findings.append(confirmed)
        else:
            state.suspected[dedup] = finding
        return
    state.findings.append(finding)


def _check_escape_and_windows(device: BaseDevice, state: _State) -> None:
    """应用逃逸检测 (见 §4.7): Web domain 白名单 / Windows 前台失焦; 新标签页仅 Web。"""
    context = getattr(device, "_context", None)
    if context is not None:
        try:
            pages = list(context.pages)
            if len(pages) > 1:
                for extra in pages[1:]:
                    url = getattr(extra, "url", "")
                    extra.close()
                    _collect_finding(state, state._current_key, {
                        "type": "page", "description": f"操作会打开新窗口: {url}",
                    })
        except Exception:  # noqa: BLE001
            pass
    url = _current_url(device)
    domain = _domain_of(url)
    if not domain:
        # ---- Windows: 绑定窗口设备的前台失焦检测与恢复 ----
        _recover_window_focus(device, state)
        return
    if not state.allowed_domains:
        # 首轮自动建立白名单基线: 探索起始 domain 即被测应用 (设计 §4.7 "domain 白名单")
        state.allowed_domains.add(domain)
        return
    if domain in state.allowed_domains:
        state.escape_failures = 0
        return
    logger.warning(f"探索检测到应用逃逸: {url}, 尝试返回")
    try:
        executor.run_back(device)
        state.escape_failures = 0 if _domain_of(_current_url(device)) in state.allowed_domains \
            else state.escape_failures + 1
    except Exception:  # noqa: BLE001
        state.escape_failures += 1


def _recover_window_focus(device: BaseDevice, state: _State) -> None:
    """被测应用前台失焦检测与恢复 (设备契约 is_app_foreground / restore_app_foreground)。

    对齐 loop-design §4.7 "Windows: 前台窗口句柄; 自动恢复 (激活窗口);
    连续 3 次恢复失败 -> failed" (由主循环 escape_failures 检查转 failed)。
    契约返回 None (平台无失焦概念, 如 Web) 时直接跳过, 不干预。

    恢复后必须复检前台: 各平台 restore 的 True 语义不统一 (autogui 含前台校验,
    WinAppDriver/Hypium 仅"调用成功"), 静默失败时若直接清零会导致永不到 failed。
    """
    try:
        focused = device.is_app_foreground()
    except Exception:  # noqa: BLE001
        focused = None
    if focused is None:
        return                      # 平台无此概念或无法检测
    if focused:
        state.escape_failures = 0
        return
    logger.warning("探索检测到应用失焦, 尝试恢复前台")
    try:
        ok = bool(device.restore_app_foreground())
    except Exception:  # noqa: BLE001
        ok = False
    if not ok:
        state.escape_failures += 1
        return
    # 复检前台: restore 仅"调用成功"不代表真实前台, 统一以检测结果为准
    try:
        recovered = device.is_app_foreground()
    except Exception:  # noqa: BLE001
        recovered = None
    state.escape_failures = 0 if recovered else state.escape_failures + 1


# ---- 内部: URL 工具 + dHash + bbox 换算 ---------------------------------


def _current_url(device: BaseDevice) -> str:
    page = getattr(device, "page", None) or getattr(device, "_page", None)
    try:
        return str(page.url) if page is not None else ""
    except Exception:  # noqa: BLE001
        return ""


def _domain_of(url: str) -> str:
    try:
        return urlsplit(url).netloc if url else ""
    except ValueError:
        return ""


def _dhash(image: bytes, *, size: int = 8) -> str:
    """差值哈希 (9x8 灰度相邻比较) —— 页面变化检测用。"""
    from PIL import Image

    with Image.open(io.BytesIO(image)) as img:
        gray = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
        pixels = list(gray.getdata())
    bits = []
    for row in range(size):
        offset = row * (size + 1)
        for col in range(size):
            bits.append("1" if pixels[offset + col] > pixels[offset + col + 1] else "0")
    return f"{int(''.join(bits), 2):0{size * size // 4}x}"


def _as_bbox(bbox_raw: Any) -> BBox | None:
    if not isinstance(bbox_raw, (list, tuple)) or len(bbox_raw) != 4:
        return None
    try:
        x1, y1, x2, y2 = (int(v) for v in bbox_raw)
    except (TypeError, ValueError):
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _bbox_point(bbox: Any, image: bytes) -> tuple[int, int] | None:
    """规划输出的 bbox (VLM 0-1000 归一化网格) → 原图中心点; 非法返回 None。"""
    parsed = _as_bbox(bbox)
    if parsed is None:
        return None
    x1, y1, x2, y2 = parsed
    from PIL import Image

    with Image.open(io.BytesIO(image)) as img:
        width, height = img.size
    fx, fy = width / _VLM_BBOX_GRID, height / _VLM_BBOX_GRID
    cx, cy = (x1 + x2) / 2 * fx, (y1 + y2) / 2 * fy
    if not (0 <= cx <= width and 0 <= cy <= height):
        return None
    return int(cx), int(cy)


def _to_native_bbox(bbox: Any, image: bytes) -> list[int] | None:
    """VLM 0-1000 归一化网格 bbox → 原图像素坐标; 非法返回 None。

    Qwen-VL 系列 (qwen3.7-plus 等) 输出的 bbox 是 0-1000 归一化网格,
    与输入图片实际尺寸无关 (实测: 1920x1080 与 1024x576 输入返回相同坐标)。
    """
    parsed = _as_bbox(bbox)
    if parsed is None:
        return None
    x1, y1, x2, y2 = parsed
    from PIL import Image

    with Image.open(io.BytesIO(image)) as img:
        width, height = img.size
    fx, fy = width / _VLM_BBOX_GRID, height / _VLM_BBOX_GRID
    return [int(x1 * fx), int(y1 * fy), int(x2 * fx), int(y2 * fy)]


def _to_native_regions(regions: list[Any], image: bytes) -> list[dict[str, Any]]:
    """VLM regions 的 bbox (0-1000 网格) → 原图像素; 供 locate_cache 视觉校验/匹配使用。"""
    out: list[dict[str, Any]] = []
    for region in regions:
        if not isinstance(region, dict):
            continue
        rb = region.get("bbox")
        bb = _to_native_bbox(rb, image) if rb is not None else None
        item = dict(region)
        if bb is not None:
            item["bbox"] = bb
        out.append(item)
    return out


def _collect_cycle_bboxes(image: bytes, decision: ExploreDecision,
                          exec_bbox: list[int] | None = None) -> list[list[int]]:
    """采集本轮 bbox: 动作实际执行框 (成功轮) + VLM 识别的 regions + 弹窗按钮框。

    exec_bbox: 动作执行成功时的实际定位 bbox (raw 坐标, 来自 locate_cache 实时校验/
    定位管线结果/VLM 框兜底); 优先于 VLM 的 action.bbox 用于报告框选——
    同一动作多次尝试 (bbox 点偏后 retry_full) 时, 报告框取执行成功那次的真实位置。
    """
    raw_sources: list[Any] = []
    action_bbox = (decision.action or {}).get("bbox")
    if exec_bbox is not None:
        raw_sources.append(exec_bbox)        # 成功轮: 实际执行框
    elif action_bbox is not None:
        raw_sources.append(action_bbox)      # 失败/无执行结果轮: VLM 尝试框
    for region in (decision.regions or []):
        rb = region.get("bbox") if isinstance(region, dict) else None
        if rb is not None:
            raw_sources.append(rb)
    dd = decision.dialog_decision or {}
    if dd.get("bbox") is not None:
        raw_sources.append(dd.get("bbox"))
    out: list[list[int]] = []
    for raw in raw_sources:
        bb = _to_native_bbox(raw, image)
        if bb is not None:
            out.append(bb)
    return out


def _thin_frames(frames: list[Any]) -> None:
    """超过上限时均匀抽稀 (截图/bbox/action 列表通用, 保持帧对齐)。"""
    if len(frames) <= _MAX_SUB_FRAMES:
        return
    step = (len(frames) - 1) / (_MAX_SUB_FRAMES - 1)
    kept = [frames[round(i * step)] for i in range(_MAX_SUB_FRAMES)]
    frames[:] = kept


# ---- 内部: 快照 (memory 模块) 水合 + 序列化 + 节点序列化 -----------------


def _node_to_dict(node: ExploreNode, cycle: int) -> dict[str, Any]:
    return {
        "cycle": cycle,
        "step_id": node.step_id,
        "action": node.action,
        "target": node.target,
        "from_page_id": node.from_page_id,
        "to_page_id": node.to_page_id,
        "is_new_page": node.is_new_page,
        "depth": node.depth,
        "findings": list(node.findings),
        "duration_ms": float(node.duration_ms),
        "error": node.error,
    }


def _hydrate_from_snapshot(state: _State, snap: _memory_mod.PersistedSnapshot) -> None:
    state.page_registry = registry_from_json(snap.page_registry_rows)
    state.seen_before = {fp.page_id for fp in state.page_registry}
    # visited_pages (page_id -> elements/interacted/title/url)
    for pid, info in (snap.visited_pages or {}).items():
        elements = list(info.get("elements") or [])
        interacted = set(info.get("interacted") or [])
        state.pages[pid] = _PageInfo(
            page_id=pid,
            title=str(info.get("title") or ""),
            url=info.get("url") if isinstance(info.get("url"), str) else None,
            elements=elements,
            interacted=interacted,
            discovered_at=str(info.get("discovered_at") or ""),
        )
    for row in snap.dead_elements or []:
        if isinstance(row, (list, tuple)) and len(row) == 2:
            state.dead.add((str(row[0]), str(row[1])))
    for row in snap.invalid_counts or []:
        try:
            key = (str(row["page_id"]), str(row["target"]))
            state.invalid_count[key] = int(row.get("count") or 0)
        except Exception:  # noqa: BLE001
            continue
    for row in snap.retry_full_elements or []:
        if isinstance(row, (list, tuple)) and len(row) == 2:
            state.retry_full.add((str(row[0]), str(row[1])))
    state.dialog_failures = dict(snap.dialog_failures or {})
    for row in snap.recent_transitions or []:
        if isinstance(row, (list, tuple)) and len(row) == 2:
            state.transitions.append((str(row[0]), str(row[1])))
    for fd in snap.findings or []:
        try:
            state.findings.append(ExploreFinding(
                id=str(fd.get("id") or ""),
                type=str(fd.get("type") or ""),
                description=str(fd.get("description") or ""),
                page_id=str(fd.get("page_id") or ""),
                screenshot_id=str(fd.get("screenshot_id") or ""),
                occurrences=int(fd.get("occurrences") or 1),
                data=fd.get("data"),
            ))
        except Exception:  # noqa: BLE001
            continue
    for row in snap.suspected_findings or []:
        if not isinstance(row, dict):
            continue
        dedup_key = row.get("dedup_key")
        finding_dict = row.get("finding")
        if not (isinstance(dedup_key, (list, tuple)) and len(dedup_key) == 2 and isinstance(finding_dict, dict)):
            continue
        try:
            finding = ExploreFinding(
                id=str(finding_dict.get("id") or ""),
                type=str(finding_dict.get("type") or ""),
                description=str(finding_dict.get("description") or ""),
                page_id=str(finding_dict.get("page_id") or ""),
                occurrences=int(finding_dict.get("occurrences") or 1),
                data=finding_dict.get("data"),
            )
            state.suspected[(str(dedup_key[0]), str(dedup_key[1]))] = finding
        except Exception:  # noqa: BLE001
            continue
    state.tokens = dict(snap.tokens or {})
    state.consecutive_failures = int(snap.consecutive_failures or 0)
    state.escape_failures = int(snap.escape_failures or 0)


def _snapshot_if_needed(
    mem_store: Any, state: _State, cycle: int, *,
    force: bool = False, path_override: int | None = None, session_id: str = "",
) -> None:
    if mem_store is None:
        return
    visited_pages: dict[str, dict[str, Any]] = {}
    for pid, p in state.pages.items():
        visited_pages[pid] = {
            "title": p.title,
            "url": p.url,
            "elements": list(p.elements),
            "interacted": list(p.interacted),
            "discovered_at": p.discovered_at,
        }
    findings_dict = [
        {
            "id": f.id, "type": f.type, "description": f.description,
            "page_id": f.page_id, "screenshot_id": f.screenshot_id,
            "occurrences": f.occurrences, "data": f.data,
        }
        for f in state.findings
    ]
    snap = _memory_mod.build_snapshot_dict(
        page_registry_rows=registry_to_json(state.page_registry),
        visited_pages=visited_pages,
        dead_elements=list(state.dead),
        invalid_counts=[(p, t, c) for (p, t), c in state.invalid_count.items()],
        retry_full=list(state.retry_full),
        dialog_failures=state.dialog_failures,
        recent_transitions=list(state.transitions[-_LOOP_WINDOW:]),
        findings=findings_dict,
        suspected_findings=list(state.suspected.items()),
        tokens=state.tokens,
        consecutive_failures=state.consecutive_failures,
        escape_failures=state.escape_failures,
        total_cycles_recorded=len(state.path),
        path_rows_count=path_override if path_override is not None else len(state.path),
        session_id=session_id,
    )
    _memory_mod.snapshot_state_if_needed(mem_store, snapshot_dict=snap, cycle=cycle, force=force)


__all__ = [
    "run_explore",
    "ExploreResult",
    "ExploreFinding",
    "ExploreNode",
    "ExploreCoverage",
    "ExploreError",
]
