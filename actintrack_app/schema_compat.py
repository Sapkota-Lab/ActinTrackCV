"""Schema v1/v2 compatibility: load, normalize, migrate, and save workspace metadata."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from actintrack_app.domain_models import DataFileRecord, SampleRegistryRecord
from actintrack_app.utils import (
    CROP_METADATA_JSON,
    DATA_FILES_CSV,
    DATA_FILES_CSV_COLUMNS,
    METADATA_DIR,
    SAMPLE_REGISTRY_JSON,
    SAMPLES_CSV,
    SAMPLES_CSV_COLUMNS,
    SCHEMA_V1,
    SCHEMA_V2,
    WORKSPACE_JSON,
)

V1_BACKUP_DIR = ".v1_backup"
BATCHES_JSON = "batches.json"
DRAFT_TRACKING_DIR = "draft_tracking"
DRAFT_OPTICAL_FLOW_DIR = "draft_optical_flow"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def workspace_json_path(root: Path) -> Path:
    return Path(root).resolve() / METADATA_DIR / WORKSPACE_JSON


def read_workspace_schema_version(root: Path) -> int:
    path = workspace_json_path(root)
    if not path.is_file():
        return SCHEMA_V1
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        version = int(data.get("schema_version", SCHEMA_V1))
        return SCHEMA_V2 if version >= SCHEMA_V2 else SCHEMA_V1
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return SCHEMA_V1


def write_workspace_json(root: Path, *, schema_version: int = SCHEMA_V2) -> None:
    path = workspace_json_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": schema_version,
        "migrated_at": _utc_now_iso(),
        "migration_notes": "v1→v2 terminology (breed/sample/data)",
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _data_files_csv_path(root: Path) -> Path:
    return Path(root).resolve() / METADATA_DIR / DATA_FILES_CSV


def _samples_csv_path(root: Path) -> Path:
    return Path(root).resolve() / METADATA_DIR / SAMPLES_CSV


def _sample_registry_path(root: Path) -> Path:
    return Path(root).resolve() / METADATA_DIR / SAMPLE_REGISTRY_JSON


def _batches_json_path(root: Path) -> Path:
    return Path(root).resolve() / METADATA_DIR / BATCHES_JSON


def _coerce_text_df(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    df = df[columns].copy()
    for col in columns:
        df[col] = df[col].fillna("").astype(str)
    return df


def v2_row_to_v1_record(row: dict[str, Any]) -> dict[str, str]:
    return DataFileRecord.from_v1_dict(row).to_v1_dict()


def v1_record_to_v2_row(record: dict[str, Any]) -> dict[str, str]:
    return DataFileRecord.from_v1_dict(record).to_v2_dict()


def load_data_files_raw(root: Path) -> pd.DataFrame:
    """Load persisted data-file table (v2 or v1 file)."""
    root = Path(root).resolve()
    v2_path = _data_files_csv_path(root)
    v1_path = _samples_csv_path(root)
    if v2_path.is_file():
        df = pd.read_csv(v2_path, dtype=str, keep_default_na=False)
        return _coerce_text_df(df, DATA_FILES_CSV_COLUMNS)
    if v1_path.is_file():
        df = pd.read_csv(v1_path, dtype=str, keep_default_na=False)
        records = [v1_record_to_v2_row(r) for r in df.to_dict(orient="records")]
        if not records:
            return _coerce_text_df(pd.DataFrame(), DATA_FILES_CSV_COLUMNS)
        return _coerce_text_df(pd.DataFrame(records), DATA_FILES_CSV_COLUMNS)
    return _coerce_text_df(pd.DataFrame(), DATA_FILES_CSV_COLUMNS)


def load_data_files_as_v1_df(root: Path) -> pd.DataFrame:
    """Load data files and return legacy samples.csv column shape."""
    df = load_data_files_raw(root)
    if df.empty:
        return _coerce_text_df(pd.DataFrame(), SAMPLES_CSV_COLUMNS)
    records = [v2_row_to_v1_record(r) for r in df.to_dict(orient="records")]
    return _coerce_text_df(pd.DataFrame(records), SAMPLES_CSV_COLUMNS)


def save_data_files(root: Path, v1_df: pd.DataFrame) -> None:
    """Persist data files using schema version for this workspace."""
    root = Path(root).resolve()
    version = read_workspace_schema_version(root)
    v1_df = _coerce_text_df(v1_df.copy(), SAMPLES_CSV_COLUMNS)
    if version >= SCHEMA_V2:
        v2_records = [v1_record_to_v2_row(r) for r in v1_df.to_dict(orient="records")]
        v2_df = _coerce_text_df(
            pd.DataFrame(v2_records) if v2_records else pd.DataFrame(),
            DATA_FILES_CSV_COLUMNS,
        )
        path = _data_files_csv_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        v2_df.to_csv(path, index=False)
    else:
        path = _samples_csv_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        v1_df.to_csv(path, index=False)


def load_sample_registry_raw(root: Path) -> dict[str, list[dict[str, Any]]]:
    """Load registry keyed by breed, v2 record shape."""
    root = Path(root).resolve()
    v2_path = _sample_registry_path(root)
    v1_path = _batches_json_path(root)
    if v2_path.is_file():
        try:
            with v2_path.open(encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                out: dict[str, list[dict[str, Any]]] = {}
                for breed, entries in data.items():
                    if not isinstance(entries, list):
                        continue
                    out[str(breed)] = [
                        SampleRegistryRecord.from_v1_dict(e, str(breed)).to_v2_dict()
                        for e in entries
                        if isinstance(e, dict)
                    ]
                return out
        except (json.JSONDecodeError, OSError):
            pass
    if v1_path.is_file():
        try:
            with v1_path.open(encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                out = {}
                for breed, entries in data.items():
                    if not isinstance(entries, list):
                        continue
                    out[str(breed)] = [
                        SampleRegistryRecord.from_v1_dict(e, str(breed)).to_v2_dict()
                        for e in entries
                        if isinstance(e, dict)
                    ]
                return out
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def load_sample_registry_as_v1(root: Path) -> dict[str, list[dict[str, Any]]]:
    """Registry in legacy batches.json entry shape."""
    raw = load_sample_registry_raw(root)
    out: dict[str, list[dict[str, Any]]] = {}
    for breed, entries in raw.items():
        out[breed] = [
            SampleRegistryRecord.from_v1_dict(e, breed).to_v1_dict() for e in entries
        ]
    return out


def save_sample_registry(root: Path, v1_registry: dict[str, list[dict[str, Any]]]) -> None:
    root = Path(root).resolve()
    version = read_workspace_schema_version(root)
    v2_registry: dict[str, list[dict[str, Any]]] = {}
    for breed, entries in v1_registry.items():
        v2_registry[str(breed)] = [
            SampleRegistryRecord.from_v1_dict(e, str(breed)).to_v2_dict()
            for e in entries
            if isinstance(e, dict)
        ]
    if version >= SCHEMA_V2:
        path = _sample_registry_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(v2_registry, f, indent=2)
    else:
        path = _batches_json_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        v1_out = {
            breed: [
                SampleRegistryRecord.from_v1_dict(e, breed).to_v1_dict()
                for e in entries
            ]
            for breed, entries in v1_registry.items()
        }
        with path.open("w", encoding="utf-8") as f:
            json.dump(v1_out, f, indent=2)


def load_crop_metadata_compat(path: Path) -> dict[str, Any]:
    """Load crop metadata; expose unified ``samples`` dict keyed by data_id."""
    if not path.exists():
        return {"samples": {}, "schema_version": SCHEMA_V1}
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"samples": {}, "schema_version": SCHEMA_V1}

    merged: dict[str, Any] = {}
    if isinstance(data.get("data_files"), dict):
        for data_id, ann in data["data_files"].items():
            if isinstance(ann, dict):
                merged[str(data_id)] = _normalize_annotation_keys(ann)
    if isinstance(data.get("samples"), dict):
        for data_id, ann in data["samples"].items():
            if isinstance(ann, dict) and str(data_id) not in merged:
                merged[str(data_id)] = _normalize_annotation_keys(ann)

    version = int(data.get("schema_version", SCHEMA_V1))
    return {"samples": merged, "schema_version": version}


def save_crop_metadata_compat(path: Path, data: dict[str, Any]) -> None:
    root = path.parent.parent if path.parent.name == METADATA_DIR else path.parent
    version = read_workspace_schema_version(root)
    samples = data.get("samples") or data.get("data_files") or {}
    if version >= SCHEMA_V2:
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_V2,
            "data_files": {
                str(k): _normalize_annotation_keys(v)
                for k, v in samples.items()
                if isinstance(v, dict)
            },
        }
    else:
        payload = {
            "samples": {
                str(k): _normalize_annotation_keys(v)
                for k, v in samples.items()
                if isinstance(v, dict)
            },
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _normalize_annotation_keys(ann: dict[str, Any]) -> dict[str, Any]:
    out = dict(ann)
    if "data_id" not in out and out.get("sample_id"):
        sid = str(out["sample_id"])
        if out.get("batch_id") or "_B" in sid:
            pass
        else:
            out.setdefault("data_id", sid)
    if "breed" not in out and out.get("group"):
        out["breed"] = out["group"]
    if "sample_name" not in out and out.get("batch_name"):
        out["sample_name"] = out["batch_name"]
    if "sample_id" not in out and out.get("batch_id"):
        out["sample_id"] = out["batch_id"]
    return out


def draft_tracking_path(root: Path, data_id: str) -> Path:
    return Path(root).resolve() / METADATA_DIR / DRAFT_TRACKING_DIR / f"{data_id}.json"


def resolve_draft_tracking_path(root: Path, data_id: str) -> Path | None:
    """Return existing draft path (v2 data_id name, legacy sample_id filename)."""
    root = Path(root).resolve()
    primary = draft_tracking_path(root, data_id)
    if primary.is_file():
        return primary
    legacy = root / METADATA_DIR / DRAFT_TRACKING_DIR / f"{data_id}.json"
    return legacy if legacy.is_file() else None


def draft_optical_flow_path(root: Path, data_id: str) -> Path:
    return Path(root).resolve() / METADATA_DIR / DRAFT_OPTICAL_FLOW_DIR / f"{data_id}.json"


def resolve_draft_optical_flow_path(root: Path, data_id: str) -> Path | None:
    root = Path(root).resolve()
    primary = draft_optical_flow_path(root, data_id)
    return primary if primary.is_file() else None


def migrate_draft_tracking_filenames(root: Path, id_map: dict[str, str]) -> int:
    """Rename draft files when data_id unchanged (no-op) or copy legacy keys."""
    root = Path(root).resolve()
    draft_dir = root / METADATA_DIR / DRAFT_TRACKING_DIR
    if not draft_dir.is_dir():
        return 0
    moved = 0
    for old_id, new_id in id_map.items():
        if old_id == new_id:
            continue
        old_path = draft_dir / f"{old_id}.json"
        new_path = draft_dir / f"{new_id}.json"
        if old_path.is_file() and not new_path.is_file():
            old_path.rename(new_path)
            moved += 1
    return moved


def _backup_v1_metadata(root: Path) -> Path:
    root = Path(root).resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = root / METADATA_DIR / V1_BACKUP_DIR / stamp
    backup_root.mkdir(parents=True, exist_ok=True)
    meta = root / METADATA_DIR
    for name in (SAMPLES_CSV, BATCHES_JSON, CROP_METADATA_JSON, WORKSPACE_JSON):
        src = meta / name
        if src.is_file():
            shutil.copy2(src, backup_root / name)
    draft = meta / DRAFT_TRACKING_DIR
    if draft.is_dir():
        shutil.copytree(draft, backup_root / DRAFT_TRACKING_DIR, dirs_exist_ok=True)
    return backup_root


def migrate_workspace_to_v2(root: Path) -> bool:
    """
    Upgrade workspace from v1 to v2 on disk.

    Returns True if migration ran, False if already v2.
    """
    root = Path(root).resolve()
    if read_workspace_schema_version(root) >= SCHEMA_V2:
        return False

    _backup_v1_metadata(root)

    v1_df = load_data_files_as_v1_df(root)
    v1_registry = load_sample_registry_as_v1(root)

    crop_path = root / METADATA_DIR / CROP_METADATA_JSON
    crop = load_crop_metadata_compat(crop_path)

    write_workspace_json(root, schema_version=SCHEMA_V2)

    save_data_files(root, v1_df)
    save_sample_registry(root, v1_registry)
    save_crop_metadata_compat(crop_path, crop)

    meta = root / METADATA_DIR
    for v1_name in (SAMPLES_CSV, BATCHES_JSON):
        v1_file = meta / v1_name
        if v1_file.is_file():
            v1_file.rename(meta / f"{v1_name}.v1.bak")

    return True


def migrate_workspace_schema(root: Path) -> None:
    """Run legacy v1 repairs then upgrade to v2 when needed."""
    from actintrack_app.metadata import _migrate_workspace_schema_v1

    root = Path(root).resolve()
    _migrate_workspace_schema_v1(root)
    migrate_workspace_to_v2(root)
