from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PACKAGE_ROOT = Path(__file__).resolve().parents[3]
CURRENT_WORKING_ROOT = Path.cwd().resolve()
RuntimeEnvName = Literal["dev", "prod"]


def _resolve_override_path(env_name: str) -> Path | None:
    raw = str(os.environ.get(env_name) or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _detect_development_workspace_root(package_root: Path) -> Path | None:
    packages_root = package_root.parent
    if packages_root.name != "packages":
        return None

    workspace_root = packages_root.parent
    shared_src_root = package_root / "src" / "tisui" / "shared"
    core_package_root = packages_root / "core"
    if shared_src_root.exists() and core_package_root.exists():
        return workspace_root
    return None


DEVELOPMENT_WORKSPACE_ROOT = _detect_development_workspace_root(PACKAGE_ROOT)


def _resolve_root_config_yaml_path() -> Path:
    override_path = _resolve_override_path("TISUI_CONFIG_PATH")
    if override_path is not None:
        return override_path

    candidates = []
    if DEVELOPMENT_WORKSPACE_ROOT is not None:
        candidates.append(DEVELOPMENT_WORKSPACE_ROOT / "config.yaml")

    candidates.extend(
        [
            CURRENT_WORKING_ROOT / "config.yaml",
            PACKAGE_ROOT / "config.yaml",
            # 安装态兜底: 随 wheel 附带的默认模板 (shared/config.yaml, 与本文件同级)。
            # dev 下该目录没有 config.yaml, 故此候选不影响开发环境行为。
            Path(__file__).resolve().parent / "config.yaml",
        ]
    )

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return candidates[0]


ROOT_CONFIG_YAML_PATH = _resolve_root_config_yaml_path()


@lru_cache(maxsize=1)
def _load_raw_runtime_config() -> dict[str, Any]:
    if not ROOT_CONFIG_YAML_PATH.exists():
        return {}

    with ROOT_CONFIG_YAML_PATH.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}
    return loaded if isinstance(loaded, dict) else {}


def _get_dict(config: dict[str, Any], key: str) -> dict[str, Any]:
    value = config.get(key)
    return value if isinstance(value, dict) else {}


def _normalize_runtime_env(value: Any) -> RuntimeEnvName | None:
    normalized = str(value or "").strip().lower()
    mapping: dict[str, RuntimeEnvName] = {
        "dev": "dev",
        "development": "dev",
        "prod": "prod",
        "production": "prod",
    }
    return mapping.get(normalized)


def _resolve_environment_name() -> RuntimeEnvName:
    override = _normalize_runtime_env(os.environ.get("TISUI_ENV"))
    if override is not None:
        return override

    config = _load_raw_runtime_config()
    runtime = _get_dict(config, "runtime")
    configured = _normalize_runtime_env(runtime.get("env"))
    if configured is not None:
        return configured

    legacy = _normalize_runtime_env(config.get("environment"))
    if legacy is not None:
        return legacy

    if DEVELOPMENT_WORKSPACE_ROOT is not None:
        return "dev"
    return "prod"


ENVIRONMENT = _resolve_environment_name()
IS_DEVELOPMENT_ENV = ENVIRONMENT == "dev"

DEFAULT_RUNTIME_PATHS: dict[RuntimeEnvName, dict[str, Any]] = {
    "dev": {
        "workspace_root": ".",
        "core_package_root": "packages/core",
        "env_files": [
            ".env",
        ],
    },
    "prod": {
        "workspace_root": ".",
        "core_package_root": ".",
        "env_files": [
            ".env",
        ],
    },
}


def _resolve_runtime_paths_options() -> dict[str, Any]:
    return dict(DEFAULT_RUNTIME_PATHS.get(ENVIRONMENT) or {})


def _resolve_relative_config_path(value: Any, default: Path) -> Path:
    raw = str(value or "").strip()
    if not raw:
        return default.resolve()

    path = Path(raw).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (ROOT_CONFIG_YAML_PATH.parent / path).resolve()


RUNTIME_PATHS = _resolve_runtime_paths_options()
WORKSPACE_ROOT = _resolve_relative_config_path(
    RUNTIME_PATHS.get("workspace_root"),
    DEVELOPMENT_WORKSPACE_ROOT or CURRENT_WORKING_ROOT,
)
CORE_PACKAGE_ROOT = _resolve_relative_config_path(
    RUNTIME_PATHS.get("core_package_root"),
    (DEVELOPMENT_WORKSPACE_ROOT / "packages" / "core")
    if DEVELOPMENT_WORKSPACE_ROOT is not None
    else CURRENT_WORKING_ROOT,
)


