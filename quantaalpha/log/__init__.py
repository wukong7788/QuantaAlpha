"""
AlphaAgent logging module - compatibility layer.

Maps alphaagent.log to rdagent.log so all alphaagent.log imports work.
Provides AlphaAgent-specific APIs: log_trace_path, set_trace_path.
"""

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from rdagent.log import rdagent_logger as _rdagent_logger
from rdagent.log.utils import LogColors


class _AlphaAgentLoggerWrapper:
    """
    Wraps rdagent_logger and adds log_trace_path / set_trace_path. Other attributes/methods delegate to rdagent_logger.
    """

    def __init__(self, inner):
        object.__setattr__(self, "_inner", inner)

    # ---------- AlphaAgent extension ----------
    @property
    def log_trace_path(self) -> Path:
        """Return current log trace path."""
        return self._inner.storage.path

    def set_trace_path(self, path) -> None:
        """Set new log trace path."""
        from rdagent.log.storage import FileStorage
        self._inner.storage = FileStorage(Path(path))

    # ---------- Delegate to rdagent_logger ----------
    def __getattr__(self, name):
        return getattr(self._inner, name)

    def __setattr__(self, name, value):
        if name in ("_inner",):
            object.__setattr__(self, name, value)
        else:
            setattr(self._inner, name, value)


logger = _AlphaAgentLoggerWrapper(_rdagent_logger)

# Default to Beijing time log folder unless user explicitly sets LOG_TRACE_PATH.
if not os.environ.get("LOG_TRACE_PATH"):
    beijing_now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d_%H-%M-%S-%f")
    logger.set_trace_path(Path.cwd() / "log" / beijing_now)

__all__ = ["logger", "LogColors"]
