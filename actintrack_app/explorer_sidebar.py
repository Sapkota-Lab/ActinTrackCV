"""Explorer sidebar labels and tree item metadata (Phase 4A).

Pure helpers for deriving user-facing tree labels without embedding Condition Group
names or internal sample numbers in child rows.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

ITEM_TYPE_CONDITION_GROUP = "condition_group"
ITEM_TYPE_SAMPLE = "sample"
ITEM_TYPE_EMPTY_SAMPLE = "empty_sample"
ITEM_TYPE_MESSAGE = "message"

EXPLORER_SAMPLE_MIME = "application/x-actintrack-sample-id"

_GENERIC_BATCH_NAME = re.compile(r"^Batch\s+\d+$", re.IGNORECASE)


def _original_filename_stem(row: dict[str, Any]) -> str:
    original = str(row.get("original_filename", "")).strip()
    return Path(original).stem if original else ""


def _batch_name_is_custom_display_name(row: dict[str, Any]) -> bool:
    """True when batch_name is a user-facing rename, not the import filename stem."""
    batch_name = str(row.get("batch_name", "")).strip()
    if not batch_name or _GENERIC_BATCH_NAME.match(batch_name):
        return False
    stem = _original_filename_stem(row)
    if not stem:
        return True
    from actintrack_app.batch_manager import sanitize_batch_name

    return sanitize_batch_name(batch_name) != sanitize_batch_name(stem)


def sample_sidebar_display_label(row: dict[str, Any]) -> str:
    """User-facing label for a sample/data row in the explorer tree.

    Prefers a custom Sample rename when present; otherwise shows the source
    file name. Does not include Condition Group names, export prefixes, or
    internal sample numbers. ``original_filename`` metadata is never modified.
    """
    if _batch_name_is_custom_display_name(row):
        return str(row.get("batch_name", "")).strip()
    original = str(row.get("original_filename", "")).strip()
    if original:
        return Path(original).name
    batch_name = str(row.get("batch_name", "")).strip()
    if batch_name and not _GENERIC_BATCH_NAME.match(batch_name):
        return batch_name
    sample_id = str(row.get("sample_id", "")).strip()
    return sample_id or "Sample"


def empty_sample_sidebar_label(batch_name: str = "") -> str:
    """Placeholder label for a sample slot with no imported data yet."""
    name = str(batch_name).strip()
    if name and not _GENERIC_BATCH_NAME.match(name):
        return f"{name} (no data)"
    return "(no data — right-click Replace Data)"


def condition_group_tree_meta(condition_group_id: str) -> dict[str, Any]:
    return {
        "item_type": ITEM_TYPE_CONDITION_GROUP,
        "condition_group_id": str(condition_group_id),
    }


def sample_tree_meta(row: dict[str, Any]) -> dict[str, Any]:
    meta = dict(row)
    meta["item_type"] = ITEM_TYPE_SAMPLE
    return meta


def empty_sample_tree_meta(
    group_id: str,
    batch_name: str,
    *,
    batch_number: int = 1,
) -> dict[str, Any]:
    return {
        "item_type": ITEM_TYPE_EMPTY_SAMPLE,
        "group": str(group_id),
        "batch_name": str(batch_name),
        "batch_number": int(batch_number or 1),
    }


def tree_item_condition_group_id(meta: dict[str, Any] | None) -> str | None:
    if not meta:
        return None
    item_type = meta.get("item_type")
    if item_type == ITEM_TYPE_CONDITION_GROUP:
        gid = str(meta.get("condition_group_id", "")).strip()
        return gid or None
    if item_type in (ITEM_TYPE_SAMPLE, ITEM_TYPE_EMPTY_SAMPLE):
        gid = str(meta.get("group") or meta.get("condition_group_id", "")).strip()
        return gid or None
    return None


def is_draggable_sample_meta(meta: dict[str, Any] | None) -> bool:
    """True when explorer metadata represents a Sample row that may be dragged."""
    return bool(meta) and meta.get("item_type") == ITEM_TYPE_SAMPLE and str(
        meta.get("sample_id", "")
    ).strip()


def is_valid_sample_drop_target_meta(meta: dict[str, Any] | None) -> bool:
    """True when dropping a Sample onto this row should target a Condition Group."""
    if not meta:
        return False
    item_type = meta.get("item_type")
    return item_type in (
        ITEM_TYPE_CONDITION_GROUP,
        ITEM_TYPE_SAMPLE,
        ITEM_TYPE_EMPTY_SAMPLE,
    )


def label_excludes_condition_group_name(
    label: str, condition_group_name: str
) -> bool:
    """Return True when ``label`` does not embed the group display name."""
    group = str(condition_group_name).strip()
    if not group:
        return True
    text = str(label).strip()
    if not text:
        return True
    if text.casefold().startswith(group.casefold()):
        return False
    if f"{group}--" in text or f"{group} /" in text:
        return False
    return True