def _resolve_cache_root() -> Path:
    runtime = _get_dict(_load_raw_runtime_config(), "runtime")
    raw_cache_path = str(runtime.get("cache_path") or "").strip()
    if not raw_cache_path:
        return CURRENT_WORKING_ROOT / ".cache"

    configured_path = Path(raw_cache_path).expanduser()
    if configured_path.is_absolute():
        return configured_path.resolve()
    return (ROOT_CONFIG_YAML_PATH.parent / configured_path).resolve()


CACHE_ROOT = _resolve_cache_root()


def _resolve_report_root() -> Path:
    """报告输出根目录: 读取 runtime.report_path, 空值退化到 <workspace>/output/reports。"""
    runtime = _get_dict(_load_raw_runtime_config(), "runtime")
    raw_report_path = str(runtime.get("report_path") or "").strip()
    if not raw_report_path:
        # 未配置时与旧行为一致: <workspace>/output/reports
        return (WORKSPACE_ROOT / "output" / "reports").resolve()

    configured_path = Path(raw_report_path).expanduser()
    if configured_path.is_absolute():
        return configured_path.resolve()
    return (ROOT_CONFIG_YAML_PATH.parent / configured_path).resolve()


REPORT_ROOT = _resolve_report_root()


def _resolve_env_file_paths() -> tuple[str, ...]:
    override_path = _resolve_override_path("TISUI_ENV_FILE")
    if override_path is not None:
        return (str(override_path),)

    candidates: list[Path] = []
    configured_env_files = RUNTIME_PATHS.get("env_files")
    if isinstance(configured_env_files, list):
        for item in configured_env_files:
            candidates.append(_resolve_relative_config_path(item, PACKAGE_ROOT / ".env"))
    elif IS_DEVELOPMENT_ENV and DEVELOPMENT_WORKSPACE_ROOT is not None:
        candidates.extend(
            [
                DEVELOPMENT_WORKSPACE_ROOT / ".env",
                DEVELOPMENT_WORKSPACE_ROOT / "packages" / "core" / ".env",
            ]
        )
    else:
        candidates.append(CURRENT_WORKING_ROOT / ".env")

    candidates.append(PACKAGE_ROOT / ".env")

    normalized: list[str] = []
    seen: set[str] = set()
    for path in candidates:
        resolved = str(path.resolve())
        if resolved not in seen:
            normalized.append(resolved)
            seen.add(resolved)
    return tuple(normalized)


ENV_FILE_PATHS = _resolve_env_file_paths()


@lru_cache(maxsize=1)
def load_runtime_config() -> dict[str, Any]:
    return dict(_load_raw_runtime_config())


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class OpenAICompatibleModelConfig(BaseModel):
    provider: str = ""
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    timeout: int = 60
    max_retries: int = 3
    temperature: float | None = None
    max_tokens: int | None = None


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file_path: str = "logs/tisui.log"


class ActConfig(BaseModel):
    cycle_limit: int = 5
    total_timeout: float = 900.0


class ExploreConfig(BaseModel):
    max_cycles: int = 50
    total_timeout: float = 600.0
    max_depth: int | None = None


