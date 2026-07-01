"""User-defined Condition Groups with stable IDs and editable display names.

Authoritative identity: ``condition_group_id`` (e.g. ``cg_a1b2c3d4``).
On-disk folders under ``raw/``, ``processed/``, and ``previews/`` use the ID.
Display names live in ``metadata/condition_groups.json`` only.

Compatibility bridge: data/registry rows may still carry ``breed`` / ``group``
with the human display name for legacy readers. New logic must resolve and
filter by ``condition_group_id``.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from actintrack_app.utils import (
    CONDITION_GROUPS_JSON,
    METADATA_DIR,
    PREVIEWS_DIR,
    PROCESSED_DIR,
    RAW_DIR,
    SAMPLES_CSV,
)

_INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_ID_PREFIX = "cg_"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ConditionGroupRecord:
    id: str
    name: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConditionGroupRecord:
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            created_at=str(data.get("created_at", _utc_now_iso())),
            updated_at=str(data.get("updated_at", _utc_now_iso())),
        )


def _condition_groups_path(root: Path) -> Path:
    return Path(root).resolve() / METADATA_DIR / CONDITION_GROUPS_JSON


def new_condition_group_id() -> str:
    return f"{_ID_PREFIX}{uuid.uuid4().hex[:8]}"


def legacy_name_to_condition_group_id(name: str) -> str:
    """Deterministic ID for migrating a legacy name-based group key."""
    digest = hashlib.sha256(str(name).strip().encode("utf-8")).hexdigest()[:8]
    return f"{_ID_PREFIX}{digest}"


def is_condition_group_id(value: str) -> bool:
    text = str(value).strip()
    return text.startswith(_ID_PREFIX) and len(text) > len(_ID_PREFIX)


def normalize_condition_group_name(name: str) -> str:
    """Trim and validate a user-facing Condition Group name."""
    text = str(name).strip()
    if not text:
        raise ValueError("Condition Group name cannot be blank.")
    if _INVALID_NAME.search(text):
        raise ValueError(
            'Condition Group name cannot contain characters: < > : " / \\ | ? *'
        )
    return text


def _name_key(name: str) -> str:
    return normalize_condition_group_name(name).casefold()


def _load_groups_payload(root: Path) -> dict[str, Any]:
    path = _condition_groups_path(root)
    if not path.is_file():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _parse_group_records(raw_groups: Any) -> list[ConditionGroupRecord]:
    if not isinstance(raw_groups, list):
        return []
    out: list[ConditionGroupRecord] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for item in raw_groups:
        if isinstance(item, str):
            name = str(item).strip()
            if not name:
                continue
            nk = name.casefold()
            if nk in seen_names:
                continue
            seen_names.add(nk)
            now = _utc_now_iso()
            gid = legacy_name_to_condition_group_id(name)
            if gid in seen_ids:
                gid = new_condition_group_id()
            seen_ids.add(gid)
            out.append(ConditionGroupRecord(id=gid, name=name, created_at=now, updated_at=now))
            continue
        if not isinstance(item, dict):
            continue
        gid = str(item.get("id", "")).strip()
        name = str(item.get("name", "")).strip()
        if not gid or not name:
            continue
        nk = name.casefold()
        if gid in seen_ids or nk in seen_names:
            continue
        seen_ids.add(gid)
        seen_names.add(nk)
        out.append(
            ConditionGroupRecord(
                id=gid,
                name=name,
                created_at=str(item.get("created_at", _utc_now_iso())),
                updated_at=str(item.get("updated_at", _utc_now_iso())),
            )
        )
    return out


def _save_group_records(root: Path, records: list[ConditionGroupRecord]) -> None:
    root = Path(root).resolve()
    path = _condition_groups_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "groups": [r.to_dict() for r in records],
        "updated_at": _utc_now_iso(),
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def init_empty_condition_groups(root: Path) -> None:
    """Write an empty Condition Group list for a brand-new workspace."""
    _save_group_records(root, [])


def list_condition_group_records(root: Path) -> list[ConditionGroupRecord]:
    root = Path(root).resolve()
    if not _condition_groups_path(root).is_file():
        ensure_condition_groups_initialized(root)
    return _parse_group_records(_load_groups_payload(root).get("groups"))


def list_condition_groups(root: Path) -> list[str]:
    """Display names in workspace order (UI convenience)."""
    return [r.name for r in list_condition_group_records(root)]


def list_condition_group_ids(root: Path) -> list[str]:
    return [r.id for r in list_condition_group_records(root)]


def get_condition_group_record(root: Path, group_id: str) -> ConditionGroupRecord | None:
    gid = str(group_id).strip()
    for record in list_condition_group_records(root):
        if record.id == gid:
            return record
    return None


def get_condition_group_name(root: Path, group_id: str) -> str:
    record = get_condition_group_record(root, group_id)
    if record:
        return record.name
    return str(group_id)


def resolve_condition_group_id(root: Path, group_id_or_name: str) -> str | None:
    """Resolve a stable ID from an ID or display name (case-insensitive)."""
    text = str(group_id_or_name).strip()
    if not text:
        return None
    if is_condition_group_id(text):
        for record in list_condition_group_records(root):
            if record.id == text:
                return record.id
        return None
    target = text.casefold()
    for record in list_condition_group_records(root):
        if record.name.casefold() == target:
            return record.id
    return None


def resolve_condition_group_name(root: Path, group_id_or_name: str) -> str | None:
    gid = resolve_condition_group_id(root, group_id_or_name)
    if not gid:
        return None
    return get_condition_group_name(root, gid)


def condition_group_exists(root: Path, group_id_or_name: str) -> bool:
    return resolve_condition_group_id(root, group_id_or_name) is not None


def group_storage_key(group_id: str) -> str:
    """Folder segment for raw/processed/previews (stable ID)."""
    return str(group_id).strip()


def ensure_condition_group_dirs(root: Path, group_id: str) -> None:
    root = Path(root).resolve()
    key = group_storage_key(group_id)
    for sub in (RAW_DIR, PROCESSED_DIR, PREVIEWS_DIR):
        (root / sub / key).mkdir(parents=True, exist_ok=True)


def discover_legacy_group_keys(root: Path) -> list[str]:
    """Legacy name-based group keys from registry, data index, and folders."""
    from actintrack_app.metadata import load_samples_csv
    from actintrack_app.schema_compat import load_sample_registry_raw

    root = Path(root).resolve()
    keys: set[str] = set()

    registry = load_sample_registry_raw(root)
    keys.update(str(k).strip() for k in registry.keys() if str(k).strip())

    for csv_name in (SAMPLES_CSV, "data_files.csv"):
        samples_path = root / METADATA_DIR / csv_name
        if samples_path.is_file():
            df = load_samples_csv(samples_path)
            if not df.empty:
                if "condition_group_id" in df.columns:
                    keys.update(
                        str(g).strip()
                        for g in df["condition_group_id"].astype(str).tolist()
                        if str(g).strip()
                    )
                col = "breed" if "breed" in df.columns else "group"
                if col in df.columns:
                    keys.update(
                        str(g).strip()
                        for g in df[col].astype(str).tolist()
                        if str(g).strip()
                    )

    for parent_name in (RAW_DIR, PROCESSED_DIR, PREVIEWS_DIR):
        parent = root / parent_name
        if parent.is_dir():
            for child in parent.iterdir():
                if child.is_dir() and not child.name.startswith("."):
                    keys.add(child.name)

    return sorted(keys)


def row_condition_group_id(row: dict[str, Any]) -> str:
    """Authoritative group ID from a data-file row dict."""
    cid = str(row.get("condition_group_id", "")).strip()
    if cid:
        return cid
    legacy = str(row.get("group") or row.get("breed") or "").strip()
    return legacy


def sync_data_file_group_bridge(
    row: dict[str, Any], *, group_id: str, display_name: str
) -> dict[str, Any]:
    """Set authoritative ID and display-name bridge fields on a row dict."""
    out = dict(row)
    out["condition_group_id"] = group_id
    out["breed"] = display_name
    out["group"] = group_id
    return out


def _migrate_registry_to_ids(
    root: Path,
    id_by_legacy_key: dict[str, str],
    name_by_id: dict[str, str],
) -> None:
    from actintrack_app.schema_compat import load_sample_registry_as_v1, save_sample_registry

    registry = load_sample_registry_as_v1(root)
    if not registry:
        return

    new_registry: dict[str, list[dict[str, Any]]] = {}
    for legacy_key, entries in registry.items():
        legacy = str(legacy_key).strip()
        gid = id_by_legacy_key.get(legacy)
        if not gid:
            if is_condition_group_id(legacy):
                gid = legacy
            else:
                gid = legacy_name_to_condition_group_id(legacy)
                id_by_legacy_key[legacy] = gid
                name_by_id.setdefault(gid, legacy)
        display = name_by_id.get(gid, legacy)
        bucket = list(new_registry.get(gid, []))
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            e = dict(entry)
            e["group"] = gid
            e["breed"] = display
            e["condition_group_id"] = gid
            try:
                num = int(e.get("batch_number", 1) or 1)
            except (TypeError, ValueError):
                num = 1
            e["batch_id"] = f"{gid}_B{int(num):03d}"
            bucket.append(e)
        new_registry[gid] = bucket
    save_sample_registry(root, new_registry)


def _migrate_data_files_to_ids(
    root: Path,
    id_by_legacy_key: dict[str, str],
    name_by_id: dict[str, str],
) -> None:
    from actintrack_app.metadata import load_samples_csv, save_samples_csv

    samples_path = root / METADATA_DIR / SAMPLES_CSV
    df = load_samples_csv(samples_path)
    if df.empty:
        return

    if "condition_group_id" not in df.columns:
        df["condition_group_id"] = ""

    changed = False
    for idx in df.index:
        row = df.loc[idx].to_dict()
        legacy_key = ""
        cid = str(row.get("condition_group_id", "")).strip()
        if cid and is_condition_group_id(cid):
            gid = cid
            legacy_key = next(
                (k for k, v in id_by_legacy_key.items() if v == gid),
                "",
            )
        else:
            legacy_key = str(row.get("group") or row.get("breed") or "").strip()
            gid = id_by_legacy_key.get(legacy_key, "")
            if not gid:
                if is_condition_group_id(legacy_key):
                    gid = legacy_key
                elif legacy_key:
                    gid = legacy_name_to_condition_group_id(legacy_key)
                    id_by_legacy_key[legacy_key] = gid
                    name_by_id.setdefault(gid, legacy_key)
        if not gid:
            continue
        display = name_by_id.get(gid, legacy_key or get_condition_group_name(root, gid))

        stored = str(df.at[idx, "stored_path"])
        for legacy, new_id in id_by_legacy_key.items():
            if legacy == new_id:
                continue
            for sub in (RAW_DIR, PROCESSED_DIR, PREVIEWS_DIR):
                old_part = f"{sub}/{legacy}/"
                new_part = f"{sub}/{new_id}/"
                if old_part in stored:
                    stored = stored.replace(old_part, new_part, 1)
                    changed = True
        if stored != str(df.at[idx, "stored_path"]):
            df.at[idx, "stored_path"] = stored
            changed = True

        if str(df.at[idx, "condition_group_id"]) != gid:
            df.at[idx, "condition_group_id"] = gid
            changed = True
        if "group" in df.columns and str(df.at[idx, "group"]) != gid:
            df.at[idx, "group"] = gid
            changed = True
        if "breed" in df.columns and str(df.at[idx, "breed"]) != display:
            df.at[idx, "breed"] = display
            changed = True
        try:
            num = int(df.at[idx, "batch_number"])
        except (TypeError, ValueError):
            num = 1
        new_bid = f"{gid}_B{int(num):03d}"
        if "batch_id" in df.columns and str(df.at[idx, "batch_id"]) != new_bid:
            df.at[idx, "batch_id"] = new_bid
            changed = True

    if changed:
        save_samples_csv(samples_path, df)


def _migrate_group_folders(
    root: Path,
    id_by_legacy_key: dict[str, str],
) -> None:
    root = Path(root).resolve()
    for legacy, gid in id_by_legacy_key.items():
        if legacy == gid:
            continue
        for sub in (RAW_DIR, PROCESSED_DIR, PREVIEWS_DIR):
            old_path = root / sub / legacy
            new_path = root / sub / gid
            if old_path.is_dir() and not new_path.exists():
                new_path.parent.mkdir(parents=True, exist_ok=True)
                old_path.rename(new_path)
            elif not new_path.exists():
                new_path.mkdir(parents=True, exist_ok=True)


def _migrate_crop_metadata_display_names(
    root: Path,
    name_by_id: dict[str, str],
) -> None:
    from actintrack_app.metadata import load_crop_metadata, save_crop_metadata
    from actintrack_app.utils import CROP_METADATA_JSON

    crop_path = root / METADATA_DIR / CROP_METADATA_JSON
    if not crop_path.is_file():
        return
    crop = load_crop_metadata(crop_path)
    samples = crop.get("samples") or crop.get("data_files") or {}
    changed = False
    for ann in samples.values():
        if not isinstance(ann, dict):
            continue
        gid = str(ann.get("condition_group_id") or ann.get("group") or "").strip()
        if is_condition_group_id(gid):
            display = name_by_id.get(gid, "")
            if display and str(ann.get("breed", "")) != display:
                ann["breed"] = display
                changed = True
            if str(ann.get("group", "")) != gid:
                ann["group"] = gid
                changed = True
            if str(ann.get("condition_group_id", "")) != gid:
                ann["condition_group_id"] = gid
                changed = True
    if changed:
        save_crop_metadata(crop_path, crop)


def migrate_workspace_condition_groups_to_ids(root: Path) -> bool:
    """Upgrade name-based groups to stable IDs. Returns True if migration ran."""
    root = Path(root).resolve()
    payload = _load_groups_payload(root)
    raw_groups = payload.get("groups")
    records = _parse_group_records(raw_groups) if raw_groups is not None else []

    id_by_legacy_key: dict[str, str] = {}
    name_by_id: dict[str, str] = {r.id: r.name for r in records}

    for record in records:
        id_by_legacy_key[record.name] = record.id
        id_by_legacy_key[record.id] = record.id

    legacy_keys = discover_legacy_group_keys(root)
    for legacy in legacy_keys:
        if is_condition_group_id(legacy):
            if legacy not in name_by_id:
                name_by_id[legacy] = legacy
            id_by_legacy_key[legacy] = legacy
            continue
        if legacy in id_by_legacy_key:
            continue
        gid = legacy_name_to_condition_group_id(legacy)
        id_by_legacy_key[legacy] = gid
        name_by_id.setdefault(gid, legacy)
        if not any(r.id == gid for r in records):
            now = _utc_now_iso()
            records.append(
                ConditionGroupRecord(id=gid, name=legacy, created_at=now, updated_at=now)
            )

    needs_object_format = not raw_groups or any(isinstance(g, str) for g in raw_groups)
    from actintrack_app.schema_compat import load_sample_registry_as_v1

    registry = load_sample_registry_as_v1(root)
    needs_registry = any(not is_condition_group_id(str(k)) for k in registry.keys())
    samples_path = root / METADATA_DIR / SAMPLES_CSV
    if samples_path.is_file() or (root / METADATA_DIR / "data_files.csv").is_file():
        from actintrack_app.metadata import load_samples_csv

        df = load_samples_csv(samples_path)
        if not df.empty and (
            "condition_group_id" not in df.columns
            or df["condition_group_id"].astype(str).str.strip().eq("").any()
        ):
            needs_registry = True

    if not needs_object_format and not needs_registry:
        return False

    seen_name: set[str] = set()
    deduped: list[ConditionGroupRecord] = []
    for record in records:
        nk = record.name.casefold()
        if nk in seen_name:
            continue
        seen_name.add(nk)
        deduped.append(record)

    _save_group_records(root, deduped)
    _migrate_registry_to_ids(root, id_by_legacy_key, name_by_id)
    _migrate_data_files_to_ids(root, id_by_legacy_key, name_by_id)
    _migrate_group_folders(root, id_by_legacy_key)
    _migrate_crop_metadata_display_names(root, name_by_id)
    return True


def ensure_condition_groups_initialized(root: Path) -> list[ConditionGroupRecord]:
    """Ensure condition_groups.json exists and workspace uses stable IDs."""
    root = Path(root).resolve()
    path = _condition_groups_path(root)
    if not path.is_file():
        legacy_keys = discover_legacy_group_keys(root)
        records: list[ConditionGroupRecord] = []
        now = _utc_now_iso()
        seen: set[str] = set()
        for legacy in legacy_keys:
            if is_condition_group_id(legacy):
                continue
            nk = legacy.casefold()
            if nk in seen:
                continue
            seen.add(nk)
            gid = legacy_name_to_condition_group_id(legacy)
            records.append(
                ConditionGroupRecord(id=gid, name=legacy, created_at=now, updated_at=now)
            )
        _save_group_records(root, records)
    migrate_workspace_condition_groups_to_ids(root)
    return list_condition_group_records(root)


def create_condition_group(root: Path, name: str) -> ConditionGroupRecord:
    """Add a new empty Condition Group."""
    root = Path(root).resolve()
    display = normalize_condition_group_name(name)
    records = list_condition_group_records(root)
    if any(r.name.casefold() == display.casefold() for r in records):
        raise ValueError(f"A Condition Group named '{display}' already exists.")

    now = _utc_now_iso()
    record = ConditionGroupRecord(
        id=new_condition_group_id(),
        name=display,
        created_at=now,
        updated_at=now,
    )
    records.append(record)
    _save_group_records(root, records)

    from actintrack_app.schema_compat import load_sample_registry_as_v1, save_sample_registry

    registry = load_sample_registry_as_v1(root)
    registry.setdefault(record.id, [])
    save_sample_registry(root, registry)
    ensure_condition_group_dirs(root, record.id)
    return record


def condition_group_has_samples(root: Path, group_id: str) -> bool:
    from actintrack_app.batch_manager import list_batches
    from actintrack_app.metadata import load_samples_csv

    root = Path(root).resolve()
    gid = resolve_condition_group_id(root, group_id)
    if not gid:
        return False
    if list_batches(root, gid):
        return True

    for csv_name in (SAMPLES_CSV, "data_files.csv"):
        samples_path = root / METADATA_DIR / csv_name
        if not samples_path.is_file():
            continue
        df = load_samples_csv(samples_path)
        if df.empty:
            continue
        if "condition_group_id" in df.columns:
            sub = df[df["condition_group_id"].astype(str) == gid]
            if not sub.empty:
                return True
        col = "group"
        if col in df.columns:
            sub = df[df[col].astype(str) == gid]
            if not sub.empty:
                return True
    return False


def delete_empty_condition_group(root: Path, group_id: str) -> None:
    root = Path(root).resolve()
    gid = resolve_condition_group_id(root, group_id)
    if not gid:
        raise ValueError(f"Condition Group not found: {group_id}")
    record = get_condition_group_record(root, gid)
    label = record.name if record else gid
    if condition_group_has_samples(root, gid):
        raise ValueError(
            f"Cannot delete '{label}' because it still has Samples or Data. "
            "Move or delete those Samples first."
        )

    records = [r for r in list_condition_group_records(root) if r.id != gid]
    _save_group_records(root, records)

    from actintrack_app.schema_compat import load_sample_registry_as_v1, save_sample_registry

    registry = load_sample_registry_as_v1(root)
    registry.pop(gid, None)
    save_sample_registry(root, registry)

    key = group_storage_key(gid)
    for sub in (RAW_DIR, PROCESSED_DIR, PREVIEWS_DIR):
        path = root / sub / key
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


def rename_condition_group(root: Path, group_id: str, new_name: str) -> str:
    """Rename display name only; stable ID and folder paths are unchanged."""
    root = Path(root).resolve()
    gid = resolve_condition_group_id(root, group_id)
    if not gid:
        raise ValueError(f"Condition Group not found: {group_id}")
    display = normalize_condition_group_name(new_name)
    records = list_condition_group_records(root)
    for record in records:
        if record.id != gid and record.name.casefold() == display.casefold():
            raise ValueError(f"A Condition Group named '{display}' already exists.")

    updated: list[ConditionGroupRecord] = []
    now = _utc_now_iso()
    for record in records:
        if record.id == gid:
            if record.name == display:
                return display
            updated.append(
                ConditionGroupRecord(
                    id=record.id,
                    name=display,
                    created_at=record.created_at,
                    updated_at=now,
                )
            )
        else:
            updated.append(record)
    _save_group_records(root, updated)

    from actintrack_app.metadata import load_crop_metadata, save_crop_metadata
    from actintrack_app.schema_compat import (
        load_data_files_as_v1_df,
        load_data_files_raw,
        load_sample_registry_as_v1,
        save_data_files,
        save_sample_registry,
        v2_row_to_v1_record,
    )
    from actintrack_app.utils import CROP_METADATA_JSON, SAMPLES_CSV_COLUMNS

    registry = load_sample_registry_as_v1(root)
    for entry in registry.get(gid, []):
        if isinstance(entry, dict):
            entry["breed"] = display
    save_sample_registry(root, registry)

    v2_df = load_data_files_raw(root)
    if not v2_df.empty and "condition_group_id" in v2_df.columns:
        mask = v2_df["condition_group_id"].astype(str) == gid
        if mask.any():
            v2_df.loc[mask, "breed"] = display
            v1_records = [
                v2_row_to_v1_record(r) for r in v2_df.to_dict(orient="records")
            ]
            import pandas as pd

            save_data_files(root, pd.DataFrame(v1_records, columns=SAMPLES_CSV_COLUMNS))

    crop_path = root / METADATA_DIR / CROP_METADATA_JSON
    if crop_path.is_file():
        from actintrack_app.metadata import load_crop_metadata, save_crop_metadata

        crop = load_crop_metadata(crop_path)
        samples = crop.get("samples") or crop.get("data_files") or {}
        changed = False
        for ann in samples.values():
            if not isinstance(ann, dict):
                continue
            if str(ann.get("condition_group_id", ann.get("group", ""))) == gid:
                if str(ann.get("breed", "")) != display:
                    ann["breed"] = display
                    changed = True
        if changed:
            save_crop_metadata(crop_path, crop)

    return display


def data_id_prefix_for_condition_group(root: Path, group_id: str) -> str:
    from actintrack_app.utils import data_id_prefix_for_group

    display = get_condition_group_name(root, group_id)
    return data_id_prefix_for_group(display)


def condition_group_display_name(root: Path, row: dict[str, Any]) -> str:
    """Current user-facing Condition Group name for a data-file row dict."""
    gid = row_condition_group_id(row)
    if not gid:
        return ""
    return get_condition_group_name(root, gid)


def display_export_name_for_row(root: Path, row: dict[str, Any]) -> str:
    """UI-only export label using the current Condition Group display name."""
    from actintrack_app.export_naming import (
        auto_export_name_for_sample,
        resolve_final_export_name,
    )

    custom = str(row.get("custom_export_name", "")).strip()
    stored_auto = str(row.get("auto_export_name", "")).strip()
    if custom:
        return resolve_final_export_name(stored_auto, custom)
    gid = row_condition_group_id(row)
    display = get_condition_group_name(root, gid) if gid else str(row.get("breed", ""))
    is_video = str(row.get("is_video", "")).lower() == "true" or str(
        row.get("file_type", "")
    ) == "video"
    try:
        batch_number = int(row.get("batch_number", 1) or 1)
    except (TypeError, ValueError):
        batch_number = 1
    try:
        frame_number = int(row.get("frame_number", 0) or 0)
    except (TypeError, ValueError):
        frame_number = 0
    return auto_export_name_for_sample(
        group=display,
        batch_number=batch_number,
        is_video=is_video,
        frame_number=frame_number,
    )
