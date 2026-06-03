"""Shared constants and helpers for ActinTrackCV."""

from __future__ import annotations

from pathlib import Path

# Biological groups
GROUP_WT = "2_WT_550"
GROUP_MUTANT = "3_Mutant_515"
GROUPS = (GROUP_WT, GROUP_MUTANT)

GROUP_PREFIX = {
    GROUP_WT: "WT",
    GROUP_MUTANT: "MUT",
}

# Supported input formats
SUPPORTED_EXTENSIONS = {
    ".avi",
    ".mp4",
    ".tif",
    ".tiff",
    ".png",
    ".jpg",
    ".jpeg",
}

VIDEO_EXTENSIONS = {".avi", ".mp4"}
IMAGE_EXTENSIONS = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}

# Project subfolders (relative to root)
RAW_DIR = "raw"
PROCESSED_DIR = "processed"
METADATA_DIR = "metadata"
PREVIEWS_DIR = "previews"
SAMPLES_CSV = "samples.csv"
CROP_METADATA_JSON = "crop_metadata.json"

SAMPLES_CSV_COLUMNS = [
    "sample_id",
    "group",
    "original_filename",
    "stored_path",
    "file_type",
    "import_date",
    "processing_status",
    "notes",
]


def is_supported_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def file_type_label(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in {".tif", ".tiff"}:
        return "tiff"
    return "image"


def relative_to_root(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root.resolve()))
    except ValueError:
        return str(path)
