#!/usr/bin/env python3
"""
Preprocess ActinTrackCV media by cropping the biological 2D tracking ROI.

Compatibility note:
    This file keeps the historical name `preprocess_ab_regions.py`, but it no
    longer crops equal-width A/B/C display panels. Picture1.jpg shows biological
    regions inside the cell: the upper/central actin-rich filament area is kept
    for 2D tracking, while the lower perinuclear/nucleus-adjacent region is
    excluded.

The crop is deterministic and signal-driven:
    1. Build an actin-dominant signal image.
    2. Segment the largest cell-like foreground component.
    3. Compute row-wise signal mass and foreground width.
    4. Find the sustained gradient into the lower perinuclear region.
    5. Apply the detected ROI to images, videos, and TIFF stacks.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

from actintrack_app.image_processing import TrackingCrop, detect_tracking_crop


LOGGER = logging.getLogger("preprocess_tracking_roi")

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
TIFF_EXTENSIONS = {".tif", ".tiff"}
VIDEO_EXTENSIONS = {".avi", ".mp4"}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | TIFF_EXTENSIONS | VIDEO_EXTENSIONS


def iter_input_files(input_path: Path) -> Iterable[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield input_path
        return

    for path in sorted(input_path.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path


def safe_stem(path: Path, input_root: Path) -> str:
    try:
        rel = path.relative_to(input_root if input_root.is_dir() else input_root.parent)
    except ValueError:
        rel = path.name
    text = str(rel)
    for char in ("/", "\\", " ", ":"):
        text = text.replace(char, "_")
    return Path(text).with_suffix("").name


def ensure_output_path(path: Path, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Output exists; use --overwrite to replace: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)


def write_manifest(output_root: Path, rows: list[dict]) -> Path:
    manifest_path = output_root / "tracking_roi_manifest.csv"
    output_root.mkdir(parents=True, exist_ok=True)
    columns = [
        "source_path",
        "output_path",
        "media_type",
        "crop_applied",
        "cutoff_y",
        "roi_x0",
        "roi_y0",
        "roi_x1",
        "roi_y1",
        "confidence",
        "method",
        "signal_source",
        "notes",
    ]
    with manifest_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in columns})
    return manifest_path


def crop_array_spatial(data: np.ndarray, crop: TrackingCrop) -> np.ndarray:
    """Apply crop to the final two axes, assumed to be Y/X."""
    slices = [slice(None)] * data.ndim
    slices[-2] = slice(crop.y0, crop.y1)
    slices[-1] = slice(crop.x0, crop.x1)
    return data[tuple(slices)]


def detection_frame_from_tiff_array(data: np.ndarray) -> np.ndarray:
    """
    Build a 2D preview frame for ROI detection from a TIFF array.

    Last two axes are treated as Y/X for microscopy stacks. Leading Z/T/C axes
    are reduced by maximum projection, with channel 0 preferred when a small
    channel-like axis is present.
    """
    if data.ndim == 2:
        return data
    if data.ndim == 3 and data.shape[-1] in {3, 4}:
        return data[..., :3]
    if data.ndim == 3:
        return np.max(data, axis=0)
    if data.ndim >= 4:
        arr = data
        for axis, size in enumerate(data.shape[:-2]):
            if size in {2, 3, 4}:
                arr = np.take(arr, 0, axis=axis)
                break
        while arr.ndim > 2:
            arr = np.max(arr, axis=0)
        return arr
    raise ValueError(f"Unsupported TIFF array shape: {data.shape}")


def normalise_for_detector(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 2:
        lo, hi = np.percentile(frame, [1, 99.7])
        scaled = np.clip((frame.astype(np.float32) - lo) / (hi - lo + 1e-6), 0, 1)
        return (scaled * 255).astype(np.uint8)
    return frame


def process_image(path: Path, output_root: Path, input_root: Path, overwrite: bool) -> dict:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Could not read image: {path}")

    crop = detect_tracking_crop(image)
    output_path = output_root / f"{safe_stem(path, input_root)}_tracking_roi.png"
    ensure_output_path(output_path, overwrite)
    cropped = image[crop.y0 : crop.y1, crop.x0 : crop.x1]
    cv2.imwrite(str(output_path), cropped, [cv2.IMWRITE_PNG_COMPRESSION, 0])
    return manifest_row(path, output_path, "image", crop)


def process_video(path: Path, output_root: Path, input_root: Path, overwrite: bool) -> dict:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {path}")

    ok, first_frame = cap.read()
    if not ok or first_frame is None:
        cap.release()
        raise RuntimeError(f"Video has no readable frames: {path}")

    crop = detect_tracking_crop(first_frame)
    output_dir = output_root / f"{safe_stem(path, input_root)}_tracking_roi_frames"
    if output_dir.exists() and any(output_dir.iterdir()) and not overwrite:
        cap.release()
        raise FileExistsError(f"Output directory exists; use --overwrite: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    def write_frame(index: int, frame: np.ndarray) -> None:
        cropped = frame[crop.y0 : crop.y1, crop.x0 : crop.x1]
        frame_path = output_dir / f"frame_{index:04d}.png"
        cv2.imwrite(str(frame_path), cropped, [cv2.IMWRITE_PNG_COMPRESSION, 0])

    write_frame(0, first_frame)
    index = 1
    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        write_frame(index, frame)
        index += 1
    cap.release()

    meta_path = output_dir / "tracking_roi.json"
    meta_path.write_text(json.dumps(crop.as_dict(), indent=2), encoding="utf-8")
    row = manifest_row(path, output_dir, "video", crop)
    row["notes"] = f"{index} frame(s) written"
    return row


def process_tiff(path: Path, output_root: Path, input_root: Path, overwrite: bool) -> dict:
    try:
        import tifffile
    except ImportError as exc:
        raise RuntimeError("tifffile is required for TIFF preprocessing") from exc

    with tifffile.TiffFile(str(path)) as tif:
        data = tif.asarray()
        imagej_metadata = dict(tif.imagej_metadata or {})

    detect_frame = normalise_for_detector(detection_frame_from_tiff_array(data))
    crop = detect_tracking_crop(detect_frame)
    cropped = crop_array_spatial(data, crop)

    output_path = output_root / f"{safe_stem(path, input_root)}_tracking_roi.tif"
    ensure_output_path(output_path, overwrite)
    metadata = {
        **imagej_metadata,
        "actintrackcv_crop": crop.as_dict(),
        "actintrackcv_crop_notes": crop.notes,
    }
    tifffile.imwrite(output_path, cropped, metadata=metadata, compression=None)
    return manifest_row(path, output_path, "tiff", crop)


def manifest_row(path: Path, output_path: Path, media_type: str, crop: TrackingCrop) -> dict:
    row = {
        "source_path": str(path),
        "output_path": str(output_path),
        "media_type": media_type,
        "crop_applied": True,
        "cutoff_y": crop.cutoff_y,
        "roi_x0": crop.x0,
        "roi_y0": crop.y0,
        "roi_x1": crop.x1,
        "roi_y1": crop.y1,
        "confidence": crop.confidence,
        "method": crop.method,
        "signal_source": crop.signal_source,
        "notes": crop.notes,
    }
    return row


def process_file(path: Path, output_root: Path, input_root: Path, overwrite: bool) -> dict:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return process_image(path, output_root, input_root, overwrite)
    if suffix in VIDEO_EXTENSIONS:
        return process_video(path, output_root, input_root, overwrite)
    if suffix in TIFF_EXTENSIONS:
        return process_tiff(path, output_root, input_root, overwrite)
    raise ValueError(f"Unsupported file type: {suffix}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Crop ActinTrackCV microscopy media to the upper/central biological "
            "tracking ROI using actin signal gradients."
        )
    )
    parser.add_argument("--input", required=True, type=Path, help="Input file or directory.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("preprocessed_tracking_roi"),
        help="Output directory for cropped ROI media.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files/directories.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect and report crops without writing media.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    input_path = args.input.resolve()
    output_root = args.output.resolve()
    files = list(iter_input_files(input_path))
    if not files:
        raise SystemExit(f"No supported media files found under: {input_path}")

    rows: list[dict] = []
    for path in files:
        try:
            if args.dry_run:
                suffix = path.suffix.lower()
                if suffix in IMAGE_EXTENSIONS:
                    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
                    if image is None:
                        raise RuntimeError(f"Could not read image: {path}")
                    crop = detect_tracking_crop(image)
                elif suffix in VIDEO_EXTENSIONS:
                    cap = cv2.VideoCapture(str(path))
                    ok, frame = cap.read()
                    cap.release()
                    if not ok or frame is None:
                        raise RuntimeError(f"Video has no readable frames: {path}")
                    crop = detect_tracking_crop(frame)
                else:
                    import tifffile

                    data = tifffile.imread(path)
                    crop = detect_tracking_crop(
                        normalise_for_detector(detection_frame_from_tiff_array(data))
                    )
                row = manifest_row(path, Path("DRY_RUN"), path.suffix.lower().lstrip("."), crop)
            else:
                row = process_file(path, output_root, input_path, args.overwrite)
            rows.append(row)
            LOGGER.info(
                "%s cutoff_y=%s roi=(%s,%s)-(%s,%s) confidence=%s",
                path,
                row["cutoff_y"],
                row["roi_x0"],
                row["roi_y0"],
                row["roi_x1"],
                row["roi_y1"],
                row["confidence"],
            )
        except Exception as exc:
            LOGGER.error("Failed %s: %s", path, exc)
            rows.append(
                {
                    "source_path": str(path),
                    "output_path": "",
                    "media_type": path.suffix.lower().lstrip("."),
                    "crop_applied": False,
                    "notes": str(exc),
                }
            )

    manifest_path = write_manifest(output_root, rows)
    LOGGER.info("Wrote manifest: %s", manifest_path)


if __name__ == "__main__":
    main()
