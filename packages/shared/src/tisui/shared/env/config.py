from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


ENV_DIR = Path(__file__).resolve().parent
CONFIG_YAML_PATH = ENV_DIR / "config.yaml"


@lru_cache(maxsize=1)
def load_env_config() -> dict[str, Any]:
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


__all__ = [
    "CONFIG_YAML_PATH",
    "ENV_DIR",
    "get_prompt_locale",
    "get_prompt_locale_fallbacks",
    "load_env_config",
]
