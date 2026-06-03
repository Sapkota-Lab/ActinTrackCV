#!/usr/bin/env python3
"""
Preprocess ActinTrackCV microscopy data by preserving A/B regions and removing C.

The crop core is intentionally independent of file readers:

    reader -> MicroscopyAsset -> ABCropper -> writer

This lets future raw microscopy readers (.oif/.oir/etc.) be added without
changing the A/B crop logic.

Current support:
    - TIFF / TIF stacks through tifffile
    - AVI / MP4 videos through OpenCV, written as uncompressed TIFF stacks
      when tifffile is available, otherwise as lossless PNG frame folders

Runtime dependencies:
    pip install numpy tifffile opencv-python

Default behavior is conservative. In "auto" layout mode the script only crops
files that look like A/B/C horizontal composites. Single-panel videos and raw
channel stacks are passed through unchanged unless --layout abc-horizontal is
provided.

Examples:
    python preprocess_ab_regions.py --input raw_source --output preprocessed_ab

    python preprocess_ab_regions.py \
        --input raw_source/1_WT_218/Montage_of_MAX_01.tif \
        --output preprocessed_ab \
        --layout abc-horizontal

    python preprocess_ab_regions.py \
        --input raw_source/2_WT_550/01.avi \
        --output preprocessed_ab \
        --layout abc-horizontal \
        --pixel-size-x-um 0.138 \
        --pixel-size-y-um 0.138
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol

import numpy as np


LOGGER = logging.getLogger("preprocess_ab_regions")

SUPPORTED_IMAGE_EXTS = {".tif", ".tiff"}
SUPPORTED_VIDEO_EXTS = {".avi", ".mp4"}
FUTURE_RAW_EXT_PREFIX = ".o"


@dataclass
class SpatialScale:
    """Physical scale metadata for spatial axes."""

    x_um_per_px: Optional[float] = None
    y_um_per_px: Optional[float] = None
    z_um_per_slice: Optional[float] = None
    t_seconds: Optional[float] = None
    source: str = "unknown"

    def has_xy(self) -> bool:
        return self.x_um_per_px is not None and self.y_um_per_px is not None


@dataclass
class CropBoundary:
    """Spatial X-axis crop expressed in both physical and pixel coordinates."""

    start_px: int
    end_px: int
    width_px: int
    start_um: Optional[float]
    end_um: Optional[float]
    total_width_um: Optional[float]
    kept_fraction: float
    discarded_fraction: float
    scale_source: str


@dataclass
class CropResult:
    data: np.ndarray
    axes: str
    boundary: Optional[CropBoundary]
    crop_applied: bool
    layout: str
    layout_reason: str
    panel_boundaries_px: dict[str, tuple[int, int]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class MicroscopyAsset:
    """In-memory representation shared by all readers."""

    path: Path
    data: np.ndarray
    axes: str
    dtype: str
    scale: SpatialScale
    metadata: dict[str, Any] = field(default_factory=dict)
    reader_name: str = "unknown"


class Reader(Protocol):
    name: str
    extensions: set[str]

    def read(self, path: Path, fallback_scale: SpatialScale) -> MicroscopyAsset:
        ...


def _json_safe(value: Any, max_string: int = 20000) -> Any:
    """Convert nested metadata objects into JSON-serializable values."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > max_string:
            return value[:max_string] + "...[truncated]"
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(k): _json_safe(v, max_string=max_string) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v, max_string=max_string) for v in value]
    return repr(value)


def _parse_key_value_info(info: str) -> dict[str, str]:
    """Parse ImageJ/Olympus Info blocks with 'key = value' lines."""
    parsed: dict[str, str] = {}
    for line in info.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip().strip("'")
    return parsed


def _float_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        value_f = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value_f):
        return None
    return value_f


