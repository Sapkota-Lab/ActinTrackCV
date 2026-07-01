"""Project folder structure and path helpers."""

from __future__ import annotations

import json
from pathlib import Path

from actintrack_app.utils import (
    CROP_METADATA_JSON,
    DATA_FILES_CSV,
    METADATA_DIR,
    PREVIEWS_DIR,
    PROCESSED_DIR,
    RAW_DIR,
    SAMPLES_CSV,
    SCHEMA_V2,
)


def create_project_structure(root_dir: Path) -> None:
    """Create ActinTrackCV project folders under root_dir."""
    root = Path(root_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)

    for sub in (RAW_DIR, PROCESSED_DIR, METADATA_DIR, PREVIEWS_DIR):
        (root / sub).mkdir(exist_ok=True)

    metadata_dir = root / METADATA_DIR
    crop_meta_path = metadata_dir / CROP_METADATA_JSON
    data_files_path = metadata_dir / DATA_FILES_CSV

    if not data_files_path.exists() and not (metadata_dir / SAMPLES_CSV).exists():
        import pandas as pd

        from actintrack_app.condition_group_manager import init_empty_condition_groups
        from actintrack_app.schema_compat import (
            save_data_files,
            save_sample_registry,
            write_workspace_json,
        )
        from actintrack_app.utils import SAMPLES_CSV_COLUMNS

        write_workspace_json(root, schema_version=SCHEMA_V2)
        save_data_files(root, pd.DataFrame(columns=SAMPLES_CSV_COLUMNS))
        save_sample_registry(root, {})
        init_empty_condition_groups(root)

    if not crop_meta_path.exists():
        crop_meta_path.write_text(
            json.dumps({"schema_version": SCHEMA_V2, "data_files": {}}, indent=2),
            encoding="utf-8",
        )


def get_raw_dir(root: Path, group: str) -> Path:
    return root / RAW_DIR / group


def get_raw_batch_dir(root: Path, group: str, batch_name: str) -> Path:
    from actintrack_app.batch_manager import sanitize_batch_name

    return root / RAW_DIR / group / sanitize_batch_name(batch_name)


def get_processed_batch_dir(root: Path, group: str, batch_name: str) -> Path:
    from actintrack_app.batch_manager import sanitize_batch_name

    return root / PROCESSED_DIR / group / sanitize_batch_name(batch_name)


def get_processed_sample_dir(
    root: Path, group: str, batch_name: str, sample_id: str
) -> Path:
    return get_processed_batch_dir(root, group, batch_name) / sample_id


def get_previews_dir(root: Path, group: str) -> Path:
    return root / PREVIEWS_DIR / group


def is_valid_project(root: Path) -> bool:
    root = Path(root).resolve()
    if not root.is_dir():
        return False
    meta = root / METADATA_DIR
    has_data_index = (meta / DATA_FILES_CSV).exists() or (meta / SAMPLES_CSV).exists()
    required = [
        root / RAW_DIR,
        root / PROCESSED_DIR,
        meta,
    ]
    return all(p.exists() for p in required) and has_data_index
