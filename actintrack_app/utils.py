"""Shared constants and helpers for ActinTrackCV."""

from __future__ import annotations

from pathlib import Path

# Biological groups / sample folders currently present in ActinTrackCV.
GROUP_WT_218 = "1_WT_218"
GROUP_WT_550 = "2_WT_550"
GROUP_MUTANT_515 = "3_Mutant_515"
GROUP_MUTANT_175 = "4_Mutant_175"

# Backward-compatible aliases used by the first GUI pass.
GROUP_WT = GROUP_WT_550
GROUP_MUTANT = GROUP_MUTANT_515

GROUPS = (GROUP_WT_218, GROUP_WT_550, GROUP_MUTANT_515, GROUP_MUTANT_175)

GROUP_PREFIX = {
    GROUP_WT_218: "WT218",
    GROUP_WT_550: "WT550",
    GROUP_MUTANT_515: "MUT515",
    GROUP_MUTANT_175: "MUT175",
}

# Supported input formats
SUPPORTED_EXTENSIONS = {
    ".avi",
    ".mp4",
    ".tif",
    ".tiff",
    ".oib",
    ".oif",
    ".oir",
    ".png",
    ".jpg",
    ".jpeg",
}

VIDEO_EXTENSIONS = {".avi", ".mp4"}
IMAGE_EXTENSIONS = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}
RAW_MICROSCOPY_EXTENSIONS = {".oib", ".oif", ".oir"}

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
    if ext in RAW_MICROSCOPY_EXTENSIONS:
        return "raw_microscopy"
    return "image"


def relative_to_root(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root.resolve()))
    except ValueError:
        return str(path)
