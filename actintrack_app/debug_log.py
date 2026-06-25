"""Crash-safe breadcrumb logging for diagnosing import/decoding problems.

Disabled unless the ``ACTINTRACKCV_DEBUG`` environment variable is set to a
truthy value, so it adds no overhead or noise in normal or release runs. When
enabled, each call appends one *flushed and fsynced* line to

    <default workspace>/logs/import_debug.log   (e.g. ~/Documents/ActinTrackCV/logs)

so that even a hard native crash (a segfault/abort that no Python ``try/except``
can catch) still leaves the last reached checkpoint on disk. That makes it
possible to tell exactly where a frozen Windows build dies during Add Sample.

This module is intentionally dependency-free and never raises: a diagnostic
facility must not be able to break the app it is diagnosing.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

_ENV_FLAG = "ACTINTRACKCV_DEBUG"
_FALSEY = {"", "0", "false", "no", "off"}


def is_debug_enabled() -> bool:
    """True when breadcrumb logging is turned on via ``ACTINTRACKCV_DEBUG``."""
    return os.environ.get(_ENV_FLAG, "").strip().lower() not in _FALSEY


def log_path() -> Path:
    """Location of the breadcrumb log under the default user workspace."""
    from actintrack_app.paths import default_workspace_root

    return default_workspace_root() / "logs" / "import_debug.log"


def breadcrumb(message: str, **fields: object) -> None:
    """Append one timestamped, flushed checkpoint line. Never raises.

    No-op unless :func:`is_debug_enabled`. Optional ``fields`` are appended as
    ``key=value`` pairs (repr-quoted) for context such as paths and return codes.
    """
    if not is_debug_enabled():
        return
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        extra = "".join(f" {key}={value!r}" for key, value in fields.items())
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {message}{extra}\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        # Diagnostics must never themselves break the app.
        pass
