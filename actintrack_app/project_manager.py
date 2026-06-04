"""Project folder structure and path helpers."""

from __future__ import annotations

import json
from pathlib import Path

from actintrack_app.utils import (
    CROP_METADATA_JSON,
    GROUPS,
    METADATA_DIR,
    PREVIEWS_DIR,
    PROCESSED_DIR,
    RAW_DIR,
    SAMPLES_CSV,
)


def create_project_structure(root_dir: Path) -> None:
    """Create ActinTrackCV project folders under root_dir."""
    root = Path(root_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)

    for sub in (RAW_DIR, PROCESSED_DIR, METADATA_DIR, PREVIEWS_DIR):
        (root / sub).mkdir(exist_ok=True)

    for group in GROUPS:
        (root / RAW_DIR / group).mkdir(parents=True, exist_ok=True)
        (root / PROCESSED_DIR / group).mkdir(parents=True, exist_ok=True)
        (root / PREVIEWS_DIR / group).mkdir(parents=True, exist_ok=True)

    metadata_dir = root / METADATA_DIR
    samples_path = metadata_dir / SAMPLES_CSV
    crop_meta_path = metadata_dir / CROP_METADATA_JSON

    if not samples_path.exists():
        from actintrack_app.metadata import create_empty_samples_csv

        create_empty_samples_csv(samples_path)

    if not crop_meta_path.exists():
        crop_meta_path.write_text(
            json.dumps({"samples": {}}, indent=2),
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
    required = [
        root / RAW_DIR,
        root / PROCESSED_DIR,
        root / METADATA_DIR,
        root / METADATA_DIR / SAMPLES_CSV,
    ]
    return all(p.exists() for p in required)
