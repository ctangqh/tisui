from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from tisui.shared.config import CACHE_ROOT, load_runtime_config, settings


_DEBUG_CACHE: dict[str, dict[str, Any]] = {}


def load_debug_config() -> dict[str, object]:
    runtime_config = load_runtime_config()

    debug_mode = str(runtime_config.get("debug_mode") or "file").strip().lower() or "file"
    if debug_mode not in {"file", "cache", "mixed"}:
        debug_mode = "cache"

    debug_output_dir = runtime_config.get("debug_output_dir") or str(CACHE_ROOT / "debug")
    debug_write_json = bool(runtime_config.get("debug_write_json", True))
    debug_write_image = bool(runtime_config.get("debug_write_image", True))
    debug_write_cache = bool(runtime_config.get("debug_write_cache", False))

    return {
        "debug": bool(getattr(settings, "debug", False)),
        "debug_mode": debug_mode,
        "debug_output_dir": debug_output_dir,
        "debug_write_json": debug_write_json,
        "debug_write_image": debug_write_image,
        "debug_write_cache": debug_write_cache,
    }


def is_debug_enabled(debug_config: dict[str, object]) -> bool:
    return bool(debug_config.get("debug", False))


def init_debug() -> dict[str, object]:
    return load_debug_config()


def load_context_data(context_data: dict[str, object]) -> dict[str, object]:
    action = str(context_data.get("action") or "").strip()
    meta = _ensure_kv_map(context_data.get("meta"))
    steps = context_data.get("steps") or []
    if not isinstance(steps, list):
        raise TypeError("context_data['steps'] 必须是 list")

    normalized_steps: list[dict[str, object]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        normalized_steps.append(
            {
                "name": str(step.get("name") or "").strip(),
                "description": str(step.get("description") or "").strip(),
                "input": _ensure_kv_map(step.get("input")),
                "output": _ensure_kv_map(step.get("output")),
            }
        )

    return {
        "action": action,
        "meta": meta,
        "steps": normalized_steps,
    }


def group_context_steps(steps: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped_steps: list[dict[str, object]] = []
    for index, step in enumerate(steps, start=1):
        grouped_steps.append(
            {
                "index": index,
                "name": str(step.get("name") or "").strip(),
                "description": str(step.get("description") or "").strip(),
                "input": _ensure_kv_map(step.get("input")),
                "output": _ensure_kv_map(step.get("output")),
            }
        )
    return grouped_steps


def build_debug_payload(
    context_data: dict[str, object],
    debug_config: dict[str, object],
) -> dict[str, object]:
    loaded_context = load_context_data(context_data)
    steps = group_context_steps(loaded_context.get("steps") or [])

    return {
        "action": loaded_context.get("action") or "",
        "context_meta": _ensure_kv_map(loaded_context.get("meta")),
        "steps": steps,
        "meta": {
            "debug_enabled": is_debug_enabled(debug_config),
            "debug_mode": str(debug_config.get("debug_mode") or "file"),
            "output_dir": debug_config.get("debug_output_dir"),
            "write_json": bool(debug_config.get("debug_write_json", True)),
            "write_image": bool(debug_config.get("debug_write_image", True)),
            "write_cache": bool(debug_config.get("debug_write_cache", False)),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        },
    }


def build_debug_summary(debug_payload: dict[str, object]) -> dict[str, object]:
    steps = debug_payload.get("steps") or []
    step_names: list[str] = []
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict):
                step_names.append(str(step.get("name") or "").strip())
    return {
        "action": str(debug_payload.get("action") or ""),
        "step_count": len(step_names),
        "step_names": step_names,
    }


def write_debug_file(
    debug_payload: dict[str, object],
    debug_config: dict[str, object],
) -> None:
    if not bool(debug_config.get("debug_write_json", True)):
        return

    output_dir = debug_config.get("debug_output_dir")
    if not output_dir:
        return

    action = str(debug_payload.get("action") or "").strip()
    file_stem = _normalize_file_stem(action or "debug")
    target_dir = Path(str(output_dir)).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / f"{file_stem}_context_debug.json"
    file_path.write_text(
        json.dumps(debug_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_debug_cache(
    debug_payload: dict[str, object],
    debug_config: dict[str, object],
) -> None:
    if not bool(debug_config.get("debug_write_cache", False)):
        return
    action = str(debug_payload.get("action") or "").strip()
    cache_key = _normalize_file_stem(action or "debug")
    _DEBUG_CACHE[cache_key] = deepcopy(debug_payload)


def render_debug_summary(debug_summary: dict[str, object]) -> str:
    action = str(debug_summary.get("action") or "")
    step_count = int(debug_summary.get("step_count") or 0)
    step_names = debug_summary.get("step_names") or []

    lines = [
        f"action: {action}",
        f"step_count: {step_count}",
    ]
    if isinstance(step_names, list) and step_names:
        lines.append(f"step_names: {', '.join(str(name) for name in step_names)}")
    else:
        lines.append("step_names: ")
    return "\n".join(lines)


def output_debug_data(
    context_data: dict[str, object],
    debug_config: dict[str, object] | None = None,
) -> None:
    config = debug_config or init_debug()
    if not is_debug_enabled(config):
        return

    debug_payload = build_debug_payload(context_data, config)
    debug_summary = build_debug_summary(debug_payload)
    mode = str(config.get("debug_mode") or "file").strip().lower()

    if mode in {"file", "mixed"}:
        write_debug_file(debug_payload, config)
    if mode in {"cache", "mixed"}:
        write_debug_cache(debug_payload, config)

    print(render_debug_summary(debug_summary))


def get_debug_cache() -> dict[str, dict[str, Any]]:
    return deepcopy(_DEBUG_CACHE)


def clear_debug_cache() -> None:
    _DEBUG_CACHE.clear()


def _ensure_kv_map(value: Any) -> dict[str, object]:
    if isinstance(value, dict):
        return {str(key): _sanitize_value(item) for key, item in value.items()}
    return {}


def _sanitize_value(value: Any) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _sanitize_value(item) for key, item in value.items()}
    return str(value)


def _normalize_file_stem(value: str) -> str:
    text = value.strip().lower()
    if not text:
        return "debug"

    chars: list[str] = []
    for ch in text:
        if ch.isalnum():
            chars.append(ch)
        elif ch in {"-", "_"}:
            chars.append(ch)
        else:
            chars.append("_")
    normalized = "".join(chars).strip("_")
    return normalized or "debug"


__all__ = [
    "build_debug_payload",
    "build_debug_summary",
    "clear_debug_cache",
    "get_debug_cache",
    "group_context_steps",
    "init_debug",
    "is_debug_enabled",
    "load_context_data",
    "load_debug_config",
    "output_debug_data",
    "render_debug_summary",
    "write_debug_cache",
    "write_debug_file",
]