def _olympus_axis_scale_um(info_map: dict[str, str], axis_index: int) -> Optional[float]:
    """Extract um/px from Olympus-style '[Axis N Parameters Common]' metadata."""
    prefix = f"[Axis {axis_index} Parameters Common]"
    unit = info_map.get(f"{prefix} UnitName") or info_map.get(f"{prefix} PixUnit")
    if unit and unit.lower() not in {"um", "micron", "micrometer", "micrometre"}:
        return None

    start = _float_or_none(info_map.get(f"{prefix} StartPosition"))
    end = _float_or_none(info_map.get(f"{prefix} EndPosition"))
    max_size = _float_or_none(info_map.get(f"{prefix} MaxSize"))
    gui_max_size = _float_or_none(info_map.get(f"{prefix} GUI MaxSize"))
    size = max_size or gui_max_size

    if start is None or end is None or size is None or size <= 0:
        return None
    extent = abs(end - start)
    if extent <= 0:
        return None
    return extent / size


def _resolution_to_um_per_px(
    resolution_value: Any, resolution_unit: Any, imagej_unit: Optional[str]
) -> Optional[float]:
    """Convert TIFF resolution tags into um/px where possible."""
    if resolution_value is None:
        return None

    try:
        numerator, denominator = resolution_value
        pixels_per_unit = float(numerator) / float(denominator)
    except Exception:
        pixels_per_unit = _float_or_none(resolution_value) or 0.0

    if pixels_per_unit <= 0:
        return None

    # TIFF units: 1 none, 2 inch, 3 centimeter. ImageJ often pairs unit=micron
    # with unitless resolution where the value is pixels per micron.
    try:
        unit_int = int(resolution_unit) if resolution_unit is not None else 1
    except Exception:
        unit_int = 1

    if imagej_unit and imagej_unit.lower() in {"micron", "um", "micrometer", "micrometre"}:
        return 1.0 / pixels_per_unit
    if unit_int == 2:
        return 25400.0 / pixels_per_unit
    if unit_int == 3:
        return 10000.0 / pixels_per_unit
    return None


def _merge_scale(primary: SpatialScale, fallback: SpatialScale) -> SpatialScale:
    return SpatialScale(
        x_um_per_px=primary.x_um_per_px or fallback.x_um_per_px,
        y_um_per_px=primary.y_um_per_px or fallback.y_um_per_px,
        z_um_per_slice=primary.z_um_per_slice or fallback.z_um_per_slice,
        t_seconds=primary.t_seconds or fallback.t_seconds,
        source=primary.source if primary.has_xy() else fallback.source,
    )


def read_sidecar_scale(path: Path) -> SpatialScale:
    """Read optional per-file scale metadata from JSON sidecars."""
    candidates = [
        path.with_suffix(path.suffix + ".json"),
        path.with_suffix(".metadata.json"),
        path.parent / "metadata.json",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text())
        except Exception as exc:
            LOGGER.warning("Could not read metadata sidecar %s: %s", candidate, exc)
            continue

        return SpatialScale(
            x_um_per_px=_float_or_none(
                payload.get("pixel_size_x_um")
                or payload.get("x_um_per_px")
                or payload.get("PhysicalSizeX")
            ),
            y_um_per_px=_float_or_none(
                payload.get("pixel_size_y_um")
                or payload.get("y_um_per_px")
                or payload.get("PhysicalSizeY")
            ),
            z_um_per_slice=_float_or_none(
                payload.get("z_um_per_slice")
                or payload.get("pixel_size_z_um")
                or payload.get("PhysicalSizeZ")
            ),
            t_seconds=_float_or_none(
                payload.get("acquisition_interval_s")
                or payload.get("time_interval_s")
                or payload.get("t_seconds")
            ),
            source=f"sidecar:{candidate.name}",
        )

    return SpatialScale(source="none")


