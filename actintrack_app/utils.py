"""Shared constants and helpers for ActinTrackCV."""

from __future__ import annotations

from pathlib import Path

# Biological groups / WT and mutant line folders in the current dataset.
GROUP_WT_218 = "1_WT_218"
GROUP_WT_550 = "2_WT_550"
GROUP_MUTANT_515 = "3_Mutant_515"
GROUP_MUTANT_175 = "4_Mutant_175"

# Backward-compatible aliases used by the first GUI pass.
GROUP_WT = GROUP_WT_550
GROUP_MUTANT = GROUP_MUTANT_515

# Legacy preset groups from the original lab dataset. Not used for new workspaces;
# active Condition Groups are stored per workspace in condition_groups.json.
GROUPS = (GROUP_WT_218, GROUP_WT_550, GROUP_MUTANT_515, GROUP_MUTANT_175)

GROUP_PREFIX = {
    GROUP_WT_218: "WT218",
    GROUP_WT_550: "WT550",
    GROUP_MUTANT_515: "MUT515",
    GROUP_MUTANT_175: "MUT175",
}


def data_id_prefix_for_group(group: str) -> str:
    """Stable export/data_id prefix for a Condition Group (legacy or custom)."""
    import hashlib
    import re

    known = GROUP_PREFIX.get(str(group).strip())
    if known:
        return known
    alnum = re.sub(r"[^A-Za-z0-9]+", "", str(group).strip())
    stem = alnum[:8] if alnum else "GRP"
    tail = hashlib.sha1(str(group).strip().encode("utf-8")).hexdigest()[:4].upper()
    return f"{stem}{tail}"[:16]

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
DATA_FILES_CSV = "data_files.csv"
SAMPLE_REGISTRY_JSON = "sample_registry.json"
CONDITION_GROUPS_JSON = "condition_groups.json"
WORKSPACE_JSON = "workspace.json"
CROP_METADATA_JSON = "crop_metadata.json"

SCHEMA_V1 = 1
SCHEMA_V2 = 2

# Sample processing statuses (samples.csv processing_status)
STATUS_IMPORTED = "imported"
STATUS_RAW_IMPORTED = "raw_imported"
STATUS_UNANNOTATED = "unannotated"
STATUS_CUTOFF_MARKED = "cutoff_marked"  # legacy Phase 1
STATUS_ROI_MARKED = "roi_marked"
STATUS_ROI_PROPAGATED = "roi_propagated_needs_review"
STATUS_ROI_APPROVED = "roi_approved"
STATUS_PROCESSED = "processed"
STATUS_MOTION_INDEX_GENERATED = "motion_index_generated"
STATUS_MOTION_INDEX_FAILED = "motion_index_failed"
STATUS_FAILED = "failed"
STATUS_MISSING_FILE = "missing_file"

# User-facing Sample status labels. Internal enum values are preserved for
# compatibility; this maps them to clean wording (no legacy "raw_imported").
_SAMPLE_STATUS_LABELS = {
    "": "Raw",
    STATUS_IMPORTED: "Raw",
    STATUS_RAW_IMPORTED: "Raw",
    STATUS_UNANNOTATED: "Raw",
    STATUS_CUTOFF_MARKED: "Raw",
    "cutoff_marked": "Raw",
    STATUS_ROI_MARKED: "Cell boundary set",
    STATUS_ROI_PROPAGATED: "Cell boundary set",
    STATUS_ROI_APPROVED: "Cell boundary set",
    STATUS_PROCESSED: "Cell boundary set",
    STATUS_MOTION_INDEX_GENERATED: "Cell boundary set",
    STATUS_MOTION_INDEX_FAILED: "Cell boundary set",
    STATUS_FAILED: "Raw",
    STATUS_MISSING_FILE: "Missing file",
}


def sample_status_label(status: str) -> str:
    """Map an internal processing_status to a clean user-facing label.

    "Raw" means Data exists but no cell boundary is marked. "Cell boundary set"
    means a Cell Boundary exists (auto-suggested or persisted). Metric freshness
    is shown separately.
    """
    return _SAMPLE_STATUS_LABELS.get(str(status).strip(), "Raw")


F_ACTIN_MOTION_INDEX_SUMMARY_CSV = "f_actin_motion_index_summary.csv"

DATA_FILES_CSV_COLUMNS = [
    "data_id",
    "condition_group_id",
    "breed",
    "sample_number",
    "sample_name",
    "sample_id",
    "original_filename",
    "stored_path",
    "file_type",
    "media_type",
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
]

# Legacy v1 columns (data_id exposed as sample_id; registry id as batch_id).
SAMPLES_CSV_COLUMNS = [
    "sample_id",
    "condition_group_id",
    "group",
    "batch_number",
    "batch_name",
    "batch_id",
    "original_filename",
    "stored_path",
    "file_type",
    "media_type",
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
]

RECENT_WORKSPACES_JSON = "recent_workspaces.json"

# Propagation scope keys (legacy internal names; UI shows condition group/sample)
SCOPE_SAME_BATCH = "same_biological_batch"
SCOPE_UNPROCESSED_IN_BATCH = "unprocessed_in_biological_batch"
SCOPE_ALL_IN_GROUP = "all_in_condition_group"
SCOPE_SELECTED = "selected"

UNPROCESSED_STATUSES = frozenset(
    {
        "",
        STATUS_IMPORTED,
        STATUS_RAW_IMPORTED,
        STATUS_UNANNOTATED,
        STATUS_CUTOFF_MARKED,
        "cutoff_marked",
    }
)
PROTECTED_ANNOTATION_STATUSES = frozenset(
    {STATUS_ROI_APPROVED, STATUS_PROCESSED}
)


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
    """Return a project-relative path using portable POSIX separators.

    Metadata rewrites and cross-OS project moves assume ``/`` separators.
    Persist POSIX form regardless of the host OS.
    """
    try:
        return path.relative_to(root.resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def project_relative_parts(stored_path: str) -> tuple[str, ...]:
    """Split a project-relative stored path into components (OS-agnostic)."""
    normalized = str(stored_path).replace("\\", "/").strip("/")
    if not normalized:
        return ()
    return tuple(part for part in normalized.split("/") if part and part != ".")


def join_project_relative(*parts: str) -> str:
    """Join project-relative path components with portable POSIX separators."""
    cleaned: list[str] = []
    for part in parts:
        for piece in str(part).replace("\\", "/").split("/"):
            if piece and piece != ".":
                cleaned.append(piece)
    return "/".join(cleaned)


def replace_project_relative_prefix(
    stored_path: str,
    old_prefix: tuple[str, ...] | list[str],
    new_prefix: tuple[str, ...] | list[str],
) -> str:
    """Replace a leading project-relative prefix; return portable POSIX form.

    Accepts stored paths that used either ``/`` or ``\\`` separators. When the
    leading components do not match ``old_prefix``, returns ``stored_path``
    unchanged.
    """
    old = tuple(str(p) for p in old_prefix)
    new = tuple(str(p) for p in new_prefix)
    if not old:
        raise ValueError("old_prefix must be non-empty.")
    parts = project_relative_parts(stored_path)
    if len(parts) < len(old) or parts[: len(old)] != old:
        return str(stored_path)
    return join_project_relative(*(new + parts[len(old) :]))
