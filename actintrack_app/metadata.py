"""CSV and JSON metadata for samples and crop annotations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from actintrack_app.utils import CROP_METADATA_JSON, METADATA_DIR, SAMPLES_CSV, SAMPLES_CSV_COLUMNS


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_empty_samples_csv(path: Path) -> None:
    df = pd.DataFrame(columns=SAMPLES_CSV_COLUMNS)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def _coerce_samples_df_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure text columns stay str (pandas 3.x rejects '' into float64 notes)."""
    text_cols = (
        "sample_id",
        "group",
        "original_filename",
        "stored_path",
        "file_type",
        "import_date",
        "processing_status",
        "notes",
    )
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)
    return df


def load_samples_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        create_empty_samples_csv(path)
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception:
        create_empty_samples_csv(path)
        df = pd.read_csv(path, dtype=str, keep_default_na=False)

    for col in SAMPLES_CSV_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[SAMPLES_CSV_COLUMNS]
    return _coerce_samples_df_dtypes(df)


def save_samples_csv(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df[SAMPLES_CSV_COLUMNS].to_csv(path, index=False)


def resolve_sample_path(root: Path, stored_path: str) -> Path:
    return Path(root).resolve() / stored_path


def is_sample_file_present(root: Path, stored_path: str) -> bool:
    return resolve_sample_path(root, stored_path).is_file()


def sync_samples_with_disk(root: Path) -> tuple[pd.DataFrame, list[str]]:
    """
    Compare samples.csv against raw/ files on disk.

    Rows whose stored_path no longer exists are marked processing_status=missing_file.
    Returns the updated dataframe and list of missing sample_ids.
    """
    root = Path(root).resolve()
    samples_path = root / METADATA_DIR / SAMPLES_CSV
    df = load_samples_csv(samples_path)
    missing: list[str] = []
    changed = False

    for idx, row in df.iterrows():
        stored = str(row.get("stored_path", "")).strip()
        if not stored:
            continue
        if is_sample_file_present(root, stored):
            if str(row.get("processing_status", "")) == "missing_file":
                df.at[idx, "processing_status"] = "imported"
                changed = True
        else:
            sid = str(row["sample_id"])
            missing.append(sid)
            if str(row.get("processing_status", "")) != "missing_file":
                df.at[idx, "processing_status"] = "missing_file"
                changed = True

    if changed:
        save_samples_csv(samples_path, df)
    return df, missing


def remove_samples_from_metadata(root: Path, sample_ids: list[str]) -> int:
    """Remove sample rows from samples.csv and crop_metadata.json."""
    root = Path(root).resolve()
    if not sample_ids:
        return 0

    ids = {str(s) for s in sample_ids}
    samples_path = root / METADATA_DIR / SAMPLES_CSV
    crop_path = root / METADATA_DIR / CROP_METADATA_JSON

    df = load_samples_csv(samples_path)
    before = len(df)
    df = df[~df["sample_id"].astype(str).isin(ids)].reset_index(drop=True)
    save_samples_csv(samples_path, df)

    crop = load_crop_metadata(crop_path)
    for sid in ids:
        crop.get("samples", {}).pop(sid, None)
    save_crop_metadata(crop_path, crop)

    return before - len(df)


def update_samples_csv(path: Path, sample_record: dict[str, Any]) -> None:
    df = load_samples_csv(path)
    sid = str(sample_record["sample_id"])
    record = {k: "" if v is None else str(v) for k, v in sample_record.items()}
    mask = df["sample_id"] == sid
    if mask.any():
        for key, value in record.items():
            if key in df.columns:
                df.loc[mask, key] = str(value)
    else:
        df = pd.concat([df, pd.DataFrame([record])], ignore_index=True)
    save_samples_csv(path, _coerce_samples_df_dtypes(df))


def load_crop_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"samples": {}}
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        if "samples" not in data:
            data["samples"] = {}
        return data
    except (json.JSONDecodeError, OSError):
        return {"samples": {}}


def save_crop_metadata(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def save_sample_crop_annotation(
    crop_meta_path: Path,
    sample_id: str,
    annotation: dict[str, Any],
) -> None:
    """Merge per-sample annotation into crop_metadata.json."""
    data = load_crop_metadata(crop_meta_path)
    data["samples"][sample_id] = annotation
    save_crop_metadata(crop_meta_path, data)


def build_cutoff_annotation(
    *,
    sample_id: str,
    group: str,
    original_file: str,
    stored_raw_path: str,
    reference_frame_index: int,
    cutoff_y: int,
    image_width: int,
    image_height: int,
    tracking_roi: dict[str, Any] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Structured manual cutoff annotation for future training."""
    w, h, y, ref = int(image_width), int(image_height), int(cutoff_y), int(reference_frame_index)
    roi = tracking_roi or {}
    x0 = int(roi.get("x0", 0))
    y0 = int(roi.get("y0", 0))
    x1 = int(roi.get("x1", w))
    y1 = int(roi.get("y1", y))
    return {
        "sample_id": str(sample_id),
        "group": str(group),
        "original_file": str(original_file),
        "stored_raw_path": str(stored_raw_path),
        "reference_frame_index": ref,
        "cutoff_y": y,
        "cutoff_y_rotated": y,  # same until rotation is implemented
        "analysis_region_description": (
            "Upper/central actin-rich filament tracking region above cutoff_y. "
            "Lower perinuclear/nucleus-adjacent signal is excluded from 2D velocity tracking."
        ),
        "analysis_region_coords": {
            "x0": max(0, min(x0, w)),
            "y0": max(0, min(y0, h)),
            "x1": max(0, min(x1, w)),
            "y1": max(0, min(y1, h)),
        },
        "excluded_region_coords": {
            "x0": 0,
            "y0": y,
            "x1": w,
            "y1": h,
        },
        "tracking_roi": tracking_roi,
        "crop_method": roi.get("method", "manual_cutoff"),
        "original_dimensions": {"width": w, "height": h},
        "rotated_dimensions": {"width": w, "height": h},
        "segmentation_method": "not_applied_phase1",
        "rotation_angle_degrees": None,
        "flipped_180": None,
        "status": "cutoff_marked",
        "processing_date": _utc_now_iso(),
        "notes": notes,
    }
