
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger as _logger


def _resolve_log_file_path(workspace_root, settings):
    configured_path = Path(settings.logging_config.file_path).expanduser()
    if configured_path.is_absolute():
        return configured_path
    return workspace_root / configured_path


def setup_logger():
    if getattr(setup_logger, "_configured", False):
        return

    from tisui.shared.config import WORKSPACE_ROOT, settings

    log_level = settings.logging_config.level or "INFO"
    log_file_path = _resolve_log_file_path(WORKSPACE_ROOT, settings)
    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    _logger.remove()
    _logger.add(sys.stderr, level=log_level)
    _logger.add(log_file_path, level=log_level, encoding="utf-8")

    print(f"[logger setup] log_level = {log_level}")
    print(f"[logger setup] log_file_path = {log_file_path}")

    setattr(setup_logger, "_configured", True)


class _LoggerWrapper:
    def __init__(self):
        self._setup_done = False

    def _ensure_setup(self):
        if not self._setup_done:
            setup_logger()
            self._setup_done = True

    def __getattr__(self, name):
        self._ensure_setup()
        return getattr(_logger, name)


logger = _LoggerWrapper()


__all__ = ["logger", "setup_logger"]
