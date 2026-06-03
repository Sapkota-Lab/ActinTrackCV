"""Import microscopy files into project raw folders."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import pandas as pd

from actintrack_app.metadata import load_samples_csv, save_samples_csv
from actintrack_app.project_manager import get_raw_dir
from actintrack_app.utils import (
    GROUP_PREFIX,
    METADATA_DIR,
    SAMPLES_CSV,
    file_type_label,
    is_supported_file,
    relative_to_root,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_sample_id(df, group: str) -> str:
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


def import_files(
    file_paths: Sequence[str | Path],
    group_name: str,
    root_dir: Path,
) -> list[dict]:
    """
    Copy files into raw/<group>/ and append rows to metadata/samples.csv.

    Returns list of sample records created.
    """
    root = Path(root_dir).resolve()
    raw_dir = get_raw_dir(root, group_name)
    raw_dir.mkdir(parents=True, exist_ok=True)

    samples_path = root / METADATA_DIR / SAMPLES_CSV
    df = load_samples_csv(samples_path)
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

        sample_id = _next_sample_id(df, group_name)
        dest_name = f"{sample_id}{src_path.suffix.lower()}"
        dest_path = raw_dir / dest_name

        shutil.copy2(src_path, dest_path)

        record = {
            "sample_id": sample_id,
            "group": group_name,
            "original_filename": src_path.name,
            "stored_path": relative_to_root(root, dest_path),
            "file_type": file_type_label(src_path),
            "import_date": _utc_now_iso(),
            "processing_status": "imported",
            "notes": "",
        }
        df = load_samples_csv(samples_path)
        df = pd.concat([df, pd.DataFrame([record])], ignore_index=True)
        save_samples_csv(samples_path, df)

        import_result = dict(record)
        import_result["source_path"] = str(src_path.resolve())
        import_result["destination_path"] = str(dest_path.resolve())
        created.append(import_result)

    return created
