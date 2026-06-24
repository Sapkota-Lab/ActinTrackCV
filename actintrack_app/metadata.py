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
        "batch_number",
        "batch_name",
        "batch_id",
        "original_filename",
        "stored_path",
        "file_type",
        "is_video",
        "is_image_sequence",
        "frame_number",
        "auto_export_name",
        "custom_export_name",
        "final_export_name",
        "import_date",
        "processing_status",
        "annotation_source",
        "review_status",
        "notes",
    )
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)
    return df


def _migrate_workspace_schema_v1(root: Path) -> None:
    """Upgrade samples.csv and batches.json for batch numbers and export naming (v1)."""
    from actintrack_app.batch_manager import (
        list_batches,
        parse_batch_number_from_name,
        register_batch_from_samples,
        repair_batch_registry,
        sanitize_batch_name,
    )

    repair_batch_registry(root)
    from actintrack_app.export_naming import (
        auto_export_name_for_sample,
        resolve_final_export_name,
    )
    from actintrack_app.utils import VIDEO_EXTENSIONS

    root = Path(root).resolve()
    migrate_samples_batch_columns(root)
    samples_path = root / METADATA_DIR / SAMPLES_CSV
    df = load_samples_csv(samples_path)
    changed = False

    for idx, row in df.iterrows():
        group = str(row.get("group", ""))
        batch_name = str(row.get("batch_name", "")).strip()
        if not batch_name:
            batch_name = "Legacy_Batch"
            df.at[idx, "batch_name"] = batch_name
            changed = True

        bn = str(row.get("batch_number", "")).strip()
        if not bn:
            parsed = parse_batch_number_from_name(batch_name)
            if parsed is None:
                batches = list_batches(root, group)
                parsed = len(batches) or 1
            df.at[idx, "batch_number"] = str(parsed)
            changed = True
        batch_number = int(str(df.at[idx, "batch_number"]))

        stored = str(row.get("stored_path", ""))
        ext = Path(stored).suffix.lower() if stored else ""
        is_video = str(row.get("is_video", "")).lower() == "true" or ext in VIDEO_EXTENSIONS
        if str(row.get("is_video", "")).strip() == "":
            df.at[idx, "is_video"] = "true" if is_video else "false"
            changed = True
        if str(row.get("is_image_sequence", "")).strip() == "":
            df.at[idx, "is_image_sequence"] = "false" if is_video else "true"
            changed = True

        fn = str(row.get("frame_number", "")).strip()
        if not fn:
            df.at[idx, "frame_number"] = "0"
            changed = True

        auto = str(row.get("auto_export_name", "")).strip()
        if not auto and group:
            auto = auto_export_name_for_sample(
                group=group,
                batch_number=batch_number,
                is_video=is_video,
                frame_number=int(df.at[idx, "frame_number"] or 0),
            )
            df.at[idx, "auto_export_name"] = auto
            changed = True
        custom = str(row.get("custom_export_name", "")).strip()
        final = str(row.get("final_export_name", "")).strip()
        if not final:
            df.at[idx, "final_export_name"] = resolve_final_export_name(
                auto or str(df.at[idx, "auto_export_name"]),
                custom or None,
            )
            changed = True

        if not str(row.get("annotation_source", "")).strip():
            df.at[idx, "annotation_source"] = ""
        if not str(row.get("review_status", "")).strip():
            df.at[idx, "review_status"] = "pending"
            changed = True

        status = str(row.get("processing_status", ""))
        if status == "imported":
            df.at[idx, "processing_status"] = "raw_imported"
            changed = True

        bid = str(row.get("batch_id", "")).strip()
        if not bid:
            from actintrack_app.utils import GROUP_PREFIX

            prefix = GROUP_PREFIX.get(group, "B")
            bid = f"{prefix}_B{batch_number:03d}"
            df.at[idx, "batch_id"] = bid
            changed = True

        register_batch_from_samples(
            root,
            group,
            batch_name,
            bid,
            batch_number=batch_number,
        )

    if changed:
        save_samples_csv(root, df)


def migrate_workspace_schema(root: Path) -> None:
    """Run v1 repairs then migrate to schema v2 when needed."""
    from actintrack_app.schema_compat import migrate_workspace_schema as _migrate

    _migrate(root)


