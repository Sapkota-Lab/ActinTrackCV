"""Classify files for the 2D import workflow vs WIP raw/3D formats."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from actintrack_app.utils import (
    IMAGE_EXTENSIONS,
    RAW_MICROSCOPY_EXTENSIONS,
    VIDEO_EXTENSIONS,
)

WIP_MESSAGE = (
    "This file type appears to be a raw or 3D microscopy format. "
    "3D/raw import is planned but not supported in the current 2D workflow."
)

MIXED_MESSAGE = (
    "Cannot import images and video in one step. "
    "Import image files and video files separately."
)

MULTI_VIDEO_MESSAGE = "Select only one .avi or .mp4 file at a time for video import."


class ImportKind(str, Enum):
    IMAGE_SEQUENCE = "image_sequence"
    VIDEO = "video"
    WIP_RAW_3D = "wip_raw_3d"
    MIXED = "mixed"
    EMPTY = "empty"


def _per_file_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in RAW_MICROSCOPY_EXTENSIONS:
        return "wip"
    if ext in {".png", ".jpg", ".jpeg"}:
        return "image"
    if ext in {".tif", ".tiff"}:
        try:
            from actintrack_app.video_processing import get_tiff_page_count

            if get_tiff_page_count(path) > 1:
                return "wip_tiff_stack"
        except Exception:
            pass
        return "image"
    return "unknown"


def classify_paths(paths: list[Path]) -> tuple[ImportKind, list[Path], str]:
    """
    Return (kind, valid_paths, user_message).
    message is empty when selection is valid for import.
    """
    files = [Path(p).resolve() for p in paths if Path(p).is_file()]
    if not files:
        return ImportKind.EMPTY, [], "No files selected."

    kinds = {_per_file_kind(p) for p in files}
    if "unknown" in kinds:
        unknown = [p.name for p in files if _per_file_kind(p) == "unknown"]
        return ImportKind.MIXED, [], f"Unsupported file type: {', '.join(unknown[:3])}"

    if kinds & {"wip", "wip_tiff_stack"}:
        if kinds == {"wip"} or kinds == {"wip_tiff_stack"} or kinds == {"wip", "wip_tiff_stack"}:
            return ImportKind.WIP_RAW_3D, files, WIP_MESSAGE
        return ImportKind.MIXED, [], WIP_MESSAGE + "\n\n" + MIXED_MESSAGE

    if "video" in kinds and "image" in kinds:
        return ImportKind.MIXED, [], MIXED_MESSAGE

    if "video" in kinds:
        if len(files) > 1:
            return ImportKind.MIXED, [], MULTI_VIDEO_MESSAGE
        return ImportKind.VIDEO, files, ""

    if "image" in kinds:
        return ImportKind.IMAGE_SEQUENCE, files, ""

    return ImportKind.MIXED, [], "Could not determine import type for the selected files."


def import_kind_label(kind: ImportKind) -> str:
    labels = {
        ImportKind.IMAGE_SEQUENCE: "Image sequence (2D)",
        ImportKind.VIDEO: "Video timelapse (one sample per file)",
        ImportKind.WIP_RAW_3D: "Raw / 3D microscopy (WIP — not importable)",
        ImportKind.MIXED: "Mixed or invalid selection",
        ImportKind.EMPTY: "No files selected",
    }
    return labels.get(kind, str(kind.value))
