"""Thermal phenotyping from radiometric FLIR Ignite JPG exports."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from seedthermal.export_naming import (
    thermal_manifest_path,
    thermal_preview_dir,
    thermal_run_dir,
    thermal_timeseries_csv_path,
)

THERMAL_JPG_EXTENSIONS = {".jpg", ".jpeg"}
TIMESERIES_COLUMNS = [
    "source_file",
    "source_path",
    "capture_time_utc",
    "frame_index",
    "roi_id",
    "roi_label",
    "pixel_count",
    "mean_c",
    "min_c",
    "max_c",
    "std_c",
    "relative_mean_c",
]


@dataclass(frozen=True)
class RoiRect:
    """Rectangle on the thermal array (x, y, width, height in pixel indices)."""

    roi_id: str
    x: int
    y: int
    width: int
    height: int
    label: str = ""

    def __post_init__(self) -> None:
        if self.width < 1 or self.height < 1:
            raise ValueError("ROI width and height must be at least 1.")
        if self.x < 0 or self.y < 0:
            raise ValueError("ROI x and y must be non-negative.")

    @property
    def slice_y(self) -> slice:
        return slice(self.y, self.y + self.height)

    @property
    def slice_x(self) -> slice:
        return slice(self.x, self.x + self.width)

    def clipped(self, array_height: int, array_width: int) -> RoiRect:
        x1 = min(self.x, array_width)
        y1 = min(self.y, array_height)
        x2 = min(self.x + self.width, array_width)
        y2 = min(self.y + self.height, array_height)
        width = max(0, x2 - x1)
        height = max(0, y2 - y1)
        if width < 1 or height < 1:
            raise ValueError(f"ROI {self.roi_id!r} is outside the thermal array.")
        return RoiRect(self.roi_id, x1, y1, width, height, self.label or self.roi_id)


@dataclass
class FlirCapture:
    """One radiometric FLIR still."""

    source_path: Path
    celsius: np.ndarray
    emissivity: float | None = None
    object_distance_m: float | None = None
    capture_time_utc: str = ""
    optical_path: Path | None = None
    thermal_preview_path: Path | None = None


@dataclass
class ThermalRunResult:
    plate_id: str
    run_dir: Path
    rows: list[dict[str, Any]] = field(default_factory=list)
    captures_processed: int = 0
    captures_failed: int = 0
    errors: list[str] = field(default_factory=list)


def parse_roi_spec(spec: str) -> RoiRect:
    """Parse ``id:x,y,w,h`` or ``x,y,w,h`` (id defaults to ``roi``)."""
    text = spec.strip()
    if ":" in text:
        roi_id, coords = text.split(":", 1)
        roi_id = roi_id.strip() or "roi"
    else:
        roi_id = "roi"
        coords = text
    parts = [p.strip() for p in coords.split(",")]
    if len(parts) != 4:
        raise ValueError(f"ROI must be id:x,y,w,h or x,y,w,h — got {spec!r}")
    x, y, w, h = (int(p) for p in parts)
    return RoiRect(roi_id=roi_id, x=x, y=y, width=w, height=h)


def load_roi_config(path: Path) -> tuple[list[RoiRect], RoiRect | None]:
    """Load ROI definitions from JSON."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rois = [_roi_from_dict(entry) for entry in data.get("rois", [])]
    reference = data.get("reference_roi")
    ref_roi = _roi_from_dict(reference) if reference else None
    if not rois:
        raise ValueError("ROI config must include at least one entry under 'rois'.")
    return rois, ref_roi


def _roi_from_dict(entry: dict[str, Any]) -> RoiRect:
    return RoiRect(
        roi_id=str(entry.get("id") or entry.get("roi_id") or "roi"),
        x=int(entry["x"]),
        y=int(entry["y"]),
        width=int(entry.get("w", entry.get("width"))),
        height=int(entry.get("h", entry.get("height"))),
        label=str(entry.get("label", entry.get("id", ""))),
    )


def discover_thermal_jpgs(folder: Path) -> list[Path]:
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise NotADirectoryError(f"Not a directory: {folder}")
    files = [
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in THERMAL_JPG_EXTENSIONS
    ]
    return sorted(files, key=_sort_key_for_capture)


def _sort_key_for_capture(path: Path) -> tuple[str, str]:
    stamp = _capture_time_guess(path)
    return (stamp, path.name.lower())


def _capture_time_guess(path: Path) -> str:
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS

        with Image.open(path) as img:
            exif = img.getexif()
            if exif:
                for tag_id, value in exif.items():
                    if TAGS.get(tag_id) == "DateTimeOriginal" and value:
                        return _exif_datetime_to_iso(str(value))
    except Exception:
        pass
    match = re.search(r"(\d{8})[_-]?(\d{6})", path.stem)
    if match:
        d, t = match.groups()
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}T{t[:2]}:{t[2:4]}:{t[4:6]}Z"
    mtime = path.stat().st_mtime
    return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _exif_datetime_to_iso(value: str) -> str:
    parts = value.strip().replace(":", "-", 2)
    return parts.replace(" ", "T") + "Z"