class TiffReader:
    name = "tifffile"
    extensions = SUPPORTED_IMAGE_EXTS

    def read(self, path: Path, fallback_scale: SpatialScale) -> MicroscopyAsset:
        try:
            import tifffile
        except ImportError as exc:
            raise RuntimeError("tifffile is required for TIFF preprocessing") from exc

        with tifffile.TiffFile(path) as tif:
            series = tif.series[0]
            data = series.asarray()
            axes = series.axes or infer_axes(data)
            page0 = tif.pages[0]
            imagej_metadata = tif.imagej_metadata or {}
            tags = {
                tag.name: _json_safe(tag.value)
                for tag in page0.tags.values()
                if tag.name in {"XResolution", "YResolution", "ResolutionUnit", "ImageDescription"}
            }
            scale = self._extract_scale(tif, page0, imagej_metadata)

            metadata = {
                "series_axes": axes,
                "series_shape": list(series.shape),
                "imagej_metadata": _json_safe(imagej_metadata),
                "selected_tags": tags,
            }

        sidecar_scale = read_sidecar_scale(path)
        merged_fallback = _merge_scale(sidecar_scale, fallback_scale)
        scale = _merge_scale(scale, merged_fallback)

        return MicroscopyAsset(
            path=path,
            data=data,
            axes=axes,
            dtype=str(data.dtype),
            scale=scale,
            metadata=metadata,
            reader_name=self.name,
        )

    def _extract_scale(self, tif: Any, page0: Any, imagej_metadata: dict[str, Any]) -> SpatialScale:
        info_text = str(imagej_metadata.get("Info") or "")
        info_map = _parse_key_value_info(info_text)

        x_um = _olympus_axis_scale_um(info_map, 0)
        y_um = _olympus_axis_scale_um(info_map, 1)

        source = "olympus-axis-info" if x_um and y_um else "tiff-tags"

        imagej_unit = imagej_metadata.get("unit")
        if x_um is None:
            x_um = _resolution_to_um_per_px(
                page0.tags.get("XResolution").value if "XResolution" in page0.tags else None,
                page0.tags.get("ResolutionUnit").value if "ResolutionUnit" in page0.tags else None,
                imagej_unit,
            )
        if y_um is None:
            y_um = _resolution_to_um_per_px(
                page0.tags.get("YResolution").value if "YResolution" in page0.tags else None,
                page0.tags.get("ResolutionUnit").value if "ResolutionUnit" in page0.tags else None,
                imagej_unit,
            )

        z_um = _float_or_none(imagej_metadata.get("spacing"))
        if z_um is None:
            z_interval_nm = _float_or_none(info_map.get("[Axis 3 Parameters Common] Interval"))
            if z_interval_nm is not None and z_interval_nm > 0:
                z_um = z_interval_nm / 1000.0

        t_seconds = _float_or_none(imagej_metadata.get("finterval"))
        t_interval_ms = _float_or_none(info_map.get("[Axis 4 Parameters Common] Interval"))
        if t_seconds is None and t_interval_ms is not None and t_interval_ms > 0:
            t_seconds = t_interval_ms / 1000.0

        if x_um is None or y_um is None:
            source = "partial-or-missing"

        return SpatialScale(
            x_um_per_px=x_um,
            y_um_per_px=y_um,
            z_um_per_slice=z_um,
            t_seconds=t_seconds,
            source=source,
        )


class VideoReader:
    name = "opencv-video"
    extensions = SUPPORTED_VIDEO_EXTS

    def read(self, path: Path, fallback_scale: SpatialScale) -> MicroscopyAsset:
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("opencv-python is required for AVI/MP4 preprocessing") from exc

        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video file: {path}")

        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        frames: list[np.ndarray] = []
        while True:
            ok, frame_bgr = cap.read()
            if not ok:
                break
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            frames.append(frame_rgb)
        cap.release()

        if not frames:
            raise RuntimeError(f"No frames decoded from video file: {path}")

        data = np.stack(frames, axis=0)
        sidecar_scale = read_sidecar_scale(path)
        scale = _merge_scale(sidecar_scale, fallback_scale)

        metadata = {
            "opencv_frame_count": frame_count,
            "decoded_frame_count": len(frames),
            "opencv_fps": fps,
            "width_px": width,
            "height_px": height,
            "note": (
                "OpenCV FPS is export playback metadata. Use acquisition metadata "
                "for biological velocity calculations."
            ),
        }

        if scale.t_seconds is None and fps > 0:
            metadata["derived_playback_frame_interval_s"] = 1.0 / fps

        return MicroscopyAsset(
            path=path,
            data=data,
            axes="TYXS",
            dtype=str(data.dtype),
            scale=scale,
            metadata=metadata,
            reader_name=self.name,
        )


