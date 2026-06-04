"""Import microscopy files into project raw/<group>/<batch>/ folders."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import pandas as pd

from actintrack_app.batch_manager import (
    batch_has_video,
    create_batch,
    create_batch_for_video_import,
    display_batch_name,
    ensure_batch_dirs,
    next_frame_number_in_batch,
    refresh_batch_stats,
    sanitize_batch_name,
)
from actintrack_app.export_naming import (
    auto_export_name_for_sample,
    is_video_path,
    resolve_final_export_name,
)
from actintrack_app.metadata import load_samples_csv, save_samples_csv
from actintrack_app.project_manager import get_processed_batch_dir
from actintrack_app.utils import (
    GROUP_PREFIX,
    METADATA_DIR,
    SAMPLES_CSV,
    STATUS_RAW_IMPORTED,
    VIDEO_EXTENSIONS,
    file_type_label,
    is_supported_file,
    relative_to_root,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_sample_id(df: pd.DataFrame, group: str) -> str:
    prefix = GROUP_PREFIX[group]
    existing = df[df["group"] == group]["sample_id"].astype(str).tolist()
    numbers = []
    for sid in existing:
        if sid.startswith(f"{prefix}_"):
            try:
                numbers.append(int(sid.split("_", 1)[1]))
            except ValueError:
                pass
    n = max(numbers, default=0) + 1
    return f"{prefix}_{n:04d}"


def _build_sample_record(
    *,
    sample_id: str,
    group: str,
    batch: dict,
    src_path: Path,
    dest_path: Path,
    root: Path,
    frame_number: int,
    notes: str = "",
) -> dict[str, str]:
    is_video = is_video_path(src_path)
    batch_number = int(batch["batch_number"])
    auto_name = auto_export_name_for_sample(
        group=group,
        batch_number=batch_number,
        is_video=is_video,
        frame_number=frame_number,
    )
    return {
        "sample_id": sample_id,
        "group": group,
        "batch_number": str(batch_number),
        "batch_name": str(batch["batch_name"]),
        "batch_id": str(batch["batch_id"]),
        "original_filename": src_path.name,
        "stored_path": relative_to_root(root, dest_path),
        "file_type": file_type_label(src_path),
        "is_video": "true" if is_video else "false",
        "is_image_sequence": "false" if is_video else "true",
        "frame_number": str(frame_number),
        "auto_export_name": auto_name,
        "custom_export_name": "",
        "final_export_name": auto_name,
        "import_date": _utc_now_iso(),
        "processing_status": STATUS_RAW_IMPORTED,
        "annotation_source": "",
        "review_status": "pending",
        "notes": str(notes),
    }


def export_name_exists_in_batch(
    root: Path,
    group: str,
    batch_name: str,
    final_name: str,
    *,
    exclude_sample_id: str | None = None,
) -> bool:
    root = Path(root).resolve()
    df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)
    safe = sanitize_batch_name(batch_name)
    sub = df[
        (df["group"] == group)
        & (df["batch_name"].astype(str).apply(sanitize_batch_name) == safe)
    ]
    for _, row in sub.iterrows():
        if exclude_sample_id and str(row["sample_id"]) == exclude_sample_id:
            continue
        if str(row.get("final_export_name", "")).strip() == final_name:
            return True
    batch_dir = get_processed_batch_dir(root, group, safe)
    if batch_dir.is_dir():
        for ext in (".mp4", ".png", ".json"):
            if (batch_dir / f"{final_name}{ext}").exists():
                return True
            if (batch_dir / f"{final_name}_metadata{ext}").exists():
                return True
    return False


def import_files(
    file_paths: Sequence[str | Path],
    group_name: str,
    batch_name: str,
    batch_id: str,
    root_dir: Path,
    *,
    batch_number: int | None = None,
    notes: str = "",
) -> list[dict]:
    """
    Copy files into raw/<group>/<batch_name>/ and append rows to samples.csv.
    """
    root = Path(root_dir).resolve()
    safe_batch = sanitize_batch_name(batch_name)
    ensure_batch_dirs(root, group_name, safe_batch)
    from actintrack_app.project_manager import get_raw_batch_dir

    raw_dir = get_raw_batch_dir(root, group_name, safe_batch)

    samples_path = root / METADATA_DIR / SAMPLES_CSV
    df = load_samples_csv(samples_path)
    from actintrack_app.batch_manager import parse_batch_number_from_name

    bn = (
        int(batch_number)
        if batch_number is not None
        else parse_batch_number_from_name(safe_batch) or 1
    )
    batch = {
        "batch_name": safe_batch,
        "batch_id": str(batch_id),
        "batch_number": bn,
    }
    created: list[dict] = []

    for src in file_paths:
        src_path = Path(src)
        if not src_path.is_file():
            raise FileNotFoundError(f"File not found: {src_path}")
        if not is_supported_file(src_path):
            raise ValueError(
                f"Unsupported file type: {src_path.suffix}. "
                "Supported: .avi, .mp4, .tif, .tiff, .oib, .oif, .oir, "
                ".png, .jpg, .jpeg"
            )

        is_video = is_video_path(src_path)
        frame_number = 0 if is_video else next_frame_number_in_batch(
            root, group_name, safe_batch
        )

        sample_id = _next_sample_id(df, group_name)
        dest_name = f"{sample_id}{src_path.suffix.lower()}"
        dest_path = raw_dir / dest_name
        shutil.copy2(src_path, dest_path)

        record = _build_sample_record(
            sample_id=sample_id,
            group=group_name,
            batch=batch,
            src_path=src_path,
            dest_path=dest_path,
            root=root,
            frame_number=frame_number,
            notes=notes,
        )
        if batch_number is not None:
            record["batch_number"] = str(batch_number)

        df = load_samples_csv(samples_path)
        df = pd.concat([df, pd.DataFrame([record])], ignore_index=True)
        save_samples_csv(samples_path, df)

        import_result = dict(record)
        import_result["source_path"] = str(src_path.resolve())
        import_result["destination_path"] = str(dest_path.resolve())
        created.append(import_result)
        df = load_samples_csv(samples_path)

    refresh_batch_stats(root, group_name, safe_batch)
    return created


def import_files_smart(
    file_paths: Sequence[str | Path],
    group_name: str,
    root_dir: Path,
    *,
    target_batch: dict | None = None,
    one_batch_per_video: bool = True,
) -> list[dict]:
    """
    Import with video-aware batch rules:
    - Each video → new batch by default.
    - Still images → selected or default batch.
    """
    paths = [Path(p) for p in file_paths if Path(p).is_file()]
    if not paths:
        return []

    root = Path(root_dir).resolve()
    videos = [p for p in paths if p.suffix.lower() in VIDEO_EXTENSIONS]
    stills = [p for p in paths if p not in videos]

    created: list[dict] = []

    for video in videos:
        if one_batch_per_video or target_batch is None:
            batch = create_batch_for_video_import(root, group_name)
        else:
            batch = target_batch
        created.extend(
            import_files(
                [video],
                group_name,
                batch["batch_name"],
                batch["batch_id"],
                root,
                batch_number=int(batch["batch_number"]),
            )
        )

    if stills:
        if target_batch is None:
            from actintrack_app.batch_manager import ensure_default_batch

            target_batch = ensure_default_batch(root, group_name)
        created.extend(
            import_files(
                stills,
                group_name,
                target_batch["batch_name"],
                target_batch["batch_id"],
                root,
                batch_number=int(target_batch["batch_number"]),
            )
        )

    return created


def set_custom_export_name(
    root: Path,
    sample_id: str,
    custom_name: str | None,
) -> dict[str, str]:
    """Update custom/final export name with duplicate check."""
    root = Path(root).resolve()
    samples_path = root / METADATA_DIR / SAMPLES_CSV
    df = load_samples_csv(samples_path)
    mask = df["sample_id"].astype(str) == str(sample_id)
    if not mask.any():
        raise ValueError(f"Sample not found: {sample_id}")

    row = df[mask].iloc[0]
    auto_name = str(row.get("auto_export_name", ""))
    custom = (custom_name or "").strip()
    final = resolve_final_export_name(auto_name, custom or None)
    group = str(row["group"])
    batch_name = str(row["batch_name"])
    if export_name_exists_in_batch(
        root,
        group,
        batch_name,
        final,
        exclude_sample_id=sample_id,
    ):
        raise ValueError(f"Export name already exists in batch: {final}")

    idx = df.index[mask][0]
    df.at[idx, "custom_export_name"] = custom
    df.at[idx, "final_export_name"] = final
    save_samples_csv(samples_path, df)
    return {
        "auto_export_name": auto_name,
        "custom_export_name": custom,
        "final_export_name": final,
    }
