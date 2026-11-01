from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tisui.shared.config import CACHE_ROOT


@dataclass(frozen=True)
class CacheConfig:
    root_dir: Path


@dataclass(frozen=True)
class CacheKey:
    namespace: str
    identifier: str


DEFAULT_CACHE_ROOT = CACHE_ROOT / "agent"
DEFAULT_CACHE_NAMESPACE_PREPROCESS = "preprocess"
DEFAULT_CACHE_NAMESPACE_IMAGE = "image"
DEFAULT_CACHE_NAMESPACE_COORD = "coord"
DEFAULT_CACHE_NAMESPACE_CONTEXT = "context"


def get_default_cache_config() -> CacheConfig:
    """
    返回 agent 通用缓存配置。
    """
    return CacheConfig(root_dir=DEFAULT_CACHE_ROOT)


def build_cache_path(cache_key: CacheKey, *, config: CacheConfig | None = None) -> Path:
    """
    根据通用缓存 key 构建缓存文件路径。

    说明：
    - 通过 `namespace` 区分图片缓存、坐标缓存、上下文缓存、preprocess 缓存等不同类型。
    - 通过 `identifier` 指定具体实体，例如图片 hash。
    """
    resolved_config = config or get_default_cache_config()
    safe_namespace = cache_key.namespace.strip().replace("\\", "_").replace("/", "_")
    safe_identifier = cache_key.identifier.strip().replace("\\", "_").replace("/", "_")
    return resolved_config.root_dir / safe_namespace / f"{safe_identifier}.json"


def load_cached_payload(
    cache_key: CacheKey,
    *,
    config: CacheConfig | None = None,
) -> dict[str, Any] | None:
    """
    读取通用 JSON 缓存 payload。

    说明：
    - 当前使用本地 JSON 文件作为缓存存储。
    - 若缓存文件不存在，返回 `None`。
    """
    cache_path = build_cache_path(cache_key, config=config)
    if not cache_path.exists():
        return None

    return json.loads(cache_path.read_text(encoding="utf-8"))


def save_cached_payload(
    cache_key: CacheKey,
    payload: dict[str, Any],
    *,
    config: CacheConfig | None = None,
) -> None:
    """
    写入通用 JSON 缓存 payload。

    说明：
    - 当前统一落盘为本地 JSON 文件。
    - 后续图片缓存、坐标缓存、上下文缓存都复用该底层能力。
    """
    cache_path = build_cache_path(cache_key, config=config)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_preprocess_cache_key(image_hash: str) -> CacheKey:
    """
    根据图片 hash 构建 preprocess 缓存 key。
    """
    return CacheKey(
        namespace=DEFAULT_CACHE_NAMESPACE_PREPROCESS,
        identifier=image_hash,
    )


def load_preprocess_cache(
    image_hash: str,
    *,
    config: CacheConfig | None = None,
) -> dict[str, Any] | None:
    """
    读取 preprocess 专用缓存。

    说明：
    - 当前只实现 preprocess 缓存。
    - 图片缓存、坐标缓存、上下文缓存先通过 `CacheKey` 预留 namespace，不单独提供快捷接口。
    """
    return load_cached_payload(build_preprocess_cache_key(image_hash), config=config)


def save_preprocess_cache(
    image_hash: str,
    payload: dict[str, Any],
    *,
    config: CacheConfig | None = None,
) -> None:
    """
    写入 preprocess 专用缓存。
    """
    save_cached_payload(
        build_preprocess_cache_key(image_hash),
        payload,
        config=config,
    )


__all__ = [
    "CacheKey",
    "CacheConfig",
    "DEFAULT_CACHE_NAMESPACE_CONTEXT",
    "DEFAULT_CACHE_NAMESPACE_COORD",
    "DEFAULT_CACHE_NAMESPACE_IMAGE",
    "DEFAULT_CACHE_NAMESPACE_PREPROCESS",
    "DEFAULT_CACHE_ROOT",
    "build_cache_path",
    "build_preprocess_cache_key",
    "get_default_cache_config",
    "load_cached_payload",
    "load_preprocess_cache",
    "save_cached_payload",
    "save_preprocess_cache",
]