class FutureORawReader:
    """Placeholder for Olympus/Bio-Formats style raw readers (.oif/.oir/.oib)."""

    name = "future-o-format-placeholder"
    extensions = {".oif", ".oir", ".oib"}

    def read(self, path: Path, fallback_scale: SpatialScale) -> MicroscopyAsset:
        raise NotImplementedError(
            f"{path.suffix} raw microscopy files need a dedicated reader "
            "(for example Bio-Formats, aicsimageio, or an Olympus-specific reader). "
            "Add a Reader implementation and register it in ReaderRegistry."
        )


class ReaderRegistry:
    def __init__(self) -> None:
        self._readers: list[Reader] = [TiffReader(), VideoReader(), FutureORawReader()]

    def for_path(self, path: Path) -> Optional[Reader]:
        suffix = path.suffix.lower()
        for reader in self._readers:
            if suffix in reader.extensions:
                return reader
        if suffix.startswith(FUTURE_RAW_EXT_PREFIX):
            return FutureORawReader()
        return None


def infer_axes(data: np.ndarray) -> str:
    """Best-effort axes for data lacking reader metadata."""
    if data.ndim == 2:
        return "YX"
    if data.ndim == 3 and data.shape[-1] in {3, 4}:
        return "YXS"
    if data.ndim == 3:
        return "ZYX"
    if data.ndim == 4 and data.shape[-1] in {3, 4}:
        return "TYXS"
    if data.ndim == 4:
        return "ZCYX"
    raise ValueError(f"Cannot infer axes for shape {data.shape}")


def spatial_axis_indices(axes: str, shape: tuple[int, ...]) -> tuple[int, int]:
    axes = axes.upper()
    if "Y" in axes and "X" in axes:
        return axes.index("Y"), axes.index("X")
    if len(shape) < 2:
        raise ValueError(f"Data shape has no spatial axes: {shape}")
    return len(shape) - 2, len(shape) - 1


def _find_display_int(metadata: dict[str, Any], key: str) -> Optional[int]:
    """Search nested TIFF metadata text for display-layout keys."""
    as_text = json.dumps(_json_safe(metadata))
    match = re.search(rf"{re.escape(key)}\s*=\s*(\d+)", as_text)
    if not match:
        return None
    return int(match.group(1))


def detect_layout(asset: MicroscopyAsset, requested_layout: str) -> tuple[str, str]:
    """Return effective layout and reason."""
    if requested_layout != "auto":
        return requested_layout, f"requested:{requested_layout}"

    _, x_axis = spatial_axis_indices(asset.axes, asset.data.shape)
    y_axis, _ = spatial_axis_indices(asset.axes, asset.data.shape)
    width = asset.data.shape[x_axis]
    height = asset.data.shape[y_axis]

    columns = _find_display_int(asset.metadata, "[2D Display] Columns")
    view_count = _find_display_int(asset.metadata, "[2D Display] View Cnt")
    if columns and columns >= 3:
        return "abc-horizontal", "metadata:[2D Display] Columns >= 3"
    if view_count and view_count >= 3:
        return "abc-horizontal", "metadata:[2D Display] View Cnt >= 3"

    # Conservative visual-layout heuristic for rendered A/B/C composites like
    # Picture1.jpg: three tall panels side-by-side often have W/H around 1.5.
    # We do not auto-crop true microscopy channel stacks (C axis) unless display
    # metadata says it is a 3-panel rendering. RGB sample axes (S) are display
    # channels, not microscopy channels, so they can still be A/B/C composites.
    axes = asset.axes.upper()
    has_microscopy_channel_axis = "C" in axes
    aspect = width / height if height else 0.0
    if not has_microscopy_channel_axis and 1.20 <= aspect <= 3.50:
        return "abc-horizontal", f"auto-aspect:{aspect:.3f}"

    return "single-or-raw", "auto:no-abc-layout-detected"


