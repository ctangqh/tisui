"""explore 专属持久化薄层 (loop-design.md §5.1-§5.2 / §5.8)。

三件事:
1. `state.json` — 每 5 轮 + 结束时整写 ExploreState 聚合快照 (跨会话共享, 断点续探)
2. `path_<session_id>.jsonl` — 每轮 append-only 操作流水; 每个 ai_explore 会话一个文件,
   会话内各轮共享 (崩溃后尾部回放补齐 state 快照; 旧数据回退共享 path.jsonl)
3. `findings.json` — 结束时整写 findings 列表, 便于离线查看

调用方是 explorer.py; 底层复用 memory_store.py 的通用原子写/JSONL/.lock 能力,
页面指纹复用 page_identity.py 的序列化格式。

hydrate 方向: 磁盘 JSON → 纯 dict 结构 → explorer._State 自行填入字段。
snapshot 方向: explorer._State → 纯 dict → 本模块写 JSON。

这样 memory.py 不依赖 explorer 内部类型, 避免循环导入。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from tisui.agent.explore.memory_store import (
    MemoryStore,
    MemoryStoreError,
    open_memory_store,
)
from tisui.agent.explore.page_identity import registry_from_json, registry_to_json
from tisui.shared.logger import logger

_SCHEMA_VERSION = 1
_STATE_FILENAME = "state.json"
_PATH_FILENAME = "path.jsonl"  # 旧版共享 path 文件 (无会话 ID 的旧数据兼容)
_FINDINGS_FILENAME = "findings.json"
_NAMESPACE = "explore"
_SNAPSHOT_EVERY_N_CYCLES = 5


def _path_filename(session_id: str) -> str:
    """会话级 path 流水文件名: 每个 ai_explore 会话一个文件, 会话内各轮共享。"""
    return f"path_{session_id}.jsonl"


@dataclass
class PersistedSnapshot:
    """从 .cache 加载出的纯 dict 快照。explorer 自行把字段灌进 _State。"""

    schema_version: int
    page_registry_rows: list[dict[str, Any]]   # page_identity.PageRegistry 的序列化
    visited_pages: dict[str, dict[str, Any]]   # page_id -> {elements, interacted, title, url, screenshot_id, discovered_at}
    dead_elements: list[list[str]]             # [[page_id, target_desc], ...]
    invalid_counts: list[dict[str, Any]]       # [{"page_id":..,"target":..,"count":..}, ...]
    retry_full_elements: list[list[str]]       # bbox 点偏, 下次走完整 locate
    dialog_failures: dict[str, int]            # 弹窗指纹 -> 失败次数
    recent_transitions: list[list[str]]        # 最近页面转移窗口 (回环检测)
    findings: list[dict[str, Any]]             # 已确认的 findings
    suspected_findings: list[dict[str, Any]]   # anomaly 待二次确认
    tokens: dict[str, int]
    consecutive_failures: int
    escape_failures: int
    total_cycles_recorded: int
    current_session_id: str = ""  # 最近一次会话 ID, 用于定位其 path 文件; 旧数据为空
    path_rows_already_in_state: int = 0  # 已写入 state 的当前会话 path 行数, 重放时跳过前 N 行


# -------- 启动时: 打开 + 加载 --------------------------------------------


def open_memory(cache_key: str, *, reset: bool) -> tuple[MemoryStore | None, PersistedSnapshot | None, str]:
    """尝试打开 memory_cache。

    每次调用即一个会话, 生成独立 session_id; 返回 (store, snapshot, session_id):
      - 成功加载历史 → (MemoryStore 实例, 已填充的 PersistedSnapshot, 本次会话 ID)
      - 首次访问或复位 → (MemoryStore 实例, None, 视为无记忆)
      - 锁冲突等不可恢复 → 抛 MemoryStoreError, 由 explorer 转 ExploreError
    """
    session_id = f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
    try:
        ctx = open_memory_store(_NAMESPACE, cache_key, reset=reset)
    except MemoryStoreError:
        raise
    store = ctx.__enter__()  # 自行持有; explorer 调用 close_memory 释放锁
    if reset:
        return store, None, session_id
    state_obj = store.read_json(_STATE_FILENAME, default=None)
    if not isinstance(state_obj, dict):
        return store, None, session_id
    try:
        snap = _snapshot_from_dict(state_obj)
    except Exception as exc:  # noqa: BLE001 - 记忆损坏视同无记忆
        logger.warning(f"explore memory 损坏, 忽略历史: {type(exc).__name__}: {exc}")
        return store, None, session_id
    # 回放当前会话 path 文件在快照之后的增量 (最多 4 轮, §5.1);
    # 旧数据无 current_session_id 时回退旧 path.jsonl (schema 兼容)
    path_file = _path_filename(snap.current_session_id) if snap.current_session_id else _PATH_FILENAME
    extra = list(store.replay_jsonl(path_file, skip=snap.path_rows_already_in_state))
    if extra:
        _apply_path_delta(snap, extra)
        snap.path_rows_already_in_state += len(extra)
    return store, snap, session_id


def close_memory(store: MemoryStore | None) -> None:
    if store is None:
        return
    try:
        store.release()
    except Exception:  # noqa: BLE001
        pass


# -------- 运行时: 增量 (每轮) -------------------------------------------


def append_path_node(store: MemoryStore | None, node_dict: dict[str, Any], session_id: str = "") -> None:
    """每轮 append 一条操作流水到当前会话的 path 文件。node_dict 必须 JSON 可序列化。"""
    if store is None:
        return
    store.append_jsonl(_path_filename(session_id), node_dict)


def snapshot_state_if_needed(
    store: MemoryStore | None,
    *,
    snapshot_dict: dict[str, Any],
    cycle: int,
    force: bool = False,
) -> None:
    """每 5 轮 (SNAPSHOT_EVERY_N_CYCLES) 整写一次 state.json, 或 force=True 时立即写。

    findings.json 只在结束时 force=True 写, 避免频繁写。
    """
    if store is None:
        return
    if not force and cycle % _SNAPSHOT_EVERY_N_CYCLES != 0:
        return
    store.write_json(_STATE_FILENAME, snapshot_dict)
    if force:
        store.write_json(_FINDINGS_FILENAME, snapshot_dict.get("findings") or [])


# -------- explorer ↔ dict 转换 ------------------------------------------


def build_snapshot_dict(
    *,
    page_registry_rows: list[dict[str, Any]],
    visited_pages: dict[str, dict[str, Any]],
    dead_elements: Iterable[tuple[str, str]],
    invalid_counts: Iterable[tuple[str, str, int]],
    retry_full: Iterable[tuple[str, str]],
    dialog_failures: dict[str, int],
    recent_transitions: Iterable[tuple[str, str]],
    findings: list[dict[str, Any]],
    suspected_findings: Iterable[tuple[tuple[str, str], dict[str, Any]]],
    tokens: dict[str, int],
    consecutive_failures: int,
    escape_failures: int,
    total_cycles_recorded: int,
    path_rows_count: int,
    session_id: str = "",
) -> dict[str, Any]:
    """explorer 把 _State 转成 dict 后交给本函数加 schema_version 头。"""
    suspected = []
    for (dedup_type_page, _dedup_desc_lower), finding_dict in suspected_findings:
        suspected.append({
            "dedup_key": list(dedup_type_page),
            "finding": finding_dict,
        })
    return {
        "schema_version": _SCHEMA_VERSION,
        "current_session_id": session_id,
        "path_rows_already_in_state": path_rows_count,
        "page_registry_rows": page_registry_rows,
        "visited_pages": visited_pages,
        "dead_elements": [[p, t] for p, t in dead_elements],
        "invalid_counts": [{"page_id": p, "target": t, "count": c} for p, t, c in invalid_counts],
        "retry_full_elements": [[p, t] for p, t in retry_full],
        "dialog_failures": dict(dialog_failures),
        "recent_transitions": [[a, b] for a, b in recent_transitions],
        "findings": list(findings),
        "suspected_findings": suspected,
        "tokens": dict(tokens),
        "consecutive_failures": int(consecutive_failures),
        "escape_failures": int(escape_failures),
        "total_cycles_recorded": int(total_cycles_recorded),
    }


# -------- 内部: 快照 ↔ dict + 崩溃回放 -----------------------------------


def _snapshot_from_dict(d: dict[str, Any]) -> PersistedSnapshot:
    sv = int(d.get("schema_version") or 0)
    if sv != _SCHEMA_VERSION:
        raise MemoryStoreError(f"schema 版本不匹配: 期望 {_SCHEMA_VERSION}, 得到 {sv}")
    dead = d.get("dead_elements") or []
    invalid = d.get("invalid_counts") or []
    retry = d.get("retry_full_elements") or []
    transitions = d.get("recent_transitions") or []
    return PersistedSnapshot(
        schema_version=sv,
        current_session_id=str(d.get("current_session_id") or ""),
        path_rows_already_in_state=int(d.get("path_rows_already_in_state") or 0),
        page_registry_rows=list(d.get("page_registry_rows") or []),
        visited_pages={str(k): dict(v) for k, v in (d.get("visited_pages") or {}).items()},
        dead_elements=[list(x) for x in dead if isinstance(x, (list, tuple)) and len(x) == 2],
        invalid_counts=[dict(x) for x in invalid if isinstance(x, dict)],
        retry_full_elements=[list(x) for x in retry if isinstance(x, (list, tuple)) and len(x) == 2],
        dialog_failures={str(k): int(v) for k, v in (d.get("dialog_failures") or {}).items()},
        recent_transitions=[list(x) for x in transitions if isinstance(x, (list, tuple)) and len(x) == 2],
        findings=list(d.get("findings") or []),
        suspected_findings=list(d.get("suspected_findings") or []),
        tokens={str(k): int(v) for k, v in (d.get("tokens") or {}).items()},
        consecutive_failures=int(d.get("consecutive_failures") or 0),
        escape_failures=int(d.get("escape_failures") or 0),
        total_cycles_recorded=int(d.get("total_cycles_recorded") or 0),
    )


def _apply_path_delta(snap: PersistedSnapshot, extra_rows: list[Any]) -> None:
    """崩溃一致性: state.json 之后的 path.jsonl 尾部增量 (最多 4 轮)。

    只更新粗粒度字段, 避免在内存层复现 explorer 所有逻辑:
    - total_cycles_recorded += len(rows)
    - 对每个记录标记 error 的行, consecutive_failures + 1, 否则清零 (粗近似)
    - findings 不合并 (finding 由 VLM 在主循环里 collect, path 里不重复存大 payload, 下一轮主循环会按当前 UI 重新 observe, 漏几条 finding 可接受)
    """
    for row in extra_rows:
        if not isinstance(row, dict):
            continue
        snap.total_cycles_recorded += 1
        has_err = bool(row.get("error"))
        if has_err:
            snap.consecutive_failures += 1
        else:
            snap.consecutive_failures = 0


__all__ = [
    "PersistedSnapshot",
    "open_memory",
    "close_memory",
    "append_path_node",
    "snapshot_state_if_needed",
    "build_snapshot_dict",
]
