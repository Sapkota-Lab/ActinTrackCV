"""Sample workflow: create, replace, and clear AVI/MP4 data per breed."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from actintrack_app.batch_manager import (
    allocate_next_batch,
    create_batch,
    get_batch_by_name,
    refresh_batch_stats,
    rename_batch,
    sanitize_batch_name,
)
from actintrack_app.debug_log import breadcrumb
from actintrack_app.export_naming import (
    auto_export_name_for_sample,
    resolve_final_export_name,
)
from actintrack_app.file_importer import import_files
from actintrack_app.import_classifier import ImportKind, classify_paths
from actintrack_app.metadata import (
    get_sample_annotation,
    load_crop_metadata,
    load_samples_csv,
    save_crop_metadata,
    save_samples_csv,
)
from actintrack_app.preview_workflow import probe_video_frame_count
from actintrack_app.project_manager import get_raw_batch_dir
from actintrack_app.purge_manager import (
    collect_processed_artifacts_for_sample,
    complete_batch_purge,
)
from actintrack_app.schema_compat import draft_optical_flow_path, draft_tracking_path
from actintrack_app.utils import (
    METADATA_DIR,
    SAMPLES_CSV,
    STATUS_RAW_IMPORTED,
    relative_to_root,
)
from actintrack_app.video_normalize import store_imported_video
from actintrack_app.video_processing import MediaLoadError, assert_video_readable

DATA_IMPORT_FILTER = "Data files (*.avi *.mp4);;All files (*)"

_DERIVED_STATUSES = frozenset(
    {
        "roi_marked",
        "roi_propagated_needs_review",
        "roi_approved",
        "processed",
        "motion_index_generated",
        "motion_index_failed",
        "cutoff_marked",
        "failed",
    }
)


def default_sample_name_from_path(path: Path) -> str:
    return sanitize_batch_name(path.stem)


def validate_av_mp4_data_file(path: Path) -> tuple[bool, str]:
    """Return (ok, error_message). error_message empty when ok."""
    resolved = Path(path).resolve()
    breadcrumb("validate: start", path=str(resolved), suffix=resolved.suffix.lower())
    if not resolved.is_file():
        return False, f"File not found: {resolved}"
    kind, _, msg = classify_paths([resolved])
    breadcrumb("validate: classified", kind=str(kind))
    if kind != ImportKind.VIDEO:
        return False, msg or "Only AVI and MP4 data files are supported."
    try:
        breadcrumb("validate: probing source frame 0 (OpenCV decode)")
        probe_video_frame_count(resolved)
        breadcrumb("validate: probe ok")
    except (MediaLoadError, OSError, ValueError) as exc:
        breadcrumb("validate: probe raised", error=str(exc))
        return False, str(exc)
    return True, ""


def _registry_file_path(root: Path) -> Path:
    from actintrack_app.schema_compat import (
        BATCHES_JSON,
        read_workspace_schema_version,
    )
    from actintrack_app.utils import SAMPLE_REGISTRY_JSON, SCHEMA_V2

    meta = Path(root).resolve() / METADATA_DIR
    if read_workspace_schema_version(root) >= SCHEMA_V2:
        return meta / SAMPLE_REGISTRY_JSON
    return meta / BATCHES_JSON


def _load_registry_raw(root: Path) -> dict[str, list[dict[str, Any]]]:
    path = _registry_file_path(root)
    if not path.is_file():
        return {}
    import json

    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): list(v) for k, v in data.items() if isinstance(v, list)}
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_registry_raw(root: Path, data: dict[str, list[dict[str, Any]]]) -> None:
    path = _registry_file_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _registry_entry_name(entry: dict[str, Any]) -> str:
    return str(entry.get("batch_name") or entry.get("sample_name", ""))


def update_batch_registry_fields(
    root: Path,
    breed: str,
    batch_name: str,
    **fields: Any,
) -> None:
    root = Path(root).resolve()
    safe = sanitize_batch_name(batch_name)
    registry = _load_registry_raw(root)
    entries = list(registry.get(breed, []))
    for entry in entries:
        if sanitize_batch_name(_registry_entry_name(entry)) == safe:
            entry.update(fields)
            if "batch_name" in fields and "sample_name" in entry:
                entry["sample_name"] = fields["batch_name"]
            break
    registry[breed] = entries
    _save_registry_raw(root, registry)


def mark_batch_auto_generated(
    root: Path,
    breed: str,
    batch_name: str,
    *,
    source_filename: str,
) -> None:
    update_batch_registry_fields(
        root,
        breed,
        batch_name,
        auto_generated_name=True,
        source_filename=str(source_filename),
    )


def clear_batch_auto_generated(root: Path, breed: str, batch_name: str) -> None:
    update_batch_registry_fields(
        root,
        breed,
        batch_name,
        auto_generated_name=False,
    )


def batch_has_auto_generated_name(root: Path, breed: str, batch_name: str) -> bool:
    batch = get_batch_by_name(root, breed, batch_name)
    if not batch:
        return False
    safe = sanitize_batch_name(batch_name)
    for entry in _load_registry_raw(root).get(breed, []):
        if sanitize_batch_name(_registry_entry_name(entry)) == safe:
            return bool(entry.get("auto_generated_name", False))
    return False


def get_primary_data_row(
    root: Path, breed: str, batch_name: str
) -> dict[str, str] | None:
    root = Path(root).resolve()
    safe = sanitize_batch_name(batch_name)
    df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)
    sub = df[
        (df["group"] == breed)
        & (df["batch_name"].astype(str).apply(sanitize_batch_name) == safe)
    ]
    if sub.empty:
        return None
    return {str(k): str(v) for k, v in sub.iloc[0].items()}


def sample_has_derived_state(root: Path, sample_id: str) -> bool:
    root = Path(root).resolve()
    if get_sample_annotation(root, sample_id):
        return True
    draft = draft_tracking_path(root, sample_id)
    if draft.is_file():
        return True
    of_draft = draft_optical_flow_path(root, sample_id)
    if of_draft.is_file():
        return True
    row = _row_by_sample_id(root, sample_id)
    if not row:
        return False
    status = str(row.get("processing_status", ""))
    if status in _DERIVED_STATUSES:
        return True
    if str(row.get("annotation_source", "")).strip():
        return True
    artifacts = collect_processed_artifacts_for_sample(root, row)
    return bool(artifacts)


def _row_by_sample_id(root: Path, sample_id: str) -> dict[str, str] | None:
    df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)
    sub = df[df["sample_id"].astype(str) == str(sample_id)]
    if sub.empty:
        return None
    return {str(k): str(v) for k, v in sub.iloc[0].items()}


def clear_sample_derived_state(root: Path, sample_id: str) -> None:
    """Remove ROI, tracking, processed outputs; reset CSV status for one data row."""
    root = Path(root).resolve()
    row = _row_by_sample_id(root, sample_id)
    if not row:
        return

    crop_path = root / METADATA_DIR / "crop_metadata.json"
    crop = load_crop_metadata(crop_path)
    crop.get("samples", {}).pop(str(sample_id), None)
    save_crop_metadata(crop_path, crop)

    draft = draft_tracking_path(root, sample_id)
    if draft.is_file():
        draft.unlink(missing_ok=True)

    of_draft = draft_optical_flow_path(root, sample_id)
    if of_draft.is_file():
        of_draft.unlink(missing_ok=True)

    for path in collect_processed_artifacts_for_sample(root, row):
        if path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)

    samples_path = root / METADATA_DIR / SAMPLES_CSV
    df = load_samples_csv(samples_path)
    mask = df["sample_id"].astype(str) == str(sample_id)
    if not mask.any():
        return
    idx = df.index[mask][0]
    if str(df.at[idx, "processing_status"]) != "missing_file":
        df.at[idx, "processing_status"] = STATUS_RAW_IMPORTED
    df.at[idx, "annotation_source"] = ""
    df.at[idx, "review_status"] = "pending"
    save_samples_csv(root, df)

    breed = str(row.get("group", ""))
    batch_name = str(row.get("batch_name", ""))
    if breed and batch_name:
        refresh_batch_stats(root, breed, batch_name)


def create_sample_from_data(
    root: Path,
    breed: str,
    source_path: Path,
    *,
    notes: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = Path(root).resolve()
    src = Path(source_path).resolve()
    breadcrumb("create_sample: start", src=str(src))
    ok, err = validate_av_mp4_data_file(src)
    if not ok:
        raise ValueError(err)

    name = default_sample_name_from_path(src)
    num, final_name = allocate_next_batch(root, breed, preferred_name=name)
    batch = create_batch(root, breed, final_name, batch_number=num)
    breadcrumb("create_sample: batch created, importing", batch=str(final_name))
    try:
        records = import_files(
            [src],
            breed,
            batch["batch_name"],
            batch["batch_id"],
            root,
            batch_number=int(batch["batch_number"]),
            notes=notes,
        )
    except Exception as exc:
        breadcrumb("create_sample: import failed, rolling back", error=str(exc))
        from actintrack_app.batch_manager import delete_empty_batch

        try:
            delete_empty_batch(root, breed, batch["batch_name"], remove_raw_folder=True)
        except ValueError:
            pass
        raise
    breadcrumb("create_sample: success", batch=str(batch["batch_name"]))

    mark_batch_auto_generated(
        root, breed, batch["batch_name"], source_filename=src.name
    )
    batch = get_batch_by_name(root, breed, batch["batch_name"]) or batch
    return batch, records[0]


def replace_sample_data(
    root: Path,
    breed: str,
    batch_name: str,
    source_path: Path,
) -> dict[str, Any]:
    root = Path(root).resolve()
    src = Path(source_path).resolve()
    ok, err = validate_av_mp4_data_file(src)
    if not ok:
        raise ValueError(err)

    batch = get_batch_by_name(root, breed, batch_name)
    if batch is None:
        raise ValueError(f"Sample not found: {batch_name}")

    safe = sanitize_batch_name(batch_name)
    row = get_primary_data_row(root, breed, safe)

    if row is None:
        records = import_files(
            [src],
            breed,
            batch["batch_name"],
            batch["batch_id"],
            root,
            batch_number=int(batch.get("batch_number", 1) or 1),
        )
        mark_batch_auto_generated(root, breed, safe, source_filename=src.name)
        return records[0]

    sample_id = str(row["sample_id"])
    clear_sample_derived_state(root, sample_id)

    raw_dir = get_raw_batch_dir(root, breed, safe)
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest_path = raw_dir / f"{sample_id}{src.suffix.lower()}"
    old_stored = str(row.get("stored_path", ""))
    old_path = root / old_stored if old_stored else None
    if old_path and old_path.is_file() and old_path.resolve() != dest_path.resolve():
        old_path.unlink(missing_ok=True)
    store_imported_video(src, dest_path)
    assert_video_readable(dest_path)

    samples_path = root / METADATA_DIR / SAMPLES_CSV
    df = load_samples_csv(samples_path)
    mask = df["sample_id"].astype(str) == sample_id
    idx = df.index[mask][0]
    batch_number = int(str(df.at[idx, "batch_number"] or batch.get("batch_number", 1)))
    auto_name = auto_export_name_for_sample(
        group=breed,
        batch_number=batch_number,
        is_video=True,
        frame_number=0,
    )
    df.at[idx, "original_filename"] = src.name
    df.at[idx, "stored_path"] = relative_to_root(root, dest_path)
    df.at[idx, "file_type"] = "video"
    df.at[idx, "is_video"] = "true"
    df.at[idx, "is_image_sequence"] = "false"
    df.at[idx, "auto_export_name"] = auto_name
    df.at[idx, "custom_export_name"] = ""
    df.at[idx, "final_export_name"] = resolve_final_export_name(auto_name, None)
    df.at[idx, "processing_status"] = STATUS_RAW_IMPORTED
    df.at[idx, "annotation_source"] = ""
    df.at[idx, "review_status"] = "pending"
    save_samples_csv(root, df)
    refresh_batch_stats(root, breed, safe)

    final_batch_name = safe
    if batch_has_auto_generated_name(root, breed, safe):
        new_name = default_sample_name_from_path(src)
        if sanitize_batch_name(new_name) != safe:
            rename_batch(root, breed, safe, new_name)
            final_batch_name = sanitize_batch_name(new_name)
            mark_batch_auto_generated(
                root, breed, final_batch_name, source_filename=src.name
            )
    else:
        update_batch_registry_fields(
            root, breed, safe, source_filename=str(src.name)
        )

    updated = get_primary_data_row(root, breed, final_batch_name)
    return updated or row


def delete_sample_and_artifacts(
    root: Path,
    breed: str,
    batch_name: str,
    *,
    remove_workspace_raw: bool = False,
) -> dict[str, Any]:
    return complete_batch_purge(
        root,
        breed,
        batch_name,
        remove_workspace_raw=remove_workspace_raw,
    )