class ABCropper:
    """Crop A/B/C horizontal composites by physical relative boundaries."""

    def __init__(
        self,
        panel_count: int = 3,
        keep_panel_count: int = 2,
        require_scale: bool = False,
    ) -> None:
        if panel_count <= 0:
            raise ValueError("panel_count must be positive")
        if keep_panel_count <= 0 or keep_panel_count > panel_count:
            raise ValueError("keep_panel_count must be in [1, panel_count]")
        self.panel_count = panel_count
        self.keep_panel_count = keep_panel_count
        self.require_scale = require_scale

    def crop(self, asset: MicroscopyAsset, requested_layout: str) -> CropResult:
        layout, reason = detect_layout(asset, requested_layout)
        if layout in {"single", "single-or-raw", "none"}:
            return CropResult(
                data=asset.data,
                axes=asset.axes,
                boundary=None,
                crop_applied=False,
                layout=layout,
                layout_reason=reason,
                warnings=[],
            )
        if layout != "abc-horizontal":
            raise ValueError(f"Unsupported layout: {layout}")

        y_axis, x_axis = spatial_axis_indices(asset.axes, asset.data.shape)
        width_px = int(asset.data.shape[x_axis])
        boundary, warnings = self._compute_boundary(width_px, asset.scale)

        slices: list[slice] = [slice(None)] * asset.data.ndim
        slices[x_axis] = slice(boundary.start_px, boundary.end_px)
        cropped = asset.data[tuple(slices)]

        panel_boundaries = self._panel_boundaries(boundary.end_px)

        return CropResult(
            data=cropped,
            axes=asset.axes,
            boundary=boundary,
            crop_applied=True,
            layout=layout,
            layout_reason=reason,
            panel_boundaries_px=panel_boundaries,
            warnings=warnings,
        )

    def _compute_boundary(self, width_px: int, scale: SpatialScale) -> tuple[CropBoundary, list[str]]:
        warnings: list[str] = []
        kept_fraction = self.keep_panel_count / self.panel_count
        discarded_fraction = 1.0 - kept_fraction

        if scale.x_um_per_px is not None:
            total_width_um = width_px * scale.x_um_per_px
            start_um = 0.0
            end_um = total_width_um * kept_fraction
            end_px = int(round(end_um / scale.x_um_per_px))
            scale_source = scale.source
        else:
            if self.require_scale:
                raise ValueError(
                    "No X pixel-to-micron scale found. Provide sidecar metadata, "
                    "--pixel-size-x-um, or disable --require-physical-scale."
                )
            total_width_um = None
            start_um = None
            end_um = None
            end_px = int(round(width_px * kept_fraction))
            scale_source = "unitless-relative-fraction"
            warnings.append(
                "No X physical scale found; used unitless relative panel fraction. "
                "Output is spatially correct for equal-panel composites but lacks um bounds."
            )

        end_px = max(1, min(width_px, end_px))

        return (
            CropBoundary(
                start_px=0,
                end_px=end_px,
                width_px=end_px,
                start_um=start_um,
                end_um=end_um,
                total_width_um=total_width_um,
                kept_fraction=kept_fraction,
                discarded_fraction=discarded_fraction,
                scale_source=scale_source,
            ),
            warnings,
        )

    def _panel_boundaries(self, ab_width_px: int) -> dict[str, tuple[int, int]]:
        panel_width = ab_width_px / self.keep_panel_count
        out: dict[str, tuple[int, int]] = {}
        for i, label in enumerate(["a", "b"][: self.keep_panel_count]):
            start = int(round(i * panel_width))
            end = int(round((i + 1) * panel_width))
            out[label] = (start, end)
        return out


