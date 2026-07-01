"""Per-workspace user preferences (import defaults, etc.)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from actintrack_app.condition_group_manager import condition_group_exists
from actintrack_app.utils import METADATA_DIR

USER_PREFERENCES_JSON = "user_preferences.json"


def _prefs_path(root: Path) -> Path:
    return Path(root).resolve() / METADATA_DIR / USER_PREFERENCES_JSON


def load_preferences(root: Path) -> dict[str, Any]:
    path = _prefs_path(root)
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return dict(data)
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def save_preferences(root: Path, prefs: dict[str, Any]) -> None:
    root = Path(root).resolve()
    path = _prefs_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2)


def get_last_import_breed(root: Path) -> str | None:
    breed = str(load_preferences(root).get("last_import_breed", "")).strip()
    if breed and condition_group_exists(root, breed):
        return breed
    return None


def set_last_import_breed(root: Path, breed: str) -> None:
    if not condition_group_exists(root, breed):
        return
    prefs = load_preferences(root)
    prefs["last_import_breed"] = breed
    save_preferences(root, prefs)
