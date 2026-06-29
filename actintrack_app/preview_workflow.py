"""In-app cropped ROI preview and draft motion-index analysis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from actintrack_app.motion_index import (
    MotionIndexParams,
    PointTrack,
    compute_motion_indices,
    compute_track_statistics,
    compute_velocity_summary,
    render_track_preview_frame,
    select_starting_points,
    track_points,
)
from actintrack_app.orientation import OrientationState, RectROI, apply_orientation, crop_rect_roi
from actintrack_app.utils import VIDEO_EXTENSIONS
from actintrack_app.video_processing import MediaLoadError, load_media_frame


@dataclass
class CroppedPreviewAnalysis:
    frames: list[np.ndarray]
    tracks: list[PointTrack]
    starting_points: list[tuple[float, float]]
    downward_velocity_index_um_per_s: float
    general_movement_index_um_per_s: float
    num_tracks_with_valid_steps: int
    total_valid_steps: int
    mean_track_length_frames: float
    time_weighted_mean_speed_um_per_s: float = 0.0
    signed_vertical_velocity_um_per_s: float = 0.0
    downward_velocity_contribution_um_per_s: float = 0.0
    tracking_warning: str = ""
    params: MotionIndexParams | None = None

    @property
    def num_tracks_started(self) -> int:
        return len(self.tracks)


def load_cropped_frames_from_video(
    video_path: Path,
    orientation: OrientationState,
    roi_oriented: RectROI,
) -> list[np.ndarray]:
    """Load all frames from a video, orient, and crop to the ROI."""
    path = Path(video_path)
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise MediaLoadError(
            "Only AVI and MP4 data files are supported in the current 2D workflow."
        )

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
            oriented = apply_orientation(frame, orientation)
            cropped = crop_rect_roi(oriented, roi_oriented)
            frames.append(cropped)
    finally:
        cap.release()

    if len(frames) < 2:
        raise MediaLoadError(
            "Data file must contain at least 2 readable frames for preview."
        )
    return frames


def analyze_cropped_preview(
    frames: list[np.ndarray],
    *,
    params: MotionIndexParams | None = None,
) -> CroppedPreviewAnalysis:
    """Run draft motion-index tracking on in-memory cropped frames."""
    params = params or MotionIndexParams()
    if len(frames) < 2:
        raise ValueError("Need at least 2 cropped frames for tracking preview.")

    warning = ""
    try:
        starting_points = select_starting_points(frames[0], params)
    except ValueError as exc:
        return CroppedPreviewAnalysis(
            frames=frames,
            tracks=[],
            starting_points=[],
            downward_velocity_index_um_per_s=0.0,
            general_movement_index_um_per_s=0.0,
            num_tracks_with_valid_steps=0,
            total_valid_steps=0,
            mean_track_length_frames=0.0,
            tracking_warning=str(exc),
            params=params,
        )

    if len(starting_points) < params.num_starting_points:
        warning = (
            f"Only {len(starting_points)} starting point(s) found "
            f"(requested {params.num_starting_points})."
        )

    try:
        tracks = track_points(frames, starting_points, params)
    except ValueError as exc:
        return CroppedPreviewAnalysis(
            frames=frames,
            tracks=[],
            starting_points=starting_points,
            downward_velocity_index_um_per_s=0.0,
            general_movement_index_um_per_s=0.0,
            num_tracks_with_valid_steps=0,
            total_valid_steps=0,
            mean_track_length_frames=0.0,
            tracking_warning=str(exc),
            params=params,
        )

    valid_tracks, total_steps, mean_len = compute_track_statistics(tracks)
    if valid_tracks == 0:
        return CroppedPreviewAnalysis(
            frames=frames,
            tracks=tracks,
            starting_points=starting_points,
            downward_velocity_index_um_per_s=0.0,
            general_movement_index_um_per_s=0.0,
            num_tracks_with_valid_steps=0,
            total_valid_steps=0,
            mean_track_length_frames=0.0,
            tracking_warning=(
                warning or "Tracking failed or too few points survived. "
                "Adjust ROI or tracking settings."
            ),
            params=params,
        )

    downward, general, _ = compute_motion_indices(tracks, params)
    velocity_summary = compute_velocity_summary(tracks, params)
    return CroppedPreviewAnalysis(
        frames=frames,
        tracks=tracks,
        starting_points=starting_points,
        downward_velocity_index_um_per_s=downward,
        general_movement_index_um_per_s=general,
        num_tracks_with_valid_steps=valid_tracks,
        total_valid_steps=total_steps,
        mean_track_length_frames=mean_len,
        time_weighted_mean_speed_um_per_s=(
            velocity_summary.time_weighted_mean_speed_um_per_s
        ),
        signed_vertical_velocity_um_per_s=(
            velocity_summary.signed_vertical_velocity_um_per_s
        ),
        downward_velocity_contribution_um_per_s=(
            velocity_summary.downward_velocity_contribution_um_per_s
        ),
        tracking_warning=warning,
        params=params,
    )


def render_cropped_tracking_frame(
    analysis: CroppedPreviewAnalysis,
    frame_index: int,
) -> np.ndarray:
    """Return one cropped ROI frame with optional tracking overlay."""
    index = max(0, min(frame_index, len(analysis.frames) - 1))
    frame = analysis.frames[index]
    if not analysis.tracks:
        return frame.copy()
    return render_track_preview_frame(frame, analysis.tracks, index)


def is_supported_video_path(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def probe_video_frame_count(path: Path) -> int:
    _, _, total = load_media_frame(path, 0)
    return max(1, total)