class OutputWriter:
    def __init__(self, output_root: Path, write_panels: bool = True) -> None:
        self.output_root = output_root
        self.write_panels = write_panels
        self.output_root.mkdir(parents=True, exist_ok=True)

    def write(self, asset: MicroscopyAsset, result: CropResult) -> dict[str, Any]:
        used_png_video_fallback = False
        if asset.path.suffix.lower() in SUPPORTED_IMAGE_EXTS:
            output_path = self._write_tiff(asset, result, suffix="_ab.tif")
        elif asset.path.suffix.lower() in SUPPORTED_VIDEO_EXTS:
            try:
                output_path = self._write_tiff(asset, result, suffix="_ab_stack.tif")
            except RuntimeError as exc:
                if "tifffile is required" not in str(exc):
                    raise
                output_path = self._write_video_png_frames(asset, result, suffix="_ab_frames")
                used_png_video_fallback = True
        else:
            raise ValueError(f"Unsupported output type for {asset.path}")

        panel_paths: dict[str, str] = {}
        if self.write_panels and result.crop_applied and result.panel_boundaries_px:
            if used_png_video_fallback:
                panel_paths = self._write_panel_png_frames(asset, result)
            else:
                panel_paths = self._write_panel_tiffs(asset, result)

        sidecar_path = Path(str(output_path) + ".metadata.json")
        metadata = self._metadata_payload(asset, result, output_path, panel_paths)
        sidecar_path.write_text(json.dumps(metadata, indent=2, sort_keys=True))

        return {
            "source_path": str(asset.path),
            "output_path": str(output_path),
            "metadata_path": str(sidecar_path),
            "panel_paths": panel_paths,
            "crop_applied": result.crop_applied,
            "layout": result.layout,
            "layout_reason": result.layout_reason,
            "warnings": "; ".join(result.warnings),
        }

    def _target_path(self, source: Path, suffix: str) -> Path:
        rel_name = "_".join(source.with_suffix("").parts[-3:])
        rel_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", rel_name)
        return self.output_root / f"{rel_name}{suffix}"

    def _write_tiff(self, asset: MicroscopyAsset, result: CropResult, suffix: str) -> Path:
        try:
            import tifffile
        except ImportError as exc:
            raise RuntimeError("tifffile is required for writing lossless TIFF outputs") from exc

        output_path = self._target_path(asset.path, suffix)
        metadata = self._tiff_metadata(asset, result)

        kwargs: dict[str, Any] = {
            "metadata": metadata,
            "compression": None,
        }

        # imagej=True works well for common microscopy axes such as ZCYX/TYX.
        # Avoid it for sample-axis RGB video stacks because ImageJ metadata
        # support for TYXS is less predictable.
        if "S" not in result.axes.upper():
            kwargs["imagej"] = True

        tifffile.imwrite(output_path, result.data, **kwargs)
        return output_path

    def _write_video_png_frames(self, asset: MicroscopyAsset, result: CropResult, suffix: str) -> Path:
        """Write video-like TYXS/TYX data as lossless PNG frames."""
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("opencv-python is required for PNG frame fallback output") from exc

        output_dir = self._target_path(asset.path, suffix)
        output_dir.mkdir(parents=True, exist_ok=True)

        data = result.data
        axes = result.axes.upper()
        if "T" not in axes:
            data = np.expand_dims(data, axis=0)
            axes = "T" + axes

        t_axis = axes.index("T")
        moved = np.moveaxis(data, t_axis, 0)
        for frame_index, frame in enumerate(moved):
            frame_path = output_dir / f"{asset.path.stem}_ab_f{frame_index:04d}.png"
            self._write_png_frame(frame_path, frame)

        return output_dir

    def _write_panel_tiffs(self, asset: MicroscopyAsset, result: CropResult) -> dict[str, str]:
        try:
            import tifffile
        except ImportError as exc:
            raise RuntimeError("tifffile is required for writing panel TIFF outputs") from exc

        _, x_axis = spatial_axis_indices(result.axes, result.data.shape)
        paths: dict[str, str] = {}

        for label, (start, end) in result.panel_boundaries_px.items():
            slices: list[slice] = [slice(None)] * result.data.ndim
            slices[x_axis] = slice(start, end)
            panel_data = result.data[tuple(slices)]
            output_path = self._target_path(asset.path, f"_{label}.tif")
            metadata = self._tiff_metadata(asset, result)
            metadata["actintrackcv_panel"] = label
            tifffile.imwrite(output_path, panel_data, metadata=metadata, compression=None)
            paths[label] = str(output_path)

        return paths

    def _write_panel_png_frames(self, asset: MicroscopyAsset, result: CropResult) -> dict[str, str]:
        _, x_axis = spatial_axis_indices(result.axes, result.data.shape)
        paths: dict[str, str] = {}

        for label, (start, end) in result.panel_boundaries_px.items():
            slices: list[slice] = [slice(None)] * result.data.ndim
            slices[x_axis] = slice(start, end)
            panel_data = result.data[tuple(slices)]
            panel_result = CropResult(
                data=panel_data,
                axes=result.axes,
                boundary=result.boundary,
                crop_applied=result.crop_applied,
                layout=result.layout,
                layout_reason=f"{result.layout_reason};panel:{label}",
            )
            output_dir = self._write_video_png_frames(asset, panel_result, suffix=f"_{label}_frames")
            paths[label] = str(output_dir)

        return paths

    def _write_png_frame(self, path: Path, frame: np.ndarray) -> None:
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("opencv-python is required for PNG frame fallback output") from exc

        frame_to_write = frame
        if frame_to_write.ndim == 3 and frame_to_write.shape[-1] == 3:
            frame_to_write = cv2.cvtColor(frame_to_write, cv2.COLOR_RGB2BGR)
        elif frame_to_write.ndim == 3 and frame_to_write.shape[-1] == 4:
            frame_to_write = cv2.cvtColor(frame_to_write, cv2.COLOR_RGBA2BGRA)
        cv2.imwrite(str(path), frame_to_write, [cv2.IMWRITE_PNG_COMPRESSION, 0])

    def _tiff_metadata(self, asset: MicroscopyAsset, result: CropResult) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "axes": result.axes,
            "actintrackcv_source": str(asset.path),
            "actintrackcv_layout": result.layout,
            "actintrackcv_crop_applied": result.crop_applied,
        }
        if asset.scale.x_um_per_px is not None:
            metadata["PhysicalSizeX"] = asset.scale.x_um_per_px
            metadata["PhysicalSizeXUnit"] = "um"
        if asset.scale.y_um_per_px is not None:
            metadata["PhysicalSizeY"] = asset.scale.y_um_per_px
            metadata["PhysicalSizeYUnit"] = "um"
        if asset.scale.z_um_per_slice is not None:
            metadata["spacing"] = asset.scale.z_um_per_slice
            metadata["unit"] = "micron"
        if result.boundary is not None:
            metadata["actintrackcv_crop_boundary"] = asdict(result.boundary)
        return metadata

    def _metadata_payload(
        self,
        asset: MicroscopyAsset,
        result: CropResult,
        output_path: Path,
        panel_paths: dict[str, str],
    ) -> dict[str, Any]:
        return {
            "source_path": str(asset.path),
            "output_path": str(output_path),
            "panel_paths": panel_paths,
            "reader": asset.reader_name,
            "input_axes": asset.axes,
            "output_axes": result.axes,
            "input_shape": list(asset.data.shape),
            "output_shape": list(result.data.shape),
            "dtype": asset.dtype,
            "spatial_scale": asdict(asset.scale),
            "crop_applied": result.crop_applied,
            "layout": result.layout,
            "layout_reason": result.layout_reason,
            "crop_boundary": asdict(result.boundary) if result.boundary else None,
            "panel_boundaries_px": result.panel_boundaries_px,
            "warnings": result.warnings,
            "original_metadata": _json_safe(asset.metadata),
        }


