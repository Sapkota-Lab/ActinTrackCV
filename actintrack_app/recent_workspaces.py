"""Track recently opened workspace folders."""

from __future__ import annotations

import json
from pathlib import Path

from actintrack_app.utils import METADATA_DIR, RECENT_WORKSPACES_JSON

MAX_RECENT = 8


def _path(root: Path) -> Path:
    return Path(root).resolve() / METADATA_DIR / RECENT_WORKSPACES_JSON


def load_recent(root: Path) -> list[str]:
    path = _path(root)
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(p) for p in data if p]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def add_recent(root: Path, workspace: Path) -> None:
    root = Path(root).resolve()
    workspace = str(Path(workspace).resolve())
    entries = [workspace]
    for p in load_recent(root):
        if p != workspace:
            entries.append(p)
    entries = entries[:MAX_RECENT]
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