def load_flir_radiometric(path: Path) -> FlirCapture:
    """Load a radiometric FLIR JPG via flyr."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    try:
        import flyr
    except ImportError as exc:
        raise ImportError("flyr is required. Install with: pip install flyr") from exc

    try:
        thermogram = flyr.unpack(str(path))
    except ValueError as exc:
        if str(exc) == "Incorrect input":
            raise ValueError(
                f"Not a readable radiometric FLIR file: {path}. "
                "Use Ignite downloads, not chat/Photos exports."
            ) from exc
        raise

    celsius = np.asarray(thermogram.celsius, dtype=np.float64)
    meta = thermogram.metadata
    emissivity = _meta_value(meta, "emissivity")
    distance = _meta_value(meta, "object_distance")

    return FlirCapture(
        source_path=path,
        celsius=celsius,
        emissivity=emissivity,
        object_distance_m=distance,
        capture_time_utc=_capture_time_guess(path),
    )


def _meta_value(meta: Any, key: str) -> float | None:
    if hasattr(meta, key):
        value = getattr(meta, key)
    elif isinstance(meta, dict):
        value = meta.get(key)
    else:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def roi_temperature_stats(celsius: np.ndarray, roi: RoiRect) -> dict[str, float | int]:
    height, width = celsius.shape
    clipped = roi.clipped(height, width)
    patch = celsius[clipped.slice_y, clipped.slice_x]
    if patch.size == 0:
        raise ValueError(f"ROI {roi.roi_id!r} has no pixels after clipping.")
    return {
        "pixel_count": int(patch.size),
        "mean_c": float(np.mean(patch)),
        "min_c": float(np.min(patch)),
        "max_c": float(np.max(patch)),
        "std_c": float(np.std(patch)),
    }


def default_frame_roi(celsius: np.ndarray) -> RoiRect:
    height, width = celsius.shape
    return RoiRect("frame", 0, 0, width, height, label="full_frame")


def save_capture_previews(
    source_path: Path,
    run_dir: Path,
    *,
    save_optical: bool = True,
    save_thermal: bool = True,
) -> tuple[Path | None, Path | None]:
    """Write clean optical and false-color thermal previews (no FLIR UI overlay)."""
    import flyr

    preview_dir = thermal_preview_dir(run_dir)
    preview_dir.mkdir(parents=True, exist_ok=True)
    stem = source_path.stem
    optical_path: Path | None = None
    thermal_path: Path | None = None

    thermogram = flyr.unpack(str(source_path))
    if save_optical and thermogram.optical_pil is not None:
        optical_path = preview_dir / f"{stem}_optical.jpg"
        thermogram.optical_pil.save(optical_path, format="JPEG", quality=92)
    if save_thermal:
        thermal_path = preview_dir / f"{stem}_thermal.png"
        thermogram.render_pil().save(thermal_path, format="PNG")
    return optical_path, thermal_path


def run_thermal_batch(
    input_dir: Path,
    output_root: Path,
    plate_id: str,
    *,
    rois: Sequence[RoiRect] | None = None,
    reference_roi: RoiRect | None = None,
    save_previews: bool = True,
    run_timestamp: datetime | None = None,
) -> ThermalRunResult:
    """Process all radiometric JPGs in a folder and write CSV + manifest."""
    input_dir = Path(input_dir).expanduser().resolve()
    run_dir = thermal_run_dir(output_root, plate_id, run_timestamp)
    run_dir.mkdir(parents=True, exist_ok=True)

    result = ThermalRunResult(plate_id=plate_id, run_dir=run_dir)
    sources = discover_thermal_jpgs(input_dir)
    if not sources:
        raise FileNotFoundError(f"No JPG files found in {input_dir}")

    for frame_index, source in enumerate(sources):
        try:
            capture = load_flir_radiometric(source)
            frame_rois = list(rois) if rois else [default_frame_roi(capture.celsius)]
            ref_mean: float | None = None
            if reference_roi is not None:
                ref_stats = roi_temperature_stats(capture.celsius, reference_roi)
                ref_mean = float(ref_stats["mean_c"])

            if save_previews:
                optical_path, thermal_path = save_capture_previews(source, run_dir)
                capture.optical_path = optical_path
                capture.thermal_preview_path = thermal_path

            for roi in frame_rois:
                stats = roi_temperature_stats(capture.celsius, roi)
                relative = (
                    float(stats["mean_c"] - ref_mean)
                    if ref_mean is not None
                    else ""
                )
                result.rows.append(
                    {
                        "source_file": source.name,
                        "source_path": str(source),
                        "capture_time_utc": capture.capture_time_utc,
                        "frame_index": frame_index,
                        "roi_id": roi.roi_id,
                        "roi_label": roi.label or roi.roi_id,
                        "pixel_count": stats["pixel_count"],
                        "mean_c": round(stats["mean_c"], 4),
                        "min_c": round(stats["min_c"], 4),
                        "max_c": round(stats["max_c"], 4),
                        "std_c": round(stats["std_c"], 4),
                        "relative_mean_c": (
                            round(relative, 4) if relative != "" else ""
                        ),
                    }
                )
            result.captures_processed += 1
        except Exception as exc:
            result.captures_failed += 1
            result.errors.append(f"{source.name}: {exc}")

    _write_timeseries_csv(thermal_timeseries_csv_path(run_dir), result.rows)
    _write_manifest(run_dir, result, input_dir, rois, reference_roi)
    return result


def _write_timeseries_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TIMESERIES_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _write_manifest(
    run_dir: Path,
    result: ThermalRunResult,
    input_dir: Path,
    rois: Sequence[RoiRect] | None,
    reference_roi: RoiRect | None,
) -> None:
    manifest = {
        "schema_version": 1,
        "plate_id": result.plate_id,
        "input_dir": str(input_dir),
        "run_dir": str(run_dir),
        "captures_processed": result.captures_processed,
        "captures_failed": result.captures_failed,
        "errors": result.errors,
        "timeseries_csv": str(thermal_timeseries_csv_path(run_dir)),
        "preview_dir": str(thermal_preview_dir(run_dir)),
        "rois": [asdict(r) for r in rois] if rois else "full_frame",
        "reference_roi": asdict(reference_roi) if reference_roi else None,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    thermal_manifest_path(run_dir).write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
