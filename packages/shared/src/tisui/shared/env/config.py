from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


ENV_DIR = Path(__file__).resolve().parent
CONFIG_YAML_PATH = ENV_DIR / "config.yaml"


def _load_root_config() -> dict[str, Any]:
    """尝试读取主配置(root config.yaml)。

    主配置由 tisui.shared.config 解析，遵循 TISUI_CONFIG_PATH / 工作目录 / 包内
    的优先级。任何异常都退化到空 dict，交由包内 env/config.yaml 兜底。
    """
    try:
        from tisui.shared.config import load_runtime_config

        root = load_runtime_config()
        return root if isinstance(root, dict) else {}
    except Exception:
        return {}


@lru_cache(maxsize=1)
def load_env_config() -> dict[str, Any]:
    """读取配置：主配置优先，包内 env/config.yaml 兜底。

    这样用户只需维护根目录一份 config.yaml，prompt / explore 等段都能被读到。
    """
    # 1) 主配置优先
    root = _load_root_config()
    if root:
        return root

    # 2) 兜底：包内 env/config.yaml（安装态默认模板）
    if not CONFIG_YAML_PATH.exists():
        return {}

    with CONFIG_YAML_PATH.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}
    if not isinstance(loaded, dict):
        return {}
    return loaded


def get_prompt_locale(default: str = "zh-CN") -> str:
    config = load_env_config()
    prompt_config = config.get("prompt")
    if not isinstance(prompt_config, dict):
        return default

    value = str(prompt_config.get("default_locale") or "").strip()
    return value or default


def get_prompt_locale_fallbacks() -> dict[str, str]:
    config = load_env_config()
    prompt_config = config.get("prompt")
    if not isinstance(prompt_config, dict):
        return {}

    fallbacks = prompt_config.get("locale_fallbacks")
    if not isinstance(fallbacks, dict):
        return {}

    normalized: dict[str, str] = {}
    for key, value in fallbacks.items():
        normalized_key = str(key or "").strip()
        normalized_value = str(value or "").strip()
        if normalized_key and normalized_value:
            normalized[normalized_key] = normalized_value
    return normalized


def get_forbidden_enabled(default: bool = True) -> bool:
    """是否启用 ai_explore 的危险词拦截(含内置黑名单)。

    配置项: explore.forbidden_enabled
      true  (默认) 启用
      false        关闭内置黑名单(用户显式传入的 forbidden 仍然生效)
    """
    config = load_env_config()
    explore_config = config.get("explore")
    if not isinstance(explore_config, dict):
        return default

    value = explore_config.get("forbidden_enabled")
    if isinstance(value, bool):
        return value
    return default


__all__ = [
    "CONFIG_YAML_PATH",
    "ENV_DIR",
    "get_forbidden_enabled",
    "get_prompt_locale",
    "get_prompt_locale_fallbacks",
    "load_env_config",
]
