"""F-actin motion-index tracking for processed ROI videos and image sequences."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np

from actintrack_app.export_naming import motion_index_output_paths
from actintrack_app.project_manager import get_processed_batch_dir
from actintrack_app.utils import (
    F_ACTIN_MOTION_INDEX_SUMMARY_CSV,
    IMAGE_EXTENSIONS,
    METADATA_DIR,
    VIDEO_EXTENSIONS,
)
from actintrack_app.video_processing import MediaLoadError, get_video_frame_count

TRACK_PALETTE = [
    (80, 220, 120),
    (120, 180, 255),
    (255, 160, 80),
    (220, 120, 255),
    (255, 120, 120),
    (120, 255, 255),
    (180, 255, 120),
    (255, 220, 120),
    (120, 120, 255),
    (255, 120, 220),
]

MOTION_INDEX_SUMMARY_COLUMNS = [
    "sample_id",
    "group",
    "batch_name",
    "final_export_name",
    "source_path",
    "analysis_timestamp_utc",
    "absolute_velocity_index_um_per_s",
    "general_movement_index_um_per_s",
    "downward_velocity_index_um_per_s",
    "time_weighted_mean_speed_um_per_s",
    "signed_vertical_velocity_um_per_s",
    "downward_velocity_contribution_um_per_s",
    "num_tracks_started",
    "num_tracks_with_valid_steps",
    "total_valid_steps",
    "mean_track_length_frames",
    "frame_count",
    "trajectory_csv",
    "summary_json",
    "track_preview",
]

DEFAULT_MICRONS_PER_PIXEL = 0.2650
DEFAULT_SECONDS_PER_FRAME = 30.0000
TRACKING_METHOD_BRIGHTEST_LOCAL = "brightest_local"
TRACKING_METHOD_TEMPLATE = "template"
TRACKING_METHODS = {TRACKING_METHOD_BRIGHTEST_LOCAL, TRACKING_METHOD_TEMPLATE}


@dataclass(frozen=True)
class MotionIndexParams:
    """Parameters for bright-point motion-index analysis."""

    num_starting_points: int = 10
    min_point_spacing_px: int = 20
    search_radius_px: int = 8
    template_patch_size_px: int = 11
    min_template_confidence: float = 0.55
    lookahead_frames: int = 0
    microns_per_pixel: float = DEFAULT_MICRONS_PER_PIXEL
    seconds_per_frame: float = DEFAULT_SECONDS_PER_FRAME
    downward_direction: str = "increasing_y"
    tracking_method: str = TRACKING_METHOD_BRIGHTEST_LOCAL

    def __post_init__(self) -> None:
        if self.num_starting_points < 1:
            raise ValueError("num_starting_points must be at least 1.")
        if self.min_point_spacing_px < 1:
            raise ValueError("min_point_spacing_px must be at least 1.")
        if self.search_radius_px < 1:
            raise ValueError("search_radius_px must be at least 1.")
        patch = int(self.template_patch_size_px)
        if patch < 3 or patch % 2 == 0:
            raise ValueError("template_patch_size_px must be an odd integer >= 3.")
        if not 0.0 <= self.min_template_confidence <= 1.0:
            raise ValueError("min_template_confidence must be between 0 and 1.")
        if self.lookahead_frames < 0:
            raise ValueError("lookahead_frames must be >= 0.")
        if self.microns_per_pixel <= 0:
            raise ValueError("microns_per_pixel must be positive.")
        if self.seconds_per_frame <= 0:
            raise ValueError("seconds_per_frame must be positive.")
        if self.downward_direction != "increasing_y":
            raise ValueError("Only downward_direction='increasing_y' is supported.")
        if self.tracking_method not in TRACKING_METHODS:
            supported = ", ".join(sorted(TRACKING_METHODS))
            raise ValueError(f"tracking_method must be one of: {supported}.")


@dataclass
class TrackPoint:
    track_id: int
    frame_index: int
    x: float
    y: float
    confidence: float
    recovered_with_lookahead: bool = False


@dataclass
class PointTrack:
    track_id: int
    start_x: float
    start_y: float
    points: list[TrackPoint] = field(default_factory=list)
    active: bool = True
    end_reason: str = ""

    def last_point(self) -> TrackPoint:
        return self.points[-1]


@dataclass(frozen=True)
class VelocitySummary:
    """Explicit aggregate velocity definitions across all valid track steps."""

    mean_step_speed_um_per_s: float
    conditional_positive_downward_speed_um_per_s: float
    time_weighted_mean_speed_um_per_s: float
    signed_vertical_velocity_um_per_s: float
    downward_velocity_contribution_um_per_s: float
    total_tracked_time_s: float
    valid_step_count: int


@dataclass(frozen=True)
class ProcessedInputOption:
    """One discoverable processed ROI input for motion-index analysis."""

    label: str
    path: Path
    input_kind: str  # "video" | "image_sequence"
    frame_paths: tuple[Path, ...] = ()


@dataclass
class MotionIndexResult:
    source_path: str
    output_dir: str
    frame_count: int
    frame_width: int
    frame_height: int
    params: MotionIndexParams
    tracks: list[PointTrack]
    trajectory_csv: str
    summary_json: str
    start_points_preview: str
    tracks_overlay_preview: str
    track_preview_video: str
    downward_velocity_index_um_per_s: float
    general_movement_index_um_per_s: float
    track_summaries: list[dict[str, Any]]
    track_preview_webm: str = ""
    track_preview_mp4_codec: str = ""
    track_preview_webm_codec: str = ""
    time_weighted_mean_speed_um_per_s: float = 0.0
    signed_vertical_velocity_um_per_s: float = 0.0
    downward_velocity_contribution_um_per_s: float = 0.0
    final_export_name: str = ""
    sample_id: str = ""
    num_tracks_with_valid_steps: int = 0
    total_valid_steps: int = 0
    mean_track_length_frames: float = 0.0
    track_preview_error: str = ""

    def summary_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "output_dir": self.output_dir,
            "final_export_name": self.final_export_name,
            "sample_id": self.sample_id,
            "frame_count": self.frame_count,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "analysis_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "parameters": asdict(self.params),
            "primary_velocity_metric": "absolute_velocity_index_um_per_s",
            "recommended_scalar_speed_metric": "time_weighted_mean_speed_um_per_s",
            "primary_velocity_index_um_per_s": self.general_movement_index_um_per_s,
            "absolute_velocity_index_um_per_s": self.general_movement_index_um_per_s,
            "downward_velocity_index_um_per_s": self.downward_velocity_index_um_per_s,
            "downward_velocity_index_definition": (
                "mean(dy/dt | dy > 0); increasing image y is downward"
            ),
            "time_weighted_mean_speed_um_per_s": self.time_weighted_mean_speed_um_per_s,
            "signed_vertical_velocity_um_per_s": self.signed_vertical_velocity_um_per_s,
            "downward_velocity_contribution_um_per_s": (
                self.downward_velocity_contribution_um_per_s
            ),
            "general_movement_index_um_per_s": self.general_movement_index_um_per_s,
            "num_tracks_started": len(self.tracks),
            "num_tracks_with_valid_steps": self.num_tracks_with_valid_steps,
            "total_valid_steps": self.total_valid_steps,
            "mean_track_length_frames": self.mean_track_length_frames,
            "num_tracks_completed_full_sequence": sum(
                1
                for t in self.tracks
                if t.points and t.points[-1].frame_index == self.frame_count - 1
            ),
            "track_summaries": self.track_summaries,
            "track_preview_error": self.track_preview_error,
            "outputs": {
                "trajectory_csv": self.trajectory_csv,
                "summary_json": self.summary_json,
                "starting_points_png": self.start_points_preview,
                "track_overlay_png": self.tracks_overlay_preview,
                "track_preview_mp4": self.track_preview_video,
                "track_preview_webm": self.track_preview_webm,
                "track_preview_mp4_codec": self.track_preview_mp4_codec,
                "track_preview_webm_codec": self.track_preview_webm_codec,
            },
        }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _odd_size(value: int) -> int:
    size = max(3, int(value))
    return size if size % 2 == 1 else size + 1


def frame_to_signal(frame: np.ndarray) -> np.ndarray:
    """Grayscale actin-dominant signal used for peak detection and matching."""
    if frame.ndim == 2:
        return frame.astype(np.float32)
    b = frame[..., 0].astype(np.float32)
    g = frame[..., 1].astype(np.float32)
    r = frame[..., 2].astype(np.float32)
    gray = (0.114 * b) + (0.587 * g) + (0.299 * r)
    cyan_actin = np.maximum(b, g) - (0.25 * r)
    cyan_actin = np.clip(cyan_actin, 0.0, None)
    if float(np.percentile(cyan_actin, 99) - np.percentile(cyan_actin, 5)) < 5.0:
        return gray
    return cyan_actin


def _is_image_sequence_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    images = [
        p
        for p in sorted(path.iterdir())
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    ]
    return len(images) >= 2


def _sorted_image_paths(directory: Path) -> list[Path]:
    images = [
        p
        for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    ]
    return sorted(images, key=lambda p: p.name.lower())


def _sequence_paths_for_export(batch_dir: Path, final_export_name: str) -> list[Path]:
    """Return sorted processed image-sequence frames for one export prefix."""
    pattern = f"{final_export_name}--*.png"
    paths = sorted(batch_dir.glob(pattern), key=lambda p: p.name.lower())
    if len(paths) >= 2:
        return paths
    jpg_paths = sorted(
        batch_dir.glob(f"{final_export_name}--*.jpg"),
        key=lambda p: p.name.lower(),
    )
    if len(jpg_paths) >= 2:
        return jpg_paths
    return []


def discover_processed_inputs(
    root: Path,
    sample_row: dict[str, Any],
) -> list[ProcessedInputOption]:
    """
    Find processed/cropped ROI inputs for one sample.

    Returns zero or more candidates (video and/or image sequence).
    """
    root = Path(root).resolve()
    group = str(sample_row.get("group", "")).strip()
    batch_name = str(sample_row.get("batch_name", "")).strip()
    final_name = str(sample_row.get("final_export_name", "")).strip()
    if not group or not batch_name or not final_name:
        return []

    batch_dir = get_processed_batch_dir(root, group, batch_name)
    if not batch_dir.is_dir():
        return []

    options: list[ProcessedInputOption] = []
    for ext in (".mp4", ".avi"):
        video_path = batch_dir / f"{final_name}{ext}"
        if video_path.is_file():
            options.append(
                ProcessedInputOption(
                    label=f"Processed data file ({video_path.name})",
                    path=video_path,
                    input_kind="video",
                )
            )
            break

    seq_paths = _sequence_paths_for_export(batch_dir, final_name)
    if len(seq_paths) >= 2:
        options.append(
            ProcessedInputOption(
                label=(
                    f"Postponed image sequence ({len(seq_paths)} frames, "
                    f"{seq_paths[0].name} …)"
                ),
                path=seq_paths[0],
                input_kind="image_sequence",
                frame_paths=tuple(seq_paths),
            )
        )

    return options


def load_frames_from_paths(frame_paths: Sequence[Path]) -> tuple[list[np.ndarray], dict[str, Any]]:
    """Load an explicit ordered list of image frames."""
    if len(frame_paths) < 2:
        raise MediaLoadError(
            "Postponed image-sequence format is not supported in the current workflow."
        )
    frames = [cv2.imread(str(p), cv2.IMREAD_COLOR) for p in frame_paths]
    frames = [f for f in frames if f is not None]
    if len(frames) < 2:
        raise MediaLoadError(
            "Postponed image-sequence format is not supported in the current workflow."
        )
    return frames, {
        "source_path": str(frame_paths[0].parent),
        "loader": "image_sequence",
        "frame_paths": [str(p) for p in frame_paths],
    }


def load_frame_sequence(source: str | Path) -> tuple[list[np.ndarray], dict[str, Any]]:
    """
    Load a processed ROI video or image sequence.

    Accepts:
    - video files (.mp4, .avi)
    - directories containing two or more image frames
    - multi-frame TIFF stacks (when tifffile is available)
    """
    path = Path(source).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Input path does not exist: {path}")

    meta: dict[str, Any] = {"source_path": str(path), "loader": ""}

    if path.is_dir():
        frame_paths = _sorted_image_paths(path)
        if len(frame_paths) < 2:
            raise MediaLoadError(
                "Postponed image-sequence format is not supported in the current workflow."
            )
        frames = [cv2.imread(str(p), cv2.IMREAD_COLOR) for p in frame_paths]
        frames = [f for f in frames if f is not None]
        if len(frames) < 2:
            raise MediaLoadError(f"Need at least 2 readable frames in: {path}")
        meta["loader"] = "image_sequence"
        meta["frame_paths"] = [str(p) for p in frame_paths]
        return frames, meta

    ext = path.suffix.lower()
    if ext in VIDEO_EXTENSIONS:
        count = get_video_frame_count(path)
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            cap.release()
            raise MediaLoadError(f"Cannot open data file: {path}")
        frames: list[np.ndarray] = []
        try:
            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                frames.append(frame)
        finally:
            cap.release()
        if len(frames) < 2:
            raise MediaLoadError(f"Data file must contain at least 2 frames: {path}")
        meta["loader"] = "video"
        meta["reported_frame_count"] = count
        return frames, meta

    if ext in {".tif", ".tiff"}:
        try:
            import tifffile

            with tifffile.TiffFile(str(path)) as tif:
                arrays = [page.asarray() for page in tif.pages]
        except ImportError as exc:
            raise MediaLoadError(
                "Multi-frame TIFF loading requires tifffile. "
                "Install with: pip install tifffile"
            ) from exc

        frames = []
        for arr in arrays:
            if arr.ndim == 2:
                frames.append(cv2.cvtColor(arr.astype(np.uint8), cv2.COLOR_GRAY2BGR))
            elif arr.ndim == 3 and arr.shape[2] >= 3:
                frames.append(cv2.cvtColor(arr.astype(np.uint8), cv2.COLOR_RGB2BGR))
            else:
                raise MediaLoadError(f"Unsupported TIFF page shape: {arr.shape}")
        if len(frames) < 2:
            raise MediaLoadError(f"TIFF stack must contain at least 2 frames: {path}")
        meta["loader"] = "tiff_stack"
        return frames, meta

    if ext in IMAGE_EXTENSIONS:
        frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if frame is None:
            raise MediaLoadError(f"Cannot open image: {path}")
        meta["loader"] = "single_image"
        raise MediaLoadError(
            "Single image provided; motion-index analysis needs AVI/MP4 data "
            "with at least 2 frames."
        )

    raise MediaLoadError(f"Unsupported motion-index input: {path}")


def _local_maxima_mask(signal: np.ndarray, patch_size: int) -> np.ndarray:
    kernel = np.ones((patch_size, patch_size), dtype=np.uint8)
    dilated = cv2.dilate(signal, kernel)
    return signal >= (dilated - 1e-6)


def _signal_confidence(signal: np.ndarray, peak_value: float) -> float:
    low = float(np.percentile(signal, 5))
    high = float(np.percentile(signal, 99.5))
    denom = max(high - low, 1e-6)
    return float(np.clip((float(peak_value) - low) / denom, 0.0, 1.0))


def _bright_region_centroid(
    signal: np.ndarray,
    peak_x: float,
    peak_y: float,
    *,
    radius_px: int,
) -> tuple[float, float]:
    """Return a weighted centroid for the bright connected region around a peak."""
    h, w = signal.shape[:2]
    cx = int(round(peak_x))
    cy = int(round(peak_y))
    radius = max(1, int(radius_px))
    x0 = max(0, cx - radius)
    y0 = max(0, cy - radius)
    x1 = min(w, cx + radius + 1)
    y1 = min(h, cy + radius + 1)
    region = signal[y0:y1, x0:x1]
    if region.size == 0:
        return float(peak_x), float(peak_y)

    local_x = cx - x0
    local_y = cy - y0
    peak_value = float(region[local_y, local_x])
    floor = float(np.percentile(region, 20))
    threshold = floor + (0.65 * max(0.0, peak_value - floor))
    bright = (region >= threshold).astype(np.uint8)
    if not np.any(bright):
        return float(peak_x), float(peak_y)

    labels_count, labels = cv2.connectedComponents(bright, connectivity=8)
    if labels_count <= 1:
        return float(peak_x), float(peak_y)
    peak_label = int(labels[local_y, local_x])
    if peak_label <= 0:
        return float(peak_x), float(peak_y)

    mask = labels == peak_label
    ys, xs = np.where(mask)
    if ys.size == 0:
        return float(peak_x), float(peak_y)

    weights = np.clip(region[ys, xs] - floor, 0.0, None).astype(np.float64)
    if float(np.sum(weights)) <= 1e-9:
        return float(x0 + np.mean(xs)), float(y0 + np.mean(ys))
    return (
        float(np.sum((x0 + xs) * weights) / np.sum(weights)),
        float(np.sum((y0 + ys) * weights) / np.sum(weights)),
    )


def _too_close_to_blocked(
    x: float,
    y: float,
    blocked_points: Sequence[tuple[float, float]],
    min_distance_px: float,
) -> bool:
    if not blocked_points or min_distance_px <= 0:
        return False
    min_dist_sq = float(min_distance_px) * float(min_distance_px)
    for bx, by in blocked_points:
        dx = float(x) - float(bx)
        dy = float(y) - float(by)
        if (dx * dx) + (dy * dy) < min_dist_sq:
            return True
    return False


def _starting_point_valid_mask(signal: np.ndarray) -> np.ndarray:
    """
    Mask pixels where starting points are allowed.

    Large dark voids (nucleus / H2B) and their immediate perinuclear bright ring
    are excluded so seed points land on actin cables instead of circling the nucleus.
    """
    h, w = signal.shape[:2]
    valid = np.ones((h, w), dtype=bool)
    if h < 8 or w < 8:
        return valid

    low = float(np.percentile(signal, 12))
    dark = (signal <= low).astype(np.uint8)
    if not np.any(dark):
        return valid

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, kernel)
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    min_void_area = max(64, int(0.004 * h * w))
    excluded = np.zeros((h, w), dtype=np.uint8)
    for label in range(1, num_labels):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < min_void_area:
            continue
        component = labels == label
        touches_border = (
            np.any(component[0, :])
            or np.any(component[-1, :])
            or np.any(component[:, 0])
            or np.any(component[:, -1])
        )
        if touches_border:
            continue
        radius = max(4.0, (area / 3.14159265) ** 0.5)
        margin = int(max(6, min(35, radius * 0.45)))
        component_u8 = component.astype(np.uint8)
        dilate_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (2 * margin + 1, 2 * margin + 1),
        )
        excluded = np.maximum(excluded, cv2.dilate(component_u8, dilate_kernel))
    valid &= excluded == 0
    return valid


def select_starting_points(
    first_frame: np.ndarray,
    params: MotionIndexParams,
) -> list[tuple[float, float]]:
    """
    Pick bright local maxima from the first frame with minimum spacing.

    Returns (x, y) coordinates in image pixels.
    """
    signal = frame_to_signal(first_frame)
    h, w = signal.shape[:2]
    patch = _odd_size(max(3, params.template_patch_size_px))
    half = patch // 2
    valid_mask = _starting_point_valid_mask(signal)

    mask = _local_maxima_mask(signal, patch_size=5)
    ys, xs = np.where(mask)
    if ys.size == 0:
        raise ValueError("No local maxima found in the first frame.")

    scores = signal[ys, xs]
    order = np.argsort(scores)[::-1]

    selected: list[tuple[float, float]] = []
    min_dist = float(params.min_point_spacing_px)
    min_dist_sq = min_dist * min_dist

    for idx in order:
        x = float(xs[idx])
        y = float(ys[idx])
        x, y = _bright_region_centroid(
            signal,
            x,
            y,
            radius_px=max(2, half),
        )
        cx_i = int(round(x))
        cy_i = int(round(y))
        if cx_i < 0 or cy_i < 0 or cx_i >= w or cy_i >= h:
            continue
        if not valid_mask[cy_i, cx_i]:
            continue
        if x < half or y < half or x >= w - half or y >= h - half:
            continue
        too_close = False
        for sx, sy in selected:
            dx = x - sx
            dy = y - sy
            if (dx * dx) + (dy * dy) < min_dist_sq:
                too_close = True
                break
        if too_close:
            continue
        selected.append((x, y))
        if len(selected) >= params.num_starting_points:
            break

    if not selected:
        raise ValueError("No valid starting points after spacing and border checks.")
    return selected


def _extract_patch(signal: np.ndarray, x: float, y: float, patch_size: int) -> np.ndarray:
    half = patch_size // 2
    cx = int(round(x))
    cy = int(round(y))
    y0 = cy - half
    y1 = cy + half + 1
    x0 = cx - half
    x1 = cx + half + 1
    patch = signal[y0:y1, x0:x1]
    if patch.shape != (patch_size, patch_size):
        raise ValueError("Patch extraction failed near image border.")
    return patch.astype(np.float32)


def _match_template_in_window(
    frame_signal: np.ndarray,
    template: np.ndarray,
    center_x: float,
    center_y: float,
    search_radius_px: int,
    *,
    blocked_points: Sequence[tuple[float, float]] = (),
    blocked_radius_px: float = 0.0,
) -> tuple[float, float, float]:
    h, w = frame_signal.shape[:2]
    patch_h, patch_w = template.shape[:2]
    half_y = patch_h // 2
    half_x = patch_w // 2

    cx = int(round(center_x))
    cy = int(round(center_y))
    radius = int(search_radius_px)

    x0 = max(0, cx - radius - half_x)
    y0 = max(0, cy - radius - half_y)
    x1 = min(w, cx + radius + half_x + 1)
    y1 = min(h, cy + radius + half_y + 1)

    search_region = frame_signal[y0:y1, x0:x1]
    if search_region.shape[0] < patch_h or search_region.shape[1] < patch_w:
        return center_x, center_y, -1.0

    result = cv2.matchTemplate(search_region, template, cv2.TM_CCOEFF_NORMED)
    order = np.argsort(result.ravel())[::-1]
    for flat_idx in order:
        y_loc, x_loc = np.unravel_index(int(flat_idx), result.shape)
        match_x = float(x0 + x_loc + half_x)
        match_y = float(y0 + y_loc + half_y)
        refined_x, refined_y = _bright_region_centroid(
            frame_signal,
            match_x,
            match_y,
            radius_px=max(2, min(half_x, half_y)),
        )
        if _too_close_to_blocked(
            refined_x,
            refined_y,
            blocked_points,
            blocked_radius_px,
        ):
            continue
        return refined_x, refined_y, float(result[y_loc, x_loc])
    return center_x, center_y, -1.0


def _brightest_point_in_window(
    frame_signal: np.ndarray,
    center_x: float,
    center_y: float,
    search_radius_px: int,
    *,
    centroid_radius_px: int,
    blocked_points: Sequence[tuple[float, float]] = (),
    blocked_radius_px: float = 0.0,
) -> tuple[float, float, float]:
    h, w = frame_signal.shape[:2]
    cx = int(round(center_x))
    cy = int(round(center_y))
    radius = int(search_radius_px)
    x0 = max(0, cx - radius)
    y0 = max(0, cy - radius)
    x1 = min(w, cx + radius + 1)
    y1 = min(h, cy + radius + 1)
    region = frame_signal[y0:y1, x0:x1]
    if region.size == 0:
        return center_x, center_y, -1.0

    mask = _local_maxima_mask(region, patch_size=3)
    ys, xs = np.where(mask)
    if ys.size == 0:
        flat = int(np.argmax(region))
        y_max, x_max = np.unravel_index(flat, region.shape)
        ys = np.array([y_max])
        xs = np.array([x_max])

    scores = region[ys, xs]
    order = np.argsort(scores)[::-1]
    max_radius_sq = float(radius + 1) * float(radius + 1)
    for idx in order:
        raw_x = float(x0 + xs[idx])
        raw_y = float(y0 + ys[idx])
        x, y = _bright_region_centroid(
            frame_signal,
            raw_x,
            raw_y,
            radius_px=centroid_radius_px,
        )
        dx = x - float(center_x)
        dy = y - float(center_y)
        if (dx * dx) + (dy * dy) > max_radius_sq:
            continue
        if _too_close_to_blocked(x, y, blocked_points, blocked_radius_px):
            continue
        confidence = _signal_confidence(frame_signal, float(scores[idx]))
        return x, y, confidence
    return center_x, center_y, -1.0


def _try_match_step(
    signals: Sequence[np.ndarray],
    prev_point: TrackPoint,
    target_frame_idx: int,
    params: MotionIndexParams,
    *,
    search_radius_px: int,
    blocked_points: Sequence[tuple[float, float]] = (),
    blocked_radius_px: float = 0.0,
) -> tuple[float, float, float]:
    patch_size = _odd_size(params.template_patch_size_px)
    if params.tracking_method == TRACKING_METHOD_BRIGHTEST_LOCAL:
        return _brightest_point_in_window(
            signals[target_frame_idx],
            prev_point.x,
            prev_point.y,
            search_radius_px,
            centroid_radius_px=max(2, patch_size // 2),
            blocked_points=blocked_points,
            blocked_radius_px=blocked_radius_px,
        )

    try:
        template = _extract_patch(
            signals[prev_point.frame_index],
            prev_point.x,
            prev_point.y,
            patch_size,
        )
    except ValueError:
        return prev_point.x, prev_point.y, -1.0
    return _match_template_in_window(
        signals[target_frame_idx],
        template,
        prev_point.x,
        prev_point.y,
        search_radius_px,
        blocked_points=blocked_points,
        blocked_radius_px=blocked_radius_px,
    )


def track_points(
    frames: Sequence[np.ndarray],
    starting_points: Sequence[tuple[float, float]],
    params: MotionIndexParams,
) -> list[PointTrack]:
    """Track starting bright points across frames using the configured local matcher."""
    if len(frames) < 2:
        raise ValueError("At least two frames are required for tracking.")

    signals = [frame_to_signal(frame) for frame in frames]
    claims_by_frame: dict[int, list[tuple[float, float]]] = {}
    blocked_radius = max(2.0, min(10.0, float(params.min_point_spacing_px) * 0.5))

    tracks: list[PointTrack] = []
    for track_id, (sx, sy) in enumerate(starting_points):
        tracks.append(
            PointTrack(
                track_id=track_id,
                start_x=sx,
                start_y=sy,
                points=[
                    TrackPoint(
                        track_id=track_id,
                        frame_index=0,
                        x=sx,
                        y=sy,
                        confidence=1.0,
                    )
                ],
            )
        )

    for next_frame in range(1, len(frames)):
        frame_claims = claims_by_frame.setdefault(next_frame, [])
        for track in tracks:
            if not track.active:
                continue
            prev_point = track.last_point()
            if prev_point.frame_index >= next_frame:
                continue

            if prev_point.frame_index < next_frame - 1:
                frame_gap = next_frame - prev_point.frame_index
                if params.lookahead_frames > 0 and frame_gap <= params.lookahead_frames + 1:
                    match_x, match_y, confidence = _try_match_step(
                        signals,
                        prev_point,
                        next_frame,
                        params,
                        search_radius_px=params.search_radius_px * frame_gap,
                        blocked_points=frame_claims,
                        blocked_radius_px=blocked_radius,
                    )
                    if confidence >= params.min_template_confidence:
                        track.points.append(
                            TrackPoint(
                                track_id=track.track_id,
                                frame_index=next_frame,
                                x=match_x,
                                y=match_y,
                                confidence=confidence,
                                recovered_with_lookahead=True,
                            )
                        )
                        frame_claims.append((match_x, match_y))
                        continue
                track.active = False
                track.end_reason = f"lost_before_frame_{next_frame}"
                continue

            match_x, match_y, confidence = _try_match_step(
                signals,
                prev_point,
                next_frame,
                params,
                search_radius_px=params.search_radius_px,
                blocked_points=frame_claims,
                blocked_radius_px=blocked_radius,
            )

            if confidence >= params.min_template_confidence:
                track.points.append(
                    TrackPoint(
                        track_id=track.track_id,
                        frame_index=next_frame,
                        x=match_x,
                        y=match_y,
                        confidence=confidence,
                    )
                )
                frame_claims.append((match_x, match_y))
                continue

            track.active = False
            track.end_reason = f"lost_at_frame_{next_frame}"

    for track in tracks:
        if track.active:
            track.active = False
            track.end_reason = "reached_last_frame"

    return tracks


def _iter_consecutive_points(track: PointTrack) -> list[tuple[TrackPoint, TrackPoint]]:
    pairs: list[tuple[TrackPoint, TrackPoint]] = []
    for i in range(1, len(track.points)):
        pairs.append((track.points[i - 1], track.points[i]))
    return pairs


def _point_step_metrics(
    prev_pt: TrackPoint | None,
    point: TrackPoint,
    params: MotionIndexParams,
    previous_motion_angle_deg: float | None = None,
) -> dict[str, Any]:
    if prev_pt is None:
        return {
            "prev_frame_index": "",
            "frame_gap": "",
            "dx_px": "",
            "dy_px": "",
            "displacement_px": "",
            "dt_s": "",
            "dx_um": "",
            "dy_um": "",
            "displacement_um": "",
            "absolute_velocity_um_per_s": "",
            "downward_velocity_um_per_s": "",
            "motion_angle_deg": "",
            "turning_angle_deg": "",
        }

    frame_gap = max(1, point.frame_index - prev_pt.frame_index)
    dt_s = float(params.seconds_per_frame) * frame_gap
    dx_px = point.x - prev_pt.x
    dy_px = point.y - prev_pt.y
    displacement_px = float(np.hypot(dx_px, dy_px))
    dx_um = dx_px * float(params.microns_per_pixel)
    dy_um = dy_px * float(params.microns_per_pixel)
    displacement_um = float(np.hypot(dx_um, dy_um))
    absolute_velocity = displacement_um / dt_s
    downward_velocity = (dy_um / dt_s) if dy_px > 0 else 0.0
    motion_angle_deg = float(np.degrees(np.arctan2(dy_px, dx_px)))
    turning_angle_deg: float | str = ""
    if previous_motion_angle_deg is not None:
        turning_angle_deg = (
            (motion_angle_deg - previous_motion_angle_deg + 180.0) % 360.0
        ) - 180.0
    return {
        "prev_frame_index": prev_pt.frame_index,
        "frame_gap": frame_gap,
        "dx_px": round(dx_px, 6),
        "dy_px": round(dy_px, 6),
        "displacement_px": round(displacement_px, 6),
        "dt_s": round(dt_s, 6),
        "dx_um": round(dx_um, 6),
        "dy_um": round(dy_um, 6),
        "displacement_um": round(displacement_um, 6),
        "absolute_velocity_um_per_s": round(absolute_velocity, 6),
        "downward_velocity_um_per_s": round(downward_velocity, 6),
        "motion_angle_deg": round(motion_angle_deg, 6),
        "turning_angle_deg": (
            round(turning_angle_deg, 6)
            if isinstance(turning_angle_deg, float)
            else turning_angle_deg
        ),
    }


def compute_motion_indices(
    tracks: Sequence[PointTrack],
    params: MotionIndexParams,
) -> tuple[float, float, list[dict[str, Any]]]:
    """
    Compute aggregate motion indices and per-track summaries.

    Downward Velocity Index:
        Mean positive downward speed (dy > 0, increasing y) in microns/s.

    General Movement / Absolute Velocity Index:
        Mean Euclidean displacement speed in microns/s across all valid steps.
    """
    mpp = float(params.microns_per_pixel)
    dt = float(params.seconds_per_frame)

    downward_speeds: list[float] = []
    general_speeds: list[float] = []
    track_summaries: list[dict[str, Any]] = []

    for track in tracks:
        track_downward: list[float] = []
        track_general: list[float] = []
        total_downward_um = 0.0
        total_path_um = 0.0
        total_time_s = 0.0

        for prev_pt, next_pt in _iter_consecutive_points(track):
            frame_gap = max(1, next_pt.frame_index - prev_pt.frame_index)
            step_dt = dt * frame_gap
            dx_px = next_pt.x - prev_pt.x
            dy_px = next_pt.y - prev_pt.y
            dx_um = dx_px * mpp
            dy_um = dy_px * mpp
            displacement_um = float(np.hypot(dx_um, dy_um))
            speed_general = displacement_um / step_dt

            track_general.append(speed_general)
            general_speeds.append(speed_general)
            total_path_um += displacement_um
            total_time_s += step_dt

            if dy_px > 0:
                speed_down = dy_um / step_dt
                track_downward.append(speed_down)
                downward_speeds.append(speed_down)
                total_downward_um += dy_um

        track_summaries.append(
            {
                "track_id": track.track_id,
                "start_x_px": round(track.start_x, 3),
                "start_y_px": round(track.start_y, 3),
                "num_points": len(track.points),
                "last_frame_index": track.points[-1].frame_index if track.points else None,
                "active_to_end": track.active,
                "end_reason": track.end_reason,
                "downward_velocity_index_um_per_s": round(
                    float(np.mean(track_downward)) if track_downward else 0.0, 6
                ),
                "general_movement_index_um_per_s": round(
                    float(np.mean(track_general)) if track_general else 0.0, 6
                ),
                "total_downward_displacement_um": round(total_downward_um, 6),
                "total_path_length_um": round(total_path_um, 6),
                "tracked_time_s": round(total_time_s, 6),
            }
        )

    downward_index = float(np.mean(downward_speeds)) if downward_speeds else 0.0
    general_index = float(np.mean(general_speeds)) if general_speeds else 0.0
    return downward_index, general_index, track_summaries


def compute_velocity_summary(
    tracks: Sequence[PointTrack],
    params: MotionIndexParams,
) -> VelocitySummary:
    """
    Compute velocity aggregates with explicit denominators and direction semantics.

    The historical indices are step-weighted means. The additional metrics below
    are time-weighted, which is important when lookahead creates unequal frame gaps.
    Positive image y is defined as downward.
    """
    mpp = float(params.microns_per_pixel)
    seconds_per_frame = float(params.seconds_per_frame)
    step_speeds: list[float] = []
    positive_downward_step_speeds: list[float] = []
    total_path_um = 0.0
    total_vertical_um = 0.0
    total_downward_um = 0.0
    total_time_s = 0.0

    for track in tracks:
        for prev_pt, next_pt in _iter_consecutive_points(track):
            frame_gap = max(1, next_pt.frame_index - prev_pt.frame_index)
            step_time_s = seconds_per_frame * frame_gap
            dx_um = (next_pt.x - prev_pt.x) * mpp
            dy_um = (next_pt.y - prev_pt.y) * mpp
            displacement_um = float(np.hypot(dx_um, dy_um))

            step_speeds.append(displacement_um / step_time_s)
            if dy_um > 0:
                positive_downward_step_speeds.append(dy_um / step_time_s)
            total_path_um += displacement_um
            total_vertical_um += dy_um
            total_downward_um += max(dy_um, 0.0)
            total_time_s += step_time_s

    if total_time_s <= 0:
        return VelocitySummary(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0)

    return VelocitySummary(
        mean_step_speed_um_per_s=(
            float(np.mean(step_speeds)) if step_speeds else 0.0
        ),
        conditional_positive_downward_speed_um_per_s=(
            float(np.mean(positive_downward_step_speeds))
            if positive_downward_step_speeds
            else 0.0
        ),
        time_weighted_mean_speed_um_per_s=total_path_um / total_time_s,
        signed_vertical_velocity_um_per_s=total_vertical_um / total_time_s,
        downward_velocity_contribution_um_per_s=total_downward_um / total_time_s,
        total_tracked_time_s=total_time_s,
        valid_step_count=len(step_speeds),
    )


def compute_track_statistics(tracks: Sequence[PointTrack]) -> tuple[int, int, float]:
    """Return (tracks_with_valid_steps, total_valid_steps, mean_track_length_frames)."""
    valid_lengths: list[int] = []
    total_steps = 0
    for track in tracks:
        n = len(track.points)
        if n >= 2:
            valid_lengths.append(n)
            total_steps += n - 1
    mean_len = float(np.mean(valid_lengths)) if valid_lengths else 0.0
    return len(valid_lengths), total_steps, mean_len


def _default_output_dir(source: Path, final_export_name: str | None = None) -> Path:
    if final_export_name:
        return source.parent if source.is_file() else source
    if source.is_dir():
        return source
    return source.parent


def save_trajectory_csv(
    path: Path,
    tracks: Sequence[PointTrack],
    params: MotionIndexParams,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "track_id",
                "frame_index",
                "prev_frame_index",
                "frame_gap",
                "x_px",
                "y_px",
                "dx_px",
                "dy_px",
                "displacement_px",
                "dt_s",
                "dx_um",
                "dy_um",
                "displacement_um",
                "absolute_velocity_um_per_s",
                "downward_velocity_um_per_s",
                "motion_angle_deg",
                "turning_angle_deg",
                "confidence",
                "recovered_with_lookahead",
            ],
        )
        writer.writeheader()
        for track in tracks:
            prev_point: TrackPoint | None = None
            previous_motion_angle_deg: float | None = None
            for point in track.points:
                row = {
                    "track_id": point.track_id,
                    "frame_index": point.frame_index,
                    "x_px": round(point.x, 3),
                    "y_px": round(point.y, 3),
                    "confidence": round(point.confidence, 4),
                    "recovered_with_lookahead": point.recovered_with_lookahead,
                }
                row.update(
                    _point_step_metrics(
                        prev_point,
                        point,
                        params,
                        previous_motion_angle_deg,
                    )
                )
                writer.writerow(row)
                motion_angle = row.get("motion_angle_deg", "")
                if motion_angle != "":
                    previous_motion_angle_deg = float(motion_angle)
                prev_point = point


def draw_start_points_preview(
    first_frame: np.ndarray,
    starting_points: Sequence[tuple[float, float]],
) -> np.ndarray:
    out = first_frame.copy()
    for idx, (x, y) in enumerate(starting_points):
        cx, cy = int(round(x)), int(round(y))
        cv2.circle(out, (cx, cy), 5, (0, 255, 255), 1, lineType=cv2.LINE_AA)
        cv2.circle(out, (cx, cy), 2, (0, 255, 255), -1, lineType=cv2.LINE_AA)
        cv2.putText(
            out,
            str(idx + 1),
            (cx + 6, cy - 6),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return out


def _track_visible_at_frame(track: PointTrack, frame_index: int) -> list[TrackPoint]:
    pts = [p for p in track.points if p.frame_index <= frame_index]
    if not pts:
        return []
    last = pts[-1]
    if not track.active and last.frame_index < frame_index:
        return []
    return pts


def render_track_preview_frame(
    frame: np.ndarray,
    tracks: Sequence[PointTrack],
    frame_index: int,
    *,
    trail_length: int = 6,
) -> np.ndarray:
    """Draw tracked points, short trails, and IDs on one cropped ROI frame."""
    out = frame.copy()
    for track in tracks:
        pts = _track_visible_at_frame(track, frame_index)
        if not pts:
            continue
        color = TRACK_PALETTE[track.track_id % len(TRACK_PALETTE)]
        draw_pts = pts[-max(1, trail_length) :]
        for i in range(1, len(draw_pts)):
            p0 = (int(round(draw_pts[i - 1].x)), int(round(draw_pts[i - 1].y)))
            p1 = (int(round(draw_pts[i].x)), int(round(draw_pts[i].y)))
            cv2.line(out, p0, p1, color, 1, lineType=cv2.LINE_AA)
        last = pts[-1]
        cx, cy = int(round(last.x)), int(round(last.y))
        cv2.circle(out, (cx, cy), 4, color, 1, lineType=cv2.LINE_AA)
        cv2.circle(out, (cx, cy), 2, color, -1, lineType=cv2.LINE_AA)
        cv2.putText(
            out,
            str(track.track_id + 1),
            (cx + 5, cy - 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            color,
            1,
            cv2.LINE_AA,
        )
    return out


def write_track_preview_video(
    path: Path,
    frames: Sequence[np.ndarray],
    tracks: Sequence[PointTrack],
    *,
    fps: float = 5.0,
) -> str:
    """Write an H.264 trajectory preview MP4 and return the codec tag used."""
    if not frames:
        raise ValueError("Cannot write track preview: no frames.")
    path.parent.mkdir(parents=True, exist_ok=True)
    h, w = frames[0].shape[:2]
    rendered = [
        render_track_preview_frame(frame, tracks, frame_index)
        for frame_index, frame in enumerate(frames)
    ]
    return _write_browser_video(path, rendered, fps=fps, codecs=("avc1", "H264"))


def write_track_preview_webm(
    path: Path,
    frames: Sequence[np.ndarray],
    tracks: Sequence[PointTrack],
    *,
    fps: float = 5.0,
) -> str:
    """Write a VP9/VP8 WebM trajectory preview and return the codec tag used."""
    if not frames:
        raise ValueError("Cannot write track preview: no frames.")
    rendered = [
        render_track_preview_frame(frame, tracks, frame_index)
        for frame_index, frame in enumerate(frames)
    ]
    return _write_browser_video(path, rendered, fps=fps, codecs=("VP90", "VP80"))


def _write_browser_video(
    path: Path,
    frames: Sequence[np.ndarray],
    *,
    fps: float,
    codecs: Sequence[str],
) -> str:
    """Write frames using the first available codec from a browser-safe list."""
    if not frames:
        raise ValueError("Cannot write track preview: no frames.")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    h, w = frames[0].shape[:2]
    errors: list[str] = []
    for codec in codecs:
        writer = cv2.VideoWriter(
            str(path),
            cv2.VideoWriter_fourcc(*codec),
            max(1.0, float(fps)),
            (w, h),
        )
        if not writer.isOpened():
            writer.release()
            errors.append(f"{codec}: unavailable")
            continue
        try:
            for frame in frames:
                writer.write(frame)
        finally:
            writer.release()
        if path.is_file() and path.stat().st_size > 0:
            return codec
        errors.append(f"{codec}: empty output")
    raise OSError(
        f"Could not encode browser-compatible preview {path.name}: "
        + "; ".join(errors)
    )


def transcode_preview_to_webm(
    source: str | Path,
    output: str | Path,
) -> dict[str, Any]:
    """Convert a legacy preview into browser-compatible VP9/VP8 WebM."""
    source_path = Path(source).resolve()
    output_path = Path(output).resolve()
    cap = cv2.VideoCapture(str(source_path))
    if not cap.isOpened():
        cap.release()
        raise OSError(f"Could not open legacy preview: {source_path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    if fps <= 0:
        fps = 5.0
    frames: list[np.ndarray] = []
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            frames.append(frame)
    finally:
        cap.release()
    if not frames:
        raise OSError(f"Legacy preview contains no readable frames: {source_path}")
    codec = _write_browser_video(
        output_path,
        frames,
        fps=fps,
        codecs=("VP90", "VP80"),
    )
    return {
        "source_path": str(source_path),
        "output_path": str(output_path),
        "codec": codec,
        "mime_type": "video/webm",
        "frame_count": len(frames),
        "fps": fps,
    }


def draw_tracks_overlay_preview(
    first_frame: np.ndarray,
    tracks: Sequence[PointTrack],
) -> np.ndarray:
    out = first_frame.copy()

    for track in tracks:
        color = TRACK_PALETTE[track.track_id % len(TRACK_PALETTE)]
        if not track.points:
            continue
        pts = [(int(round(p.x)), int(round(p.y))) for p in track.points]
        for i in range(1, len(pts)):
            cv2.line(out, pts[i - 1], pts[i], color, 1, lineType=cv2.LINE_AA)
        cv2.circle(out, pts[0], 4, color, 1, lineType=cv2.LINE_AA)
        cv2.circle(out, pts[-1], 3, color, -1, lineType=cv2.LINE_AA)
    return out


def update_workspace_motion_index_summary(
    root: Path,
    result: MotionIndexResult,
    *,
    group: str,
    batch_name: str,
) -> Path:
    """Append or update one row in metadata/f_actin_motion_index_summary.csv."""
    root = Path(root).resolve()
    summary_path = root / METADATA_DIR / F_ACTIN_MOTION_INDEX_SUMMARY_CSV
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    row = {
        "sample_id": result.sample_id,
        "group": group,
        "batch_name": batch_name,
        "final_export_name": result.final_export_name,
        "source_path": result.source_path,
        "analysis_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "absolute_velocity_index_um_per_s": round(
            result.general_movement_index_um_per_s, 6
        ),
        "general_movement_index_um_per_s": round(
            result.general_movement_index_um_per_s, 6
        ),
        "downward_velocity_index_um_per_s": round(
            result.downward_velocity_index_um_per_s, 6
        ),
        "time_weighted_mean_speed_um_per_s": round(
            result.time_weighted_mean_speed_um_per_s, 6
        ),
        "signed_vertical_velocity_um_per_s": round(
            result.signed_vertical_velocity_um_per_s, 6
        ),
        "downward_velocity_contribution_um_per_s": round(
            result.downward_velocity_contribution_um_per_s, 6
        ),
        "num_tracks_started": len(result.tracks),
        "num_tracks_with_valid_steps": result.num_tracks_with_valid_steps,
        "total_valid_steps": result.total_valid_steps,
        "mean_track_length_frames": round(result.mean_track_length_frames, 3),
        "frame_count": result.frame_count,
        "trajectory_csv": result.trajectory_csv,
        "summary_json": result.summary_json,
        "track_preview": result.track_preview_video,
    }

    existing_rows: list[dict[str, Any]] = []
    if summary_path.is_file():
        with summary_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for item in reader:
                existing_rows.append(item)

    key = (result.sample_id, result.final_export_name)
    updated = False
    for item in existing_rows:
        if (item.get("sample_id"), item.get("final_export_name")) == key:
            item.update({k: str(v) for k, v in row.items()})
            updated = True
            break
    if not updated:
        existing_rows.append({k: str(v) for k, v in row.items()})

    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MOTION_INDEX_SUMMARY_COLUMNS)
        writer.writeheader()
        for item in existing_rows:
            writer.writerow({col: item.get(col, "") for col in MOTION_INDEX_SUMMARY_COLUMNS})
    return summary_path


def save_motion_index_outputs(
    *,
    output_dir: Path,
    final_export_name: str,
    first_frame: np.ndarray,
    frames: Sequence[np.ndarray],
    starting_points: Sequence[tuple[float, float]],
    tracks: Sequence[PointTrack],
    result: MotionIndexResult,
    preview_fps: float = 5.0,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = motion_index_output_paths(output_dir, final_export_name)

    save_trajectory_csv(paths["trajectory_csv"], tracks, result.params)

    cv2.imwrite(
        str(paths["starting_points"]),
        draw_start_points_preview(first_frame, starting_points),
    )
    cv2.imwrite(
        str(paths["track_overlay"]),
        draw_tracks_overlay_preview(first_frame, tracks),
    )

    preview_errors: list[str] = []
    mp4_codec = ""
    webm_codec = ""
    try:
        mp4_codec = write_track_preview_video(
            paths["track_preview"],
            frames,
            tracks,
            fps=preview_fps,
        )
    except OSError as exc:
        preview_errors.append(str(exc))
    try:
        webm_codec = write_track_preview_webm(
            paths["track_preview_webm"],
            frames,
            tracks,
            fps=preview_fps,
        )
    except OSError as exc:
        preview_errors.append(str(exc))

    preview_error = "; ".join(preview_errors)
    result.track_preview_error = preview_error
    result.track_preview_mp4_codec = mp4_codec
    result.track_preview_webm_codec = webm_codec
    result.track_preview_webm = (
        str(paths["track_preview_webm"])
        if paths["track_preview_webm"].is_file()
        else ""
    )
    summary_payload = result.summary_dict()
    summary_payload["written_at_utc"] = _utc_now_iso()
    paths["summary_json"].write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")

    return {
        "trajectory_csv": str(paths["trajectory_csv"]),
        "summary_json": str(paths["summary_json"]),
        "start_points_preview": str(paths["starting_points"]),
        "tracks_overlay_preview": str(paths["track_overlay"]),
        "track_preview_video": str(paths["track_preview"]),
        "track_preview_webm": result.track_preview_webm,
        "track_preview_mp4_codec": mp4_codec,
        "track_preview_webm_codec": webm_codec,
        "track_preview_error": preview_error,
    }


def run_motion_index_analysis(
    source: str | Path,
    *,
    output_dir: str | Path | None = None,
    final_export_name: str | None = None,
    sample_id: str = "",
    params: MotionIndexParams | None = None,
    preview_fps: float = 5.0,
    frame_paths: Sequence[Path] | None = None,
) -> MotionIndexResult:
    """
    Run the full motion-index workflow on one processed ROI video or image sequence.
    """
    params = params or MotionIndexParams()
    source_path = Path(source).resolve()
    export_name = (final_export_name or source_path.stem).strip()
    out_dir = (
        Path(output_dir).resolve()
        if output_dir
        else _default_output_dir(source_path, export_name)
    )

    patch = _odd_size(params.template_patch_size_px)
    radius = int(params.search_radius_px)
    min_dim = patch + (2 * radius) + 2

    if frame_paths:
        frames, _loader_meta = load_frames_from_paths(frame_paths)
    else:
        frames, _loader_meta = load_frame_sequence(source_path)
    first_frame = frames[0]
    h, w = first_frame.shape[:2]
    h_crop, w_crop = h, w
    if min(h, w) < min_dim:
        raise ValueError(
            f"Cropped ROI ({w}x{h} px) is too small for patch size "
            f"{patch} and search radius {radius}."
        )

    starting_points = select_starting_points(first_frame, params)
    if not starting_points:
        raise ValueError("No bright starting points found in the first frame.")

    tracks = track_points(frames, starting_points, params)
    if not any(len(t.points) >= 2 for t in tracks):
        raise ValueError("No tracks survived with valid motion steps.")

    downward_index, general_index, track_summaries = compute_motion_indices(tracks, params)
    velocity_summary = compute_velocity_summary(tracks, params)
    valid_tracks, total_steps, mean_len = compute_track_statistics(tracks)

    result = MotionIndexResult(
        source_path=str(source_path),
        output_dir=str(out_dir),
        frame_count=len(frames),
        frame_width=w,
        frame_height=h,
        params=params,
        tracks=tracks,
        trajectory_csv="",
        summary_json="",
        start_points_preview="",
        tracks_overlay_preview="",
        track_preview_video="",
        downward_velocity_index_um_per_s=downward_index,
        general_movement_index_um_per_s=general_index,
        track_summaries=track_summaries,
        time_weighted_mean_speed_um_per_s=(
            velocity_summary.time_weighted_mean_speed_um_per_s
        ),
        signed_vertical_velocity_um_per_s=(
            velocity_summary.signed_vertical_velocity_um_per_s
        ),
        downward_velocity_contribution_um_per_s=(
            velocity_summary.downward_velocity_contribution_um_per_s
        ),
        final_export_name=export_name,
        sample_id=sample_id,
        num_tracks_with_valid_steps=valid_tracks,
        total_valid_steps=total_steps,
        mean_track_length_frames=mean_len,
    )

    outputs = save_motion_index_outputs(
        output_dir=out_dir,
        final_export_name=export_name,
        first_frame=first_frame,
        frames=frames,
        starting_points=starting_points,
        tracks=tracks,
        result=result,
        preview_fps=preview_fps,
    )

    result.trajectory_csv = outputs["trajectory_csv"]
    result.summary_json = outputs["summary_json"]
    result.start_points_preview = outputs["start_points_preview"]
    result.tracks_overlay_preview = outputs["tracks_overlay_preview"]
    result.track_preview_video = outputs["track_preview_video"]
    result.track_preview_webm = outputs.get("track_preview_webm", "")
    result.track_preview_mp4_codec = outputs.get("track_preview_mp4_codec", "")
    result.track_preview_webm_codec = outputs.get("track_preview_webm_codec", "")
    result.track_preview_error = outputs.get("track_preview_error", "")
    return result


def run_motion_index_test(
    source: str | Path,
    *,
    output_dir: str | Path | None = None,
    final_export_name: str | None = None,
    params: MotionIndexParams | None = None,
) -> dict[str, Any]:
    """
    Convenience wrapper for manual testing before GUI integration.

    Prints a short summary and returns the analysis payload.
    """
    result = run_motion_index_analysis(
        source,
        output_dir=output_dir,
        final_export_name=final_export_name,
        params=params,
    )
    print(f"Source: {result.source_path}")
    print(f"Frames: {result.frame_count} ({result.frame_width}x{result.frame_height})")
    print(f"Tracks started: {len(result.tracks)}")
    print(
        "Absolute Velocity Index: "
        f"{result.general_movement_index_um_per_s:.4f} um/s"
    )
    print(
        "Downward Velocity Index: "
        f"{result.downward_velocity_index_um_per_s:.4f} um/s"
    )
    print(
        "Time-weighted Mean Speed: "
        f"{result.time_weighted_mean_speed_um_per_s:.4f} um/s"
    )
    print(
        "Signed Vertical Velocity: "
        f"{result.signed_vertical_velocity_um_per_s:.4f} um/s"
    )
    print(
        "Downward Velocity Contribution: "
        f"{result.downward_velocity_contribution_um_per_s:.4f} um/s"
    )
    print(f"Trajectory CSV: {result.trajectory_csv}")
    print(f"Summary JSON: {result.summary_json}")
    print(f"Start points preview: {result.start_points_preview}")
    print(f"Tracks overlay preview: {result.tracks_overlay_preview}")
    print(f"Track preview video: {result.track_preview_video}")
    if result.track_preview_error:
        print(f"Track preview warning: {result.track_preview_error}")
    return result.summary_dict()