class RuntimeEnvironmentConfig(BaseModel):
    env: RuntimeEnvName = "dev"
    debug: bool = False
    workspace_root: str = ""
    core_package_root: str = ""
    cache_root: str = ""
    report_path: str = ""
    config_yaml_path: str = ""
    env_files: list[str] = Field(default_factory=list)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATHS,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    vision_api_key: str = Field(default="", alias="VISION_API_KEY")

    @property
    def llm_config(self) -> OpenAICompatibleModelConfig:
        runtime = load_runtime_config()
        model = _get_dict(runtime, "model")
        llm = _get_dict(model, "llm")
        return OpenAICompatibleModelConfig(
            provider=str(llm.get("provider") or "openai").strip(),
            api_key=self.llm_api_key,
            base_url=str(llm.get("base_url") or "https://api.openai.com/v1").strip(),
            model=str(llm.get("model") or "gpt-4o").strip(),
            timeout=_as_int(llm.get("timeout"), _as_int(model.get("timeout"), 60)),
            max_retries=_as_int(llm.get("max_retries"), _as_int(model.get("max_retries"), 3)),
            temperature=_as_float(llm.get("temperature"), 0.0) if llm.get("temperature") is not None else None,
            max_tokens=_as_int(llm.get("max_tokens"), 0) if llm.get("max_tokens") is not None else None,
        )

    @property
    def vision_config(self) -> OpenAICompatibleModelConfig:
        runtime = load_runtime_config()
        model = _get_dict(runtime, "model")
        vision = _get_dict(model, "vision")
        llm = self.llm_config
        return OpenAICompatibleModelConfig(
            provider=str(vision.get("provider") or llm.provider).strip(),
            api_key=self.vision_api_key or self.llm_api_key,
            base_url=str(vision.get("base_url") or llm.base_url).strip(),
            model=str(vision.get("model") or llm.model).strip(),
            timeout=_as_int(vision.get("timeout"), _as_int(model.get("timeout"), llm.timeout)),
            max_retries=_as_int(vision.get("max_retries"), _as_int(model.get("max_retries"), llm.max_retries)),
            temperature=(
                _as_float(vision.get("temperature"), 0.0)
                if vision.get("temperature") is not None
                else llm.temperature
            ),
            max_tokens=(
                _as_int(vision.get("max_tokens"), 0)
                if vision.get("max_tokens") is not None
                else llm.max_tokens
            ),
        )

    @property
    def MODEL_TIMEOUT(self) -> int:
        runtime = load_runtime_config()
        model = _get_dict(runtime, "model")
        return _as_int(model.get("timeout"), self.llm_config.timeout)

    @property
    def MODEL_MAX_RETRIES(self) -> int:
        runtime = load_runtime_config()
        model = _get_dict(runtime, "model")
        return _as_int(model.get("max_retries"), self.llm_config.max_retries)

    @property
    def logging_config(self) -> LoggingConfig:
        runtime = load_runtime_config()
        logging = _get_dict(runtime, "logging")
        return LoggingConfig(
            level=str(logging.get("level") or "INFO").strip().upper(),
            file_path=str(logging.get("file_path") or "logs/tisui.log").strip(),
        )

    @property
    def act_config(self) -> ActConfig:
        runtime = load_runtime_config()
        act = _get_dict(runtime, "act")
        return ActConfig(
            cycle_limit=_as_int(act.get("cycle_limit"), 5),
            total_timeout=_as_float(act.get("total_timeout"), 900.0),
        )

    @property
    def explore_config(self) -> ExploreConfig:
        runtime = load_runtime_config()
        explore = _get_dict(runtime, "explore")
        return ExploreConfig(
            max_cycles=_as_int(explore.get("max_cycles"), 50),
            total_timeout=_as_float(explore.get("total_timeout"), 600.0),
            max_depth=_as_int(explore.get("max_depth"), 0) or None,
        )

    @property
    def runtime_environment(self) -> RuntimeEnvironmentConfig:
        runtime = load_runtime_config()
        runtime_options = _get_dict(runtime, "runtime")
        return RuntimeEnvironmentConfig(
            env=ENVIRONMENT,
            debug=_as_bool(runtime_options.get("debug"), _as_bool(runtime.get("debug"), False)),
            workspace_root=str(WORKSPACE_ROOT),
            core_package_root=str(CORE_PACKAGE_ROOT),
            cache_root=str(CACHE_ROOT),
            report_path=str(REPORT_ROOT),
            config_yaml_path=str(ROOT_CONFIG_YAML_PATH),
            env_files=list(ENV_FILE_PATHS),
        )

    @property
    def debug(self) -> bool:
        runtime = load_runtime_config()
        runtime_options = _get_dict(runtime, "runtime")
        return _as_bool(runtime_options.get("debug"), _as_bool(runtime.get("debug"), False))


settings = Settings()


__all__ = [
    "CACHE_ROOT",
    "ENV_FILE_PATHS",
    "ENVIRONMENT",
    "ROOT_CONFIG_YAML_PATH",
    "WORKSPACE_ROOT",
    "OpenAICompatibleModelConfig",
    "LoggingConfig",
    "ActConfig",
    "ExploreConfig",
    "RuntimeEnvironmentConfig",
    "Settings",
    "load_runtime_config",
    "settings",
]