def migrate_samples_batch_columns(root: Path) -> None:
    """
    Add batch_name/batch_id to existing projects and assign legacy flat imports
    to Legacy_Batch folders when needed.
    """
    from actintrack_app.batch_manager import (
        LEGACY_BATCH_NAME,
        register_batch_from_samples,
        sanitize_batch_name,
    )
    from actintrack_app.utils import GROUP_PREFIX, RAW_DIR

    root = Path(root).resolve()
    samples_path = root / METADATA_DIR / SAMPLES_CSV
    df = load_samples_csv(samples_path)
    changed = False

    for idx, row in df.iterrows():
        batch_name = str(row.get("batch_name", "")).strip()
        batch_id = str(row.get("batch_id", "")).strip()
        group = str(row.get("group", ""))
        stored = str(row.get("stored_path", ""))

        if batch_name and batch_id:
            register_batch_from_samples(root, group, batch_name, batch_id)
            continue

        changed = True
        safe_legacy = sanitize_batch_name(LEGACY_BATCH_NAME)
        prefix = GROUP_PREFIX.get(group, "B")
        bid = batch_id or f"{prefix}_B000"
        if not batch_id:
            register_batch_from_samples(root, group, safe_legacy, bid)

        parts = Path(stored).parts
        # raw/<group>/<file> -> move metadata to raw/<group>/Legacy_Batch/<file>
        if (
            len(parts) >= 3
            and parts[0] == RAW_DIR
            and parts[1] == group
            and len(parts) == 3
        ):
            filename = parts[2]
            new_stored = f"{RAW_DIR}/{group}/{safe_legacy}/{filename}"
            src = root / stored
            dest = root / new_stored
            if src.is_file() and not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    src.rename(dest)
                except OSError:
                    pass
            if dest.is_file():
                df.at[idx, "stored_path"] = new_stored

        df.at[idx, "batch_name"] = safe_legacy
        df.at[idx, "batch_id"] = bid
        if "batch_number" in df.columns and not str(df.at[idx, "batch_number"]).strip():
            df.at[idx, "batch_number"] = "1"

    if changed:
        save_samples_csv(root, df)


def load_samples_csv(path: Path) -> pd.DataFrame:
    """Load data-file table; returns legacy v1 column names for compatibility."""
    from actintrack_app.schema_compat import load_data_files_as_v1_df

    root = path.parent.parent if path.parent.name == METADATA_DIR else path.parent
    if not path.exists() and not (root / METADATA_DIR / "data_files.csv").exists():
        create_empty_samples_csv(path)
    return _coerce_samples_df_dtypes(load_data_files_as_v1_df(root))


def save_samples_csv(path_or_root: Path, df: pd.DataFrame) -> None:
    """Persist data-file table (v1 or v2 on disk per workspace schema)."""
    from actintrack_app.schema_compat import save_data_files

    p = Path(path_or_root)
    if p.suffix.lower() == ".csv":
        root = p.parent.parent if p.parent.name == METADATA_DIR else p.parent
    else:
        root = p
    save_data_files(root, _coerce_samples_df_dtypes(df))


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
        save_samples_csv(root, df)
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
    save_samples_csv(root, df)

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
    root = path.parent.parent if path.parent.name == METADATA_DIR else path.parent
    save_samples_csv(root, _coerce_samples_df_dtypes(df))


def load_crop_metadata(path: Path) -> dict[str, Any]:
    from actintrack_app.schema_compat import load_crop_metadata_compat

    return load_crop_metadata_compat(path)


def save_crop_metadata(path: Path, data: dict[str, Any]) -> None:
    from actintrack_app.schema_compat import save_crop_metadata_compat

    save_crop_metadata_compat(path, data)


def save_sample_crop_annotation(
    crop_meta_path: Path,
    sample_id: str,
    annotation: dict[str, Any],
) -> None:
    """Merge per-sample annotation into crop_metadata.json."""
    data = load_crop_metadata(crop_meta_path)
    data["samples"][sample_id] = annotation
    save_crop_metadata(crop_meta_path, data)


def remove_sample_crop_annotation(crop_meta_path: Path, sample_id: str) -> bool:
    """Remove a per-sample annotation from crop_metadata.json.

    Returns True if an annotation existed and was removed.
    """
    data = load_crop_metadata(crop_meta_path)
    samples = data.get("samples", {})
    if str(sample_id) in samples:
        del samples[str(sample_id)]
        save_crop_metadata(crop_meta_path, data)
        return True
    return False


def get_sample_annotation(root: Path, sample_id: str) -> dict[str, Any] | None:
    crop_path = Path(root).resolve() / METADATA_DIR / CROP_METADATA_JSON
    data = load_crop_metadata(crop_path)
    return data.get("samples", {}).get(str(sample_id))


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
