"""Legacy sample-registry module (v1 filenames/keys).

Prefer ``actintrack_app.sample_registry`` for new code. Load/save routes through
``schema_compat`` (v2: ``sample_registry.json``, ``data_files.csv``).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from actintrack_app.utils import METADATA_DIR, PROCESSED_DIR, RAW_DIR, VIDEO_EXTENSIONS


BATCHES_JSON = "batches.json"
LEGACY_BATCH_NAME = "Legacy_Batch"
_INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _batches_path(root: Path) -> Path:
    return Path(root).resolve() / METADATA_DIR / BATCHES_JSON


def _load_batches_registry(root: Path) -> dict[str, list[dict[str, Any]]]:
    from actintrack_app.schema_compat import load_sample_registry_as_v1

    return load_sample_registry_as_v1(root)


def _save_batches_registry(root: Path, data: dict[str, list[dict[str, Any]]]) -> None:
    from actintrack_app.schema_compat import save_sample_registry

    save_sample_registry(root, data)


def sanitize_batch_name(name: str) -> str:
    """Filesystem-safe batch folder name; preserves spaces (e.g. 'Batch 1')."""
    text = str(name).strip()
    text = _INVALID_NAME.sub("_", text)
    return text or "Batch 1"


def display_batch_name(batch_number: int) -> str:
    """Internal/registry batch folder name (kept for backward compatibility)."""
    return f"Batch {int(batch_number)}"


def display_sample_label(batch_number: int, batch_name: str = "") -> str:
    """User-facing sample label mapped from internal batch numbering."""
    parsed = _canonical_batch_number_from_name(batch_name)
    num = int(batch_number or 0) or parsed or 1
    return f"Sample {num}"


def parse_batch_number_from_name(name: str) -> int | None:
    m = re.match(r"^Batch\s+(\d+)$", str(name).strip(), re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)", str(name))
    if m:
        return int(m.group(1))
    return None


def _next_batch_number(registry: dict[str, list[dict[str, Any]]], group: str) -> int:
    numbers = []
    for entry in registry.get(group, []):
        try:
            numbers.append(int(entry.get("batch_number", 0)))
        except (TypeError, ValueError):
            pass
        parsed = parse_batch_number_from_name(str(entry.get("batch_name", "")))
        if parsed:
            numbers.append(parsed)
    return max(numbers, default=0) + 1


def _canonical_batch_number_from_name(batch_name: str) -> int | None:
    """Return N when batch_name is exactly 'Batch N' (case-insensitive)."""
    m = re.match(r"^Batch\s+(\d+)$", str(batch_name).strip(), re.IGNORECASE)
    return int(m.group(1)) if m else None


def allocate_next_batch(
    root: Path,
    group: str,
    *,
    preferred_name: str | None = None,
) -> tuple[int, str]:
    """Next unused batch number and a non-colliding display name."""
    root = Path(root).resolve()
    registry = _load_batches_registry(root)
    existing_names = {
        sanitize_batch_name(str(b.get("batch_name", "")))
        for b in registry.get(group, [])
    }
    num = _next_batch_number(registry, group)
    if preferred_name:
        name = sanitize_batch_name(preferred_name)
        parsed = _canonical_batch_number_from_name(name)
        if parsed is not None:
            num = parsed
        base = name
        suffix = 2
        while sanitize_batch_name(name) in existing_names:
            name = sanitize_batch_name(f"{base}_{suffix}")
            suffix += 1
    else:
        name = display_batch_name(num)
        while sanitize_batch_name(name) in existing_names:
            num += 1
            name = display_batch_name(num)
    return num, name


def _batch_id(group: str, batch_number: int) -> str:
    return f"{group}_B{int(batch_number):03d}"


def _empty_batch_stats() -> dict[str, int | bool]:
    return {
        "video_file_count": 0,
        "image_file_count": 0,
        "contains_video": False,
        "data_file_count": 0,
        "contains_data": False,
    }


def _normalize_batch_record(entry: dict[str, Any], group: str) -> dict[str, Any]:
    name = str(entry.get("batch_name", "")).strip()
    canonical = _canonical_batch_number_from_name(name) if name else None
    bn = entry.get("batch_number")
    if canonical is not None:
        batch_number = canonical
    elif bn is None or str(bn).strip() == "":
        batch_number = parse_batch_number_from_name(name) or 1
    else:
        try:
            batch_number = int(bn)
        except (TypeError, ValueError):
            batch_number = parse_batch_number_from_name(name) or 1
    if not name:
        name = display_batch_name(batch_number)
    out = {
        "group": str(entry.get("group", group)),
        "condition_group_id": str(entry.get("condition_group_id", group)),
        "breed": str(entry.get("breed") or entry.get("group", group)),
        "batch_number": batch_number,
        "batch_name": sanitize_batch_name(name),
        "batch_id": str(entry.get("batch_id", _batch_id(group, batch_number))),
        "contains_video": bool(entry.get("contains_video", False)),
        "video_file_count": int(entry.get("video_file_count", 0) or 0),
        "image_file_count": int(entry.get("image_file_count", 0) or 0),
        "data_file_count": int(
            entry.get(
                "data_file_count",
                int(entry.get("video_file_count", 0) or 0)
                + int(entry.get("image_file_count", 0) or 0),
            )
            or 0
        ),
        "contains_data": bool(
            entry.get(
                "contains_data",
                int(entry.get("video_file_count", 0) or 0)
                + int(entry.get("image_file_count", 0) or 0)
                > 0,
            )
        ),
        "created_date": str(entry.get("created_date", entry.get("created", _utc_now_iso()))),
        "renamed_date": entry.get("renamed_date"),
        "notes": str(entry.get("notes", "")),
    }
    if entry.get("auto_generated_name") is not None:
        out["auto_generated_name"] = bool(entry.get("auto_generated_name"))
    if entry.get("source_filename"):
        out["source_filename"] = str(entry.get("source_filename"))
    return out


def ensure_batch_dirs(root: Path, group: str, batch_name: str) -> None:
    root = Path(root).resolve()
    folder = sanitize_batch_name(batch_name)
    (root / RAW_DIR / group / folder).mkdir(parents=True, exist_ok=True)
    (root / PROCESSED_DIR / group / folder).mkdir(parents=True, exist_ok=True)


def list_batches(root: Path, group: str) -> list[dict[str, Any]]:
    registry = _load_batches_registry(root)
    batches = [_normalize_batch_record(b, group) for b in registry.get(group, [])]
    return sorted(batches, key=lambda b: int(b["batch_number"]))


def get_batch_by_name(root: Path, group: str, batch_name: str) -> dict[str, Any] | None:
    safe = sanitize_batch_name(batch_name)
    for batch in list_batches(root, group):
        if sanitize_batch_name(batch.get("batch_name", "")) == safe:
            return batch
    return None


def get_batch_by_number(root: Path, group: str, batch_number: int) -> dict[str, Any] | None:
    for batch in list_batches(root, group):
        if int(batch.get("batch_number", -1)) == int(batch_number):
            return batch
    return None


def create_batch(
    root: Path,
    group: str,
    batch_name: str | None = None,
    *,
    batch_number: int | None = None,
) -> dict[str, Any]:
    from actintrack_app.condition_group_manager import get_condition_group_name

    root = Path(root).resolve()
    registry = _load_batches_registry(root)
    group_batches = list(registry.get(group, []))
    num = int(batch_number) if batch_number is not None else _next_batch_number(registry, group)
    if any(int(b.get("batch_number", -1)) == num for b in group_batches):
        raise ValueError(f"Sample number {num} already exists in {group}")

    name = sanitize_batch_name(batch_name or display_batch_name(num))
    if any(sanitize_batch_name(b.get("batch_name", "")) == name for b in group_batches):
        raise ValueError(f"Sample name already exists in {group}: {name}")

    display = get_condition_group_name(root, group)
    record = {
        "group": group,
        "condition_group_id": group,
        "breed": display,
        "batch_number": num,
        "batch_name": name,
        "batch_id": _batch_id(group, num),
        **_empty_batch_stats(),
        "created_date": _utc_now_iso(),
        "renamed_date": None,
        "notes": "",
    }
    group_batches.append(record)
    registry[group] = group_batches
    _save_batches_registry(root, registry)
    ensure_batch_dirs(root, group, name)
    return record


def rename_batch(
    root: Path,
    group: str,
    old_name: str,
    new_name: str,
) -> dict[str, Any]:
    from actintrack_app.metadata import load_samples_csv, save_samples_csv
    from actintrack_app.utils import SAMPLES_CSV

    root = Path(root).resolve()
    old_safe = sanitize_batch_name(old_name)
    new_safe = sanitize_batch_name(new_name)
    if old_safe == new_safe:
        batch = get_batch_by_name(root, group, old_safe)
        if batch:
            return batch
        raise ValueError(f"Sample not found: {old_name}")

    if get_batch_by_name(root, group, new_safe):
        raise ValueError(f"Another sample already uses the name: {new_safe}")

    registry = _load_batches_registry(root)
    group_batches = list(registry.get(group, []))
    found = None
    for entry in group_batches:
        if sanitize_batch_name(entry.get("batch_name", "")) == old_safe:
            found = _normalize_batch_record(entry, group)
            entry["batch_name"] = new_safe
            entry["renamed_date"] = _utc_now_iso()
            entry["auto_generated_name"] = False
            break
    if found is None:
        raise ValueError(f"Sample not found in registry: {old_name}")

    _save_batches_registry(root, registry)

    old_raw = root / RAW_DIR / group / old_safe
    new_raw = root / RAW_DIR / group / new_safe
    old_proc = root / PROCESSED_DIR / group / old_safe
    new_proc = root / PROCESSED_DIR / group / new_safe
    if old_raw.exists():
        new_raw.parent.mkdir(parents=True, exist_ok=True)
        if new_raw.exists():
            raise ValueError(f"Cannot rename: destination folder exists: {new_safe}")
        old_raw.rename(new_raw)
    else:
        ensure_batch_dirs(root, group, new_safe)

    if old_proc.exists() and not new_proc.exists():
        old_proc.rename(new_proc)

    samples_path = root / METADATA_DIR / SAMPLES_CSV
    df = load_samples_csv(samples_path)
    mask = (df["group"] == group) & (
        df["batch_name"].astype(str).apply(sanitize_batch_name) == old_safe
    )
    for idx in df.index[mask]:
        stored = str(df.at[idx, "stored_path"])
        old_part = f"{RAW_DIR}/{group}/{old_safe}/"
        new_part = f"{RAW_DIR}/{group}/{new_safe}/"
        if old_part in stored:
            df.at[idx, "stored_path"] = stored.replace(old_part, new_part, 1)
        df.at[idx, "batch_name"] = new_safe
    save_samples_csv(samples_path, df)
    found["batch_name"] = new_safe
    found["renamed_date"] = _utc_now_iso()
    return found


def ensure_default_batch(root: Path, group: str) -> dict[str, Any]:
    batches = list_batches(root, group)
    if batches:
        return batches[0]
    return create_batch(root, group, display_batch_name(1), batch_number=1)


def create_batch_for_video_import(root: Path, group: str) -> dict[str, Any]:
    """New batch per video import (default behavior)."""
    num, name = allocate_next_batch(root, group)
    return create_batch(root, group, name, batch_number=num)


def repair_batch_registry(root: Path) -> bool:
    """Fix batch_number fields and persist when names use 'Batch N' format."""
    root = Path(root).resolve()
    registry = _load_batches_registry(root)
    changed = False
    for group, entries in list(registry.items()):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("batch_name", "")).strip()
            canonical = _canonical_batch_number_from_name(name)
            if canonical is None:
                continue
            try:
                stored = int(entry.get("batch_number"))
            except (TypeError, ValueError):
                stored = None
            if stored != canonical:
                entry["batch_number"] = canonical
                bid = str(entry.get("batch_id", ""))
                if bid and "_B" in bid:
                    entry["batch_id"] = _batch_id(group, canonical)
                changed = True
    if changed:
        _save_batches_registry(root, registry)
    return changed


def batch_has_video(root: Path, group: str, batch_name: str) -> bool:
    from actintrack_app.metadata import load_samples_csv
    from actintrack_app.utils import SAMPLES_CSV

    df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)
    safe = sanitize_batch_name(batch_name)
    sub = df[
        (df["group"] == group)
        & (df["batch_name"].astype(str).apply(sanitize_batch_name) == safe)
    ]
    if sub.empty:
        return False
    if "is_video" in sub.columns:
        return (sub["is_video"].astype(str).str.lower() == "true").any()
    return (sub["file_type"].astype(str) == "video").any()


def refresh_batch_stats(root: Path, group: str, batch_name: str) -> None:
    from actintrack_app.metadata import load_samples_csv
    from actintrack_app.utils import SAMPLES_CSV

    root = Path(root).resolve()
    df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)
    safe = sanitize_batch_name(batch_name)
    sub = df[
        (df["group"] == group)
        & (df["batch_name"].astype(str).apply(sanitize_batch_name) == safe)
    ]
    video_n = 0
    image_n = 0
    for _, row in sub.iterrows():
        is_vid = str(row.get("is_video", "")).lower() == "true" or str(
            row.get("file_type", "")
        ) == "video"
        if is_vid:
            video_n += 1
        else:
            image_n += 1

    registry = _load_batches_registry(root)
    updated = False
    for entry in registry.get(group, []):
        if sanitize_batch_name(entry.get("batch_name", "")) == safe:
            entry["video_file_count"] = video_n
            entry["image_file_count"] = image_n
            entry["contains_video"] = video_n > 0
            entry["data_file_count"] = video_n + image_n
            entry["contains_data"] = (video_n + image_n) > 0
            updated = True
            break
    if not updated and not sub.empty:
        row = sub.iloc[0]
        batch_id = str(row.get("batch_id", "")).strip()
        batch_number = None
        try:
            batch_number = int(row.get("batch_number", 0) or 0) or None
        except (TypeError, ValueError):
            pass
        if batch_id:
            register_batch_from_samples(
                root,
                group,
                batch_name,
                batch_id,
                batch_number=batch_number,
            )
            registry = _load_batches_registry(root)
            for entry in registry.get(group, []):
                if sanitize_batch_name(entry.get("batch_name", "")) == safe:
                    entry["video_file_count"] = video_n
                    entry["image_file_count"] = image_n
                    entry["contains_video"] = video_n > 0
                    entry["data_file_count"] = video_n + image_n
                    entry["contains_data"] = (video_n + image_n) > 0
                    break
    _save_batches_registry(root, registry)


def batch_has_samples(root: Path, group: str, batch_name: str) -> bool:
    from actintrack_app.metadata import load_samples_csv
    from actintrack_app.utils import SAMPLES_CSV

    df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)
    safe = sanitize_batch_name(batch_name)
    sub = df[
        (df["group"] == group)
        & (df["batch_name"].astype(str).apply(sanitize_batch_name) == safe)
    ]
    return not sub.empty


def all_workspace_condition_groups(root: Path) -> list[str]:
    """All condition group IDs in the workspace."""
    from actintrack_app.condition_group_manager import list_condition_group_ids

    return list_condition_group_ids(root)


def clear_batches_registry_for_groups(root: Path, groups: list[str] | None = None) -> int:
    """Remove all batch entries for the given groups (or every known group)."""
    root = Path(root).resolve()
    registry = _load_batches_registry(root)
    target = set(groups) if groups is not None else set(_load_batches_registry(root).keys()) | set(
        all_workspace_condition_groups(root)
    )
    removed = 0
    for group in target:
        removed += len(registry.get(group, []))
        registry[group] = []
    _save_batches_registry(root, registry)
    return removed


def reset_batches_registry_workspace(root: Path) -> None:
    """Empty the sample registry after a full workspace purge."""
    _save_batches_registry(root, {})


def prune_registry_batches_without_samples(
    root: Path, group: str, *, remove_empty_folders: bool = True
) -> int:
    """Explicit repair only: remove registry entries with no samples.csv rows.

    Do not call during normal refresh or import — empty samples are intentional
    registry entries and must remain visible until the user deletes them.
    """
    root = Path(root).resolve()
    removed = 0
    for batch in list(list_batches(root, group)):
        name = str(batch["batch_name"])
        if batch_has_samples(root, group, name):
            continue
        if remove_batch_from_registry(root, group, name):
            removed += 1
        if remove_empty_folders:
            remove_batch_folders(
                root, group, name, remove_raw=True, remove_processed=True
            )
    return removed


def prune_all_groups_without_samples(root: Path) -> dict[str, int]:
    """Explicit repair only: prune registry entries with no samples.csv rows.

    Not used during routine workspace operations. Empty user-created samples
    are stored in batches.json without samples.csv rows by design.
    """
    from actintrack_app.metadata import load_samples_csv
    from actintrack_app.utils import SAMPLES_CSV

    root = Path(root).resolve()
    df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)
    counts: dict[str, int] = {}
    for group in all_workspace_condition_groups(root):
        if df[df["group"] == group].empty:
            n = prune_registry_batches_without_samples(root, group)
            if n:
                counts[group] = n
    return counts


def list_empty_batches(root: Path, group: str) -> list[dict[str, Any]]:
    """All registry batches in a condition group that have no samples in samples.csv."""
    root = Path(root).resolve()
    batches = list_batches(root, group)
    return [b for b in batches if not batch_has_samples(root, group, str(b["batch_name"]))]


def remove_batch_from_registry(root: Path, group: str, batch_name: str) -> bool:
    root = Path(root).resolve()
    safe = sanitize_batch_name(batch_name)
    registry = _load_batches_registry(root)
    before = len(registry.get(group, []))
    registry[group] = [
        b
        for b in registry.get(group, [])
        if sanitize_batch_name(b.get("batch_name", "")) != safe
    ]
    removed = before != len(registry.get(group, []))
    if removed:
        _save_batches_registry(root, registry)
    return removed


def remove_batch_folders(
    root: Path,
    group: str,
    batch_name: str,
    *,
    remove_raw: bool = True,
    remove_processed: bool = True,
) -> list[str]:
    """Remove batch directories under raw/ and/or processed/. Returns paths removed."""
    import shutil

    root = Path(root).resolve()
    safe = sanitize_batch_name(batch_name)
    removed: list[str] = []
    if remove_raw:
        path = root / RAW_DIR / group / safe
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            removed.append(str(path))
    if remove_processed:
        path = root / PROCESSED_DIR / group / safe
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            removed.append(str(path))
    return removed


def delete_empty_batch(
    root: Path,
    group: str,
    batch_name: str,
    *,
    remove_raw_folder: bool = True,
) -> None:
    from actintrack_app.metadata import load_samples_csv
    from actintrack_app.utils import SAMPLES_CSV

    root = Path(root).resolve()
    safe = sanitize_batch_name(batch_name)
    df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)
    sub = df[
        (df["group"] == group)
        & (df["batch_name"].astype(str).apply(sanitize_batch_name) == safe)
    ]
    if not sub.empty:
        raise ValueError(
            f"Sample '{safe}' still has {len(sub)} data file(s). "
            "Use Complete Sample Purge to remove the sample and all its data."
        )

    if not remove_batch_from_registry(root, group, safe):
        raise ValueError(f"Sample not found in registry: {batch_name}")
    remove_batch_folders(
        root,
        group,
        safe,
        remove_raw=remove_raw_folder,
        remove_processed=True,
    )


def sync_registry_from_samples(root: Path) -> int:
    """Add missing batches.json entries from samples.csv; never removes entries."""
    from actintrack_app.metadata import load_samples_csv
    from actintrack_app.utils import SAMPLES_CSV, data_id_prefix_for_group

    root = Path(root).resolve()
    df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)
    if df.empty:
        return 0

    registry = _load_batches_registry(root)
    existing = {
        (str(g), sanitize_batch_name(str(b.get("batch_name", ""))))
        for g, batches in registry.items()
        for b in batches
        if isinstance(b, dict)
    }
    added = 0
    seen: set[tuple[str, str]] = set()
    for _, row in df.iterrows():
        group = str(row.get("group", "")).strip()
        batch_name = str(row.get("batch_name", "")).strip()
        if not group or not batch_name:
            continue
        safe = sanitize_batch_name(batch_name)
        key = (group, safe)
        if key in seen:
            continue
        seen.add(key)
        if key in existing:
            continue
        batch_number = None
        try:
            batch_number = int(row.get("batch_number", 0) or 0) or None
        except (TypeError, ValueError):
            pass
        batch_id = str(row.get("batch_id", "")).strip()
        if not batch_id:
            prefix = data_id_prefix_for_group(group)
            num = batch_number or parse_batch_number_from_name(safe) or 1
            batch_id = f"{prefix}_B{num:03d}"
        register_batch_from_samples(
            root,
            group,
            batch_name,
            batch_id,
            batch_number=batch_number,
        )
        existing.add(key)
        added += 1
    return added


def register_batch_from_samples(
    root: Path,
    group: str,
    batch_name: str,
    batch_id: str,
    batch_number: int | None = None,
) -> None:
    registry = _load_batches_registry(root)
    group_batches = list(registry.get(group, []))
    safe = sanitize_batch_name(batch_name)
    num = batch_number or parse_batch_number_from_name(safe) or 1
    if not any(
        sanitize_batch_name(b.get("batch_name", "")) == safe for b in group_batches
    ):
        group_batches.append(
            _normalize_batch_record(
                {
                    "batch_id": batch_id,
                    "batch_name": safe,
                    "batch_number": num,
                    "created_date": _utc_now_iso(),
                },
                group,
            )
        )
        registry[group] = group_batches
        _save_batches_registry(root, registry)
    ensure_batch_dirs(root, group, safe)


def next_frame_number_in_batch(root: Path, group: str, batch_name: str) -> int:
    from actintrack_app.metadata import load_samples_csv
    from actintrack_app.utils import SAMPLES_CSV

    df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)
    safe = sanitize_batch_name(batch_name)
    sub = df[
        (df["group"] == group)
        & (df["batch_name"].astype(str).apply(sanitize_batch_name) == safe)
    ]
    numbers = []
    for _, row in sub.iterrows():
        try:
            numbers.append(int(row.get("frame_number", 0)))
        except (TypeError, ValueError):
            pass
    return max(numbers, default=-1) + 1
