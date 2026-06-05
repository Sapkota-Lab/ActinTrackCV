"""Safe purge and delete operations for workspace annotations and outputs."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from actintrack_app.batch_manager import (
    all_workspace_condition_groups,
    clear_batches_registry_for_groups,
    list_batches,
    prune_all_groups_without_samples,
    remove_batch_folders,
    remove_batch_from_registry,
    refresh_batch_stats,
    reset_batches_registry_workspace,
    sanitize_batch_name,
)
from actintrack_app.export_naming import batch_metadata_base_name
from actintrack_app.metadata import (
    load_crop_metadata,
    load_samples_csv,
    remove_samples_from_metadata,
    save_crop_metadata,
    save_samples_csv,
)
from actintrack_app.project_manager import get_processed_batch_dir
from actintrack_app.utils import (
    CROP_METADATA_JSON,
    METADATA_DIR,
    PREVIEWS_DIR,
    PROCESSED_DIR,
    RAW_DIR,
    SAMPLES_CSV,
    STATUS_IMPORTED,
    STATUS_RAW_IMPORTED,
    STATUS_UNANNOTATED,
)


ANNOTATION_STATUSES = frozenset(
    {
        "cutoff_marked",
        "roi_marked",
        "roi_propagated_needs_review",
        "roi_approved",
        "processed",
        "failed",
    }
)


def _reset_status(status: str) -> str:
    if status in ("missing_file",):
        return status
    return STATUS_RAW_IMPORTED


def _sample_row_dict(row: pd.Series) -> dict[str, str]:
    return {str(k): str(v) for k, v in row.items()}


def collect_processed_artifacts_for_sample(
    root: Path,
    row: dict[str, str],
) -> list[Path]:
    """Paths under processed/ and previews/ tied to a sample."""
    root = Path(root).resolve()
    paths: list[Path] = []
    group = str(row.get("group", ""))
    batch_name = sanitize_batch_name(str(row.get("batch_name", "")))
    final_name = str(row.get("final_export_name", "")).strip()
    auto_name = str(row.get("auto_export_name", "")).strip()
    names = [n for n in (final_name, auto_name) if n]

    batch_dir = get_processed_batch_dir(root, group, batch_name)
    if batch_dir.is_dir():
        for name in names:
            for pattern in (
                f"{name}.mp4",
                f"{name}.png",
                f"{name}_metadata.json",
                f"{name}_orientation_preview.png",
                f"{name}_roi_preview.png",
                f"{name}_raw_debug_preview.png",
                f"{name}_crop_preview.png",
            ):
                p = batch_dir / pattern
                if p.is_file():
                    paths.append(p)
        try:
            bn = int(row.get("batch_number", 0) or 0)
        except ValueError:
            bn = 0
        if bn:
            base = batch_metadata_base_name(group, bn)
            meta = batch_dir / f"{base}_metadata.json"
            if meta.is_file():
                paths.append(meta)
        # Legacy per-sample_id folder
        sid = str(row.get("sample_id", ""))
        legacy = batch_dir / sid
        if legacy.is_dir():
            paths.append(legacy)

    preview_dir = root / PREVIEWS_DIR / group
    if preview_dir.is_dir():
        for name in names:
            for p in preview_dir.glob(f"{name}*"):
                if p.is_file():
                    paths.append(p)

    return list(dict.fromkeys(paths))


def delete_sample_from_batch(
    root: Path,
    sample_id: str,
    *,
    remove_workspace_raw: bool = False,
) -> dict[str, Any]:
    """Remove one file from metadata and delete its derived outputs (not external source)."""
    root = Path(root).resolve()
    df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)
    mask = df["sample_id"].astype(str) == str(sample_id)
    if not mask.any():
        raise ValueError(f"Sample not found: {sample_id}")

    row = _sample_row_dict(df[mask].iloc[0])
    artifacts = collect_processed_artifacts_for_sample(root, row)
    for path in artifacts:
        if path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)

    stored = row.get("stored_path", "")
    raw_path = root / stored if stored else None
    if remove_workspace_raw and raw_path and raw_path.is_file():
        raw_path.unlink(missing_ok=True)

    remove_samples_from_metadata(root, [sample_id])
    group = row.get("group", "")
    batch_name = row.get("batch_name", "")
    if group and batch_name:
        refresh_batch_stats(root, group, batch_name)

    return {
        "sample_id": sample_id,
        "removed_artifacts": [str(p) for p in artifacts],
        "raw_removed": bool(remove_workspace_raw and raw_path),
    }


def purge_sample_annotations_only(root: Path, sample_id: str) -> dict[str, Any]:
    """Clear annotations/processed for one sample; keep file row and raw copy."""
    return purge_filtered_samples(root, [sample_id], keep_raw=True)


def purge_sample_completely(
    root: Path,
    sample_id: str,
    *,
    remove_workspace_raw: bool = False,
) -> dict[str, Any]:
    """Remove one sample from the app database and all derived outputs."""
    return delete_sample_from_batch(
        root,
        sample_id,
        remove_workspace_raw=remove_workspace_raw,
    )


def complete_batch_purge(
    root: Path,
    group: str,
    batch_name: str,
    *,
    remove_workspace_raw: bool = False,
) -> dict[str, Any]:
    """Remove batch registry entry and all samples in the batch from the app database."""
    root = Path(root).resolve()
    safe = sanitize_batch_name(batch_name)
    df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)
    sub = df[
        (df["group"] == group)
        & (df["batch_name"].astype(str).apply(sanitize_batch_name) == safe)
    ]
    sample_ids = sub["sample_id"].astype(str).tolist()
    files_removed = 0
    artifacts_removed: list[str] = []

    for sid in sample_ids:
        try:
            result = delete_sample_from_batch(
                root,
                sid,
                remove_workspace_raw=remove_workspace_raw,
            )
            files_removed += 1
            artifacts_removed.extend(result.get("removed_artifacts", []))
        except ValueError:
            pass

    remove_batch_from_registry(root, group, safe)
    folder_paths = remove_batch_folders(
        root,
        group,
        safe,
        remove_raw=remove_workspace_raw,
        remove_processed=True,
    )

    return {
        "batch_name": safe,
        "samples_removed": len(sample_ids),
        "files_removed": files_removed,
        "artifacts_removed": artifacts_removed,
        "folders_removed": folder_paths,
        "raw_folder_removed": remove_workspace_raw,
    }


def purge_condition_annotations(root: Path, group: str) -> dict[str, Any]:
    """Clear annotations/processed for all samples in a condition; keep batches and raw."""
    root = Path(root).resolve()
    df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)
    sub = df[df["group"] == group]
    ids = sub["sample_id"].astype(str).tolist()
    stats = purge_filtered_samples(root, ids, keep_raw=True)
    stats["group"] = group
    return stats


def complete_condition_purge(
    root: Path,
    group: str,
    *,
    remove_workspace_raw: bool = False,
) -> dict[str, Any]:
    """Remove all batches and samples for a condition group from the app database."""
    root = Path(root).resolve()
    batches = list_batches(root, group)
    batch_count = len(batches)

    df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)
    sample_ids = df[df["group"] == group]["sample_id"].astype(str).tolist()
    for sid in sample_ids:
        try:
            delete_sample_from_batch(
                root, sid, remove_workspace_raw=remove_workspace_raw
            )
        except ValueError:
            pass

    for batch in batches:
        remove_batch_from_registry(root, group, str(batch["batch_name"]))
    clear_batches_registry_for_groups(root, [group])

    import shutil

    if remove_workspace_raw:
        raw_group = root / RAW_DIR / group
        if raw_group.is_dir():
            shutil.rmtree(raw_group, ignore_errors=True)
    proc_group = root / PROCESSED_DIR / group
    if proc_group.is_dir():
        shutil.rmtree(proc_group, ignore_errors=True)
    prev_group = root / PREVIEWS_DIR / group
    if prev_group.is_dir():
        shutil.rmtree(prev_group, ignore_errors=True)

    return {
        "group": group,
        "batches_removed": batch_count,
        "samples_removed": len(sample_ids),
    }


def purge_all_annotations_only(root: Path) -> dict[str, Any]:
    """Clear all annotations/processed workspace-wide; keep imported files and batches."""
    return purge_all_annotated_processed(root)


def complete_workspace_purge(
    root: Path,
    *,
    remove_workspace_raw: bool = False,
) -> dict[str, Any]:
    """Remove all workspace metadata and outputs; optional removal of all raw/ copies."""
    root = Path(root).resolve()
    df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)
    # Include every standard group and any batches.json entries, not only groups
    # that still have rows in samples.csv (empty Batch 1-only groups were skipped before).
    groups = all_workspace_condition_groups(root)
    total_samples = 0
    total_batches = 0
    for group in groups:
        if not group:
            continue
        result = complete_condition_purge(
            root, group, remove_workspace_raw=remove_workspace_raw
        )
        total_samples += int(result.get("samples_removed", 0))
        total_batches += int(result.get("batches_removed", 0))

    batches_cleared = clear_batches_registry_for_groups(root, groups)
    reset_batches_registry_workspace(root)
    prune_all_groups_without_samples(root)

    save_crop_metadata(root / METADATA_DIR / CROP_METADATA_JSON, {"samples": {}})
    save_samples_csv(
        root / METADATA_DIR / SAMPLES_CSV,
        pd.DataFrame(columns=df.columns),
    )

    return {
        "groups_cleared": len(groups),
        "batches_removed": max(total_batches, batches_cleared),
        "samples_removed": total_samples,
        "raw_removed": remove_workspace_raw,
    }


def purge_batch_annotations(root: Path, group: str, batch_name: str) -> dict[str, Any]:
    """Clear annotations/processed for one batch; keep raw files."""
    root = Path(root).resolve()
    safe = sanitize_batch_name(batch_name)
    df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)
    sub = df[
        (df["group"] == group)
        & (df["batch_name"].astype(str).apply(sanitize_batch_name) == safe)
    ]
    if sub.empty:
        return {"samples_updated": 0, "files_deleted": 0}

    crop_path = root / METADATA_DIR / CROP_METADATA_JSON
    crop = load_crop_metadata(crop_path)
    deleted = 0
    for _, row in sub.iterrows():
        sid = str(row["sample_id"])
        for path in collect_processed_artifacts_for_sample(root, _sample_row_dict(row)):
            if path.is_file():
                path.unlink(missing_ok=True)
                deleted += 1
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
                deleted += 1
        crop.get("samples", {}).pop(sid, None)
        idx = df.index[df["sample_id"] == sid]
        if len(idx):
            df.at[idx[0], "processing_status"] = _reset_status(
                str(df.at[idx[0], "processing_status"])
            )
            df.at[idx[0], "annotation_source"] = ""
            df.at[idx[0], "review_status"] = "pending"

    save_crop_metadata(crop_path, crop)
    save_samples_csv(root / METADATA_DIR / SAMPLES_CSV, df)

    proc_dir = get_processed_batch_dir(root, group, safe)
    if proc_dir.is_dir():
        for child in proc_dir.iterdir():
            if child.is_file():
                child.unlink(missing_ok=True)
                deleted += 1
            elif child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
                deleted += 1

    refresh_batch_stats(root, group, safe)
    return {"samples_updated": len(sub), "files_deleted": deleted}


def filter_samples_for_purge(
    root: Path,
    *,
    group: str | None = None,
    batch_name: str | None = None,
    batch_number: int | None = None,
    processing_status: str | None = None,
    file_type: str | None = None,
    annotation_source: str | None = None,
    review_status: str | None = None,
) -> pd.DataFrame:
    df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)
    if df.empty:
        return df

    if group:
        df = df[df["group"] == group]
    if batch_name:
        safe = sanitize_batch_name(batch_name)
        df = df[df["batch_name"].astype(str).apply(sanitize_batch_name) == safe]
    if batch_number is not None:
        df = df[df["batch_number"].astype(str) == str(batch_number)]
    if processing_status:
        df = df[df["processing_status"] == processing_status]
    if file_type:
        if file_type == "video":
            df = df[
                (df["file_type"] == "video")
                | (df["is_video"].astype(str).str.lower() == "true")
            ]
        elif file_type in ("image", "tiff"):
            df = df[
                (df["file_type"].isin(["image", "tiff"]))
                | (df["is_image_sequence"].astype(str).str.lower() == "true")
            ]
        else:
            df = df[df["file_type"] == file_type]
    if annotation_source:
        df = df[df["annotation_source"] == annotation_source]
    if review_status:
        df = df[df["review_status"] == review_status]
    return df


def purge_filtered_samples(
    root: Path,
    sample_ids: list[str],
    *,
    keep_raw: bool = True,
) -> dict[str, Any]:
    """Purge annotations/processed for listed samples."""
    root = Path(root).resolve()
    df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)
    ids = {str(s) for s in sample_ids}
    sub = df[df["sample_id"].astype(str).isin(ids)]
    crop_path = root / METADATA_DIR / CROP_METADATA_JSON
    crop = load_crop_metadata(crop_path)
    deleted = 0
    for _, row in sub.iterrows():
        sid = str(row["sample_id"])
        for path in collect_processed_artifacts_for_sample(root, _sample_row_dict(row)):
            if path.is_file():
                path.unlink(missing_ok=True)
                deleted += 1
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
                deleted += 1
        crop.get("samples", {}).pop(sid, None)
        idx = df.index[df["sample_id"] == sid]
        if len(idx):
            df.at[idx[0], "processing_status"] = _reset_status(
                str(df.at[idx[0], "processing_status"])
            )
            if keep_raw:
                pass  # stored_path unchanged

    save_crop_metadata(crop_path, crop)
    save_samples_csv(root / METADATA_DIR / SAMPLES_CSV, df)
    return {"samples_updated": len(sub), "files_deleted": deleted}


def purge_all_annotated_processed(root: Path) -> dict[str, Any]:
    """Workspace-wide purge of annotations and processed outputs; keep raw/."""
    root = Path(root).resolve()
    df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)
    ids = df["sample_id"].astype(str).tolist()

    crop_path = root / METADATA_DIR / CROP_METADATA_JSON
    save_crop_metadata(crop_path, {"samples": {}})

    proc_root = root / PROCESSED_DIR
    deleted_dirs = 0
    if proc_root.is_dir():
        for group_dir in proc_root.iterdir():
            if group_dir.is_dir():
                shutil.rmtree(group_dir, ignore_errors=True)
                deleted_dirs += 1
                group_dir.mkdir(parents=True, exist_ok=True)

    prev_root = root / PREVIEWS_DIR
    if prev_root.is_dir():
        for group_dir in prev_root.iterdir():
            if group_dir.is_dir():
                for f in group_dir.iterdir():
                    if f.is_file():
                        f.unlink(missing_ok=True)

    for idx in df.index:
        st = str(df.at[idx, "processing_status"])
        if st != "missing_file":
            df.at[idx, "processing_status"] = STATUS_UNANNOTATED
        df.at[idx, "annotation_source"] = ""
        df.at[idx, "review_status"] = "pending"

    save_samples_csv(root / METADATA_DIR / SAMPLES_CSV, df)
    return {
        "samples_reset": len(ids),
        "processed_groups_cleared": deleted_dirs,
    }
