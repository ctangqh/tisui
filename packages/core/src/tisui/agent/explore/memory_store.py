"""通用持久化底座 (loop-design.md §5.1/§5.8)。

零业务语义: 只负责 `<cache_root>/<namespace>/<key>/` 下的目录、.lock 并发保护、
schema_version 版本头、JSON 原子写、JSONL append + 回放。被 memory.py / locate_cache.py
调用。业务语义 (ExploreState / 坐标缓存结构) 在调用方定义。
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from tisui.shared.config import CACHE_ROOT

SCHEMA_VERSION = 1
_LOCK_STALE_SECONDS = 3600


class MemoryStoreError(RuntimeError):
    """持久化层无法启动 (锁冲突 / 目录不可写)。"""


@dataclass
class MemoryStorePaths:
    """单个 memory_cache key 对应的目录结构。"""

    base: Path

    def _sub(self, *parts: str) -> Path:
        return self.base.joinpath(*parts)

    @property
    def lock(self) -> Path:
        return self._sub(".lock")

    @property
    def schema_marker(self) -> Path:
        return self._sub(".schema_version")


class MemoryStore:
    """以 `<cache_root>/<namespace>/<key>/` 为根的持久化访问器。

    用法:
        store = MemoryStore("explore", "settings-app", reset=True/False)
        store.write_json("state.json", state_obj)
        state = store.read_json("state.json", default={})
        store.append_jsonl("path.jsonl", node_dict)
        for node in store.replay_jsonl("path.jsonl", skip=42):
            ...
    """

    def __init__(self, namespace: str, key: str, *, reset: bool = False) -> None:
        if not str(namespace).strip() or not str(key).strip():
            raise MemoryStoreError("namespace 与 key 均不能为空")
        paths = MemoryStorePaths(base=Path(CACHE_ROOT) / namespace / key)
        paths.base.mkdir(parents=True, exist_ok=True)
        self.paths = paths
        self._ns = namespace
        self._key = key
        if reset:
            self._wipe()
            paths.base.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()
        self._acquire_lock()

    # ---- 生命周期 / 基础 -------------------------------------------------

    def _wipe(self) -> None:
        import shutil

        if self.paths.base.exists():
            shutil.rmtree(self.paths.base, ignore_errors=True)

    def _ensure_schema(self) -> None:
        marker = self.paths.schema_marker
        if marker.exists():
            try:
                written = int(marker.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                written = -1
            if written != SCHEMA_VERSION:
                self._wipe()
                self.paths.base.mkdir(parents=True, exist_ok=True)
        if not marker.exists():
            marker.write_text(str(SCHEMA_VERSION), encoding="utf-8")

    def _acquire_lock(self) -> None:
        lock = self.paths.lock
        pid = os.getpid()
        import time

        now = int(time.time())
        if lock.exists():
            try:
                raw = lock.read_text(encoding="utf-8").split()
                old_pid = int(raw[0])
                old_ts = int(raw[1]) if len(raw) > 1 else 0
            except (OSError, ValueError):
                old_pid, old_ts = -1, 0
            alive = _pid_alive(old_pid) if old_pid > 0 else False
            stale = (now - old_ts) > _LOCK_STALE_SECONDS if old_ts else True
            if alive and not stale:
                raise MemoryStoreError(
                    f"memory_cache {self._ns}/{self._key} 已被进程 {old_pid} 占用; "
                    "确认无并发后手动删除 .lock 文件或换一个 key"
                )
            try:
                lock.unlink()
            except OSError:
                pass
        lock.write_text(f"{pid} {now}", encoding="utf-8")

    def release(self) -> None:
        """显式释放锁 (通常进程退出时自动, 长生命周期服务可手动调用)。"""
        try:
            if self.paths.lock.exists():
                self.paths.lock.unlink()
        except OSError:
            pass

    def __del__(self) -> None:  # noqa: D401 - 尽力而为, 失败忽略
        try:
            self.release()
        except Exception:  # noqa: BLE001
            pass

    # ---- JSON 原子写 ----------------------------------------------------

    def write_json(self, name: str, payload: Any) -> None:
        """JSON 原子写 (tempfile + replace)。payload 必须 JSON 可序列化。"""
        target = self.paths._sub(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=f".{name}.", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, target)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def read_json(self, name: str, *, default: Any = None) -> Any:
        target = self.paths._sub(name)
        if not target.exists():
            return default
        try:
            with target.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return default

    # ---- JSONL 追加 + 回放 ----------------------------------------------

    def append_jsonl(self, name: str, record: Any) -> None:
        """追加一行 JSON (append-only, 崩溃不丢已写入)。"""
        target = self.paths._sub(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False)
        with target.open("a", encoding="utf-8") as f:
            f.write(line)
            f.write("\n")
            f.flush()

    def replay_jsonl(self, name: str, *, skip: int = 0) -> Iterator[Any]:
        """按顺序回放 JSONL, 非法行静默跳过。skip 跳过前 N 行 (崩溃恢复对齐 state 快照)。"""
        target = self.paths._sub(name)
        if not target.exists():
            return
        with target.open("r", encoding="utf-8") as f:
            for idx, line in enumerate(f):
                if idx < skip:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    # ---- locate_cache 子目录 --------------------------------------------

    def sub_paths(self, *parts: str) -> Path:
        """返回子目录路径并确保存在 (locate_cache 用)。"""
        p = self.paths._sub(*parts)
        p.mkdir(parents=True, exist_ok=True)
        return p


# ---- 工具: PID 存活探测 -------------------------------------------------

def _pid_alive(pid: int) -> bool:
    """尽力而为检测本地 pid 是否存活; 探测不到返回 False。"""
    try:
        if pid <= 0:
            return False
        import ctypes
        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        handle = kernel32.OpenProcess(SYNCHRONIZE, 0, pid)
        if handle == 0:
            return False
        try:
            WAIT_TIMEOUT = 0x00000102
            return kernel32.WaitForSingleObject(handle, 0) != WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        return False


@contextmanager
def open_memory_store(namespace: str, key: str, *, reset: bool = False) -> Iterator[MemoryStore]:
    """with 上下文: 离开时自动释放锁。"""
    store = MemoryStore(namespace, key, reset=reset)
    try:
        yield store
    finally:
        store.release()


__all__ = [
    "SCHEMA_VERSION",
    "MemoryStore",
    "MemoryStoreError",
    "MemoryStorePaths",
    "open_memory_store",
]