def discover_inputs(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    if not input_path.is_dir():
        raise FileNotFoundError(input_path)

    paths: list[Path] = []
    for path in sorted(input_path.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in SUPPORTED_IMAGE_EXTS or suffix in SUPPORTED_VIDEO_EXTS or suffix.startswith(FUTURE_RAW_EXT_PREFIX):
            paths.append(path)
    return paths


def write_manifest(output_root: Path, records: list[dict[str, Any]]) -> Path:
    manifest_path = output_root / "preprocess_manifest.csv"
    fieldnames = [
        "source_path",
        "output_path",
        "metadata_path",
        "crop_applied",
        "layout",
        "layout_reason",
        "warnings",
    ]
    with manifest_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    return manifest_path


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crop ActinTrackCV A/B/C microscopy composites to preserve A/B and remove C."
    )
    parser.add_argument("--input", required=True, type=Path, help="Input file or directory.")
    parser.add_argument("--output", required=True, type=Path, help="Output directory.")
    parser.add_argument(
        "--layout",
        choices=["auto", "abc-horizontal", "single", "none"],
        default="auto",
        help=(
            "Layout policy. 'auto' conservatively detects A/B/C composites; "
            "'abc-horizontal' forces left-two-of-three crop; 'single'/'none' pass through."
        ),
    )
    parser.add_argument(
        "--require-physical-scale",
        action="store_true",
        help="Fail if X/Y pixel-to-micron metadata are unavailable.",
    )
    parser.add_argument(
        "--pixel-size-x-um",
        type=float,
        default=None,
        help="Fallback X pixel size in microns, useful for videos with no embedded scale.",
    )
    parser.add_argument(
        "--pixel-size-y-um",
        type=float,
        default=None,
        help="Fallback Y pixel size in microns, useful for videos with no embedded scale.",
    )
    parser.add_argument(
        "--z-step-um",
        type=float,
        default=None,
        help="Fallback Z spacing in microns.",
    )
    parser.add_argument(
        "--time-interval-s",
        type=float,
        default=None,
        help="Fallback acquisition interval in seconds. Prefer microscope metadata.",
    )
    parser.add_argument(
        "--no-panel-outputs",
        action="store_true",
        help="Only write combined A/B outputs; do not write separate A and B panel TIFFs.",
    )
    parser.add_argument(
        "--fail-on-unsupported",
        action="store_true",
        help="Fail instead of warning when an unsupported/future raw format is encountered.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read inputs and compute crop decisions without writing outputs.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable detailed logging.")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    fallback_scale = SpatialScale(
        x_um_per_px=args.pixel_size_x_um,
        y_um_per_px=args.pixel_size_y_um,
        z_um_per_slice=args.z_step_um,
        t_seconds=args.time_interval_s,
        source="cli-fallback" if args.pixel_size_x_um or args.pixel_size_y_um else "none",
    )

    registry = ReaderRegistry()
    cropper = ABCropper(require_scale=args.require_physical_scale)
    writer = OutputWriter(args.output, write_panels=not args.no_panel_outputs)

    input_paths = discover_inputs(args.input)
    if not input_paths:
        LOGGER.warning("No supported microscopy inputs found under %s", args.input)
        return 0

    records: list[dict[str, Any]] = []
    failures = 0

    for path in input_paths:
        reader = registry.for_path(path)
        if reader is None:
            continue
        LOGGER.info("Processing %s", path)
        try:
            asset = reader.read(path, fallback_scale=fallback_scale)
            result = cropper.crop(asset, requested_layout=args.layout)
            LOGGER.info(
                "%s layout=%s crop=%s shape %s -> %s",
                path.name,
                result.layout,
                result.crop_applied,
                tuple(asset.data.shape),
                tuple(result.data.shape),
            )

            if args.dry_run:
                record = {
                    "source_path": str(path),
                    "output_path": "",
                    "metadata_path": "",
                    "crop_applied": result.crop_applied,
                    "layout": result.layout,
                    "layout_reason": result.layout_reason,
                    "warnings": "; ".join(result.warnings),
                }
            else:
                record = writer.write(asset, result)
            records.append(record)

        except NotImplementedError as exc:
            failures += 1
            message = f"Unsupported future/raw file {path}: {exc}"
            if args.fail_on_unsupported:
                LOGGER.error(message)
                raise
            LOGGER.warning(message)
        except Exception as exc:
            failures += 1
            LOGGER.error("Failed processing %s: %s", path, exc)
            if args.fail_on_unsupported:
                raise

    if not args.dry_run:
        manifest_path = write_manifest(args.output, records)
        LOGGER.info("Wrote manifest: %s", manifest_path)

    if failures:
        LOGGER.warning("%d file(s) were skipped or failed", failures)
    return 1 if failures and args.fail_on_unsupported else 0


if __name__ == "__main__":
    raise SystemExit(main())
