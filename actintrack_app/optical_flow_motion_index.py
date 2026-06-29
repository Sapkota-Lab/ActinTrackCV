"""Dense Farnebäck optical-flow motion index for cropped ROI video frames."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

import cv2
import numpy as np

from actintrack_app.motion_index import (
    DEFAULT_MICRONS_PER_PIXEL,
    DEFAULT_SECONDS_PER_FRAME,
)

ALGORITHM_NAME = "dense_farneback"
ALGORITHM_VERSION = 1
DOWNWARD_DIRECTION = "increasing_y"


@dataclass(frozen=True)
class OpticalFlowSettings:
    """Parameters for dense Farnebäck optical-flow motion index."""

    mask_percentile: float = 90.0
    gaussian_blur_kernel: int = 3
    pyr_scale: float = 0.5
    levels: int = 3
    winsize: int = 15
    iterations: int = 3
    poly_n: int = 5
    poly_sigma: float = 1.2
    microns_per_pixel: float = DEFAULT_MICRONS_PER_PIXEL
    seconds_per_frame: float = DEFAULT_SECONDS_PER_FRAME
    downward_direction: str = DOWNWARD_DIRECTION

    def __post_init__(self) -> None:
        if not 0 <= self.mask_percentile <= 100:
            raise ValueError("mask_percentile must be between 0 and 100.")
        if self.gaussian_blur_kernel not in (0, 3, 5):
            raise ValueError("gaussian_blur_kernel must be 0, 3, or 5.")
        if self.microns_per_pixel <= 0:
            raise ValueError("microns_per_pixel must be positive.")
        if self.seconds_per_frame <= 0:
            raise ValueError("seconds_per_frame must be positive.")


@dataclass(frozen=True)
class FramePairSummary:
    frame_a: int
    frame_b: int
    valid_pixel_count: int
    valid_pixel_fraction: float
    saturated_pixel_fraction: float
    mean_magnitude_px_frame: float
    mean_downward_px_frame: float
    mean_net_x_px_frame: float
    mean_net_y_px_frame: float


@dataclass
class OpticalFlowResult:
    """Summary optical-flow motion index for one sample."""

    has_valid_result: bool = False
    failure_reason: str = ""
    optical_flow_general_movement_um_s: Optional[float] = None
    optical_flow_downward_motion_um_s: Optional[float] = None
    optical_flow_net_y_velocity_um_s: Optional[float] = None
    optical_flow_directionality_ratio: Optional[float] = None
    optical_flow_valid_pixel_fraction: Optional[float] = None
    optical_flow_saturated_pixel_fraction: Optional[float] = None
    mean_magnitude_px_frame: Optional[float] = None
    mean_downward_px_frame: Optional[float] = None
    mean_net_x_px_frame: Optional[float] = None
    mean_net_y_px_frame: Optional[float] = None
    frame_count: int = 0
    frame_pair_count: int = 0
    frame_pair_summaries: list[FramePairSummary] = field(default_factory=list)
    fingerprint: str = ""
    analysis_timestamp_utc: str = ""
    sample_id: str = ""
    data_identity: str = ""
    roi_bounds: tuple[int, int, int, int] = (0, 0, 0, 0)
    settings: Optional[OpticalFlowSettings] = None

    def summary_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "algorithm": ALGORITHM_NAME,
            "algorithm_version": ALGORITHM_VERSION,
            "sample_id": self.sample_id,
            "data_identity": self.data_identity,
            "roi_bounds": list(self.roi_bounds),
            "fingerprint": self.fingerprint,
            "analysis_timestamp_utc": self.analysis_timestamp_utc,
            "has_valid_result": self.has_valid_result,
            "failure_reason": self.failure_reason,
            "frame_count": self.frame_count,
            "frame_pair_count": self.frame_pair_count,
            "optical_flow_general_movement_um_s": self.optical_flow_general_movement_um_s,
            "optical_flow_downward_motion_um_s": self.optical_flow_downward_motion_um_s,
            "optical_flow_net_y_velocity_um_s": self.optical_flow_net_y_velocity_um_s,
            "optical_flow_directionality_ratio": self.optical_flow_directionality_ratio,
            "optical_flow_valid_pixel_fraction": self.optical_flow_valid_pixel_fraction,
            "optical_flow_saturated_pixel_fraction": self.optical_flow_saturated_pixel_fraction,
            "mean_magnitude_px_frame": self.mean_magnitude_px_frame,
            "mean_downward_px_frame": self.mean_downward_px_frame,
            "mean_net_x_px_frame": self.mean_net_x_px_frame,
            "mean_net_y_px_frame": self.mean_net_y_px_frame,
            "frame_pair_summaries": [asdict(s) for s in self.frame_pair_summaries],
        }
        if self.settings is not None:
            payload["settings"] = asdict(self.settings)
        return payload


def _to_grayscale(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 2:
        return frame.astype(np.float32)
    if frame.ndim == 3 and frame.shape[2] >= 3:
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return np.asarray(frame, dtype=np.float32).squeeze()


def _apply_blur(gray: np.ndarray, kernel: int) -> np.ndarray:
    if kernel <= 0:
        return gray
    return cv2.GaussianBlur(gray, (kernel, kernel), 0)


def _brightness_mask(gray: np.ndarray, percentile: float) -> np.ndarray:
    threshold = float(np.percentile(gray, percentile))
    return gray > threshold


def _saturated_mask(gray: np.ndarray) -> np.ndarray:
    if gray.dtype == np.uint16 or np.max(gray) > 255:
        sat_threshold = float(np.percentile(gray, 99.9))
        return gray >= sat_threshold
    return gray >= 254.0


def _px_per_frame_to_um_per_s(value_px: float, settings: OpticalFlowSettings) -> float:
    return value_px * settings.microns_per_pixel / settings.seconds_per_frame


@dataclass(frozen=True)
class DenseFlowPair:
    """Dense optical flow and brightness mask for one consecutive frame pair."""

    flow: np.ndarray
    mask: np.ndarray
    prev_gray: np.ndarray
    frame_a: int
    frame_b: int


def preprocess_frame(frame: np.ndarray, settings: OpticalFlowSettings) -> np.ndarray:
    """Grayscale + optional Gaussian blur preprocessing for optical flow."""
    return _apply_blur(_to_grayscale(frame), settings.gaussian_blur_kernel)


def compute_dense_flow_pair(
    prev_frame: np.ndarray,
    next_frame: np.ndarray,
    settings: OpticalFlowSettings,
    *,
    frame_a: int = 0,
    frame_b: int = 1,
) -> DenseFlowPair:
    """Compute dense Farnebäck flow and brightness mask for one frame pair."""
    prev_gray = preprocess_frame(prev_frame, settings)
    next_gray = preprocess_frame(next_frame, settings)
    mask = _brightness_mask(prev_gray, settings.mask_percentile)
    flow = cv2.calcOpticalFlowFarneback(
        prev_gray,
        next_gray,
        None,
        settings.pyr_scale,
        settings.levels,
        settings.winsize,
        settings.iterations,
        settings.poly_n,
        settings.poly_sigma,
        0,
    )
    return DenseFlowPair(
        flow=flow,
        mask=mask,
        prev_gray=prev_gray,
        frame_a=frame_a,
        frame_b=frame_b,
    )


def _failed_result(
    reason: str,
    *,
    sample_id: str = "",
    settings: Optional[OpticalFlowSettings] = None,
    frame_count: int = 0,
    data_identity: str = "",
    roi_bounds: tuple[int, int, int, int] = (0, 0, 0, 0),
    fingerprint: str = "",
) -> OpticalFlowResult:
    return OpticalFlowResult(
        has_valid_result=False,
        failure_reason=reason,
        sample_id=sample_id,
        settings=settings,
        frame_count=frame_count,
        data_identity=data_identity,
        roi_bounds=roi_bounds,
        fingerprint=fingerprint,
        analysis_timestamp_utc=datetime.now(timezone.utc).isoformat(),
    )


def compute_optical_flow_motion_index(
    frames: Sequence[np.ndarray],
    settings: OpticalFlowSettings,
    *,
    sample_id: str = "",
    data_identity: str = "",
    roi_bounds: tuple[int, int, int, int] = (0, 0, 0, 0),
    fingerprint: str = "",
) -> OpticalFlowResult:
    """Compute dense Farnebäck optical-flow metrics over consecutive cropped frames."""
    if len(frames) < 2:
        return _failed_result(
            "At least 2 frames are required for optical flow.",
            sample_id=sample_id,
            settings=settings,
            frame_count=len(frames),
            data_identity=data_identity,
            roi_bounds=roi_bounds,
            fingerprint=fingerprint,
        )

    first = frames[0]
    if first.size == 0 or first.shape[0] == 0 or first.shape[1] == 0:
        return _failed_result(
            "Cropped ROI is empty.",
            sample_id=sample_id,
            settings=settings,
            frame_count=len(frames),
            data_identity=data_identity,
            roi_bounds=roi_bounds,
            fingerprint=fingerprint,
        )

    pair_summaries: list[FramePairSummary] = []
    mag_values: list[float] = []
    downward_values: list[float] = []
    net_x_values: list[float] = []
    net_y_values: list[float] = []
    valid_fractions: list[float] = []
    saturated_fractions: list[float] = []

    for i in range(len(frames) - 1):
        pair = compute_dense_flow_pair(
            frames[i], frames[i + 1], settings, frame_a=i, frame_b=i + 1
        )
        mask = pair.mask
        flow = pair.flow
        prev_gray = pair.prev_gray
        valid_count = int(np.count_nonzero(mask))
        total_pixels = int(mask.size)
        if valid_count == 0:
            continue

        flow_y = flow[..., 1]
        flow_x = flow[..., 0]
        magnitude = np.sqrt(flow_x ** 2 + flow_y ** 2)
        downward = np.maximum(flow_y, 0.0)

        mag_mean = float(np.mean(magnitude[mask]))
        down_mean = float(np.mean(downward[mask]))
        net_x_mean = float(np.mean(flow_x[mask]))
        net_y_mean = float(np.mean(flow_y[mask]))
        valid_fraction = valid_count / total_pixels
        sat_fraction = float(np.count_nonzero(_saturated_mask(prev_gray) & mask)) / total_pixels

        pair_summaries.append(
            FramePairSummary(
                frame_a=i,
                frame_b=i + 1,
                valid_pixel_count=valid_count,
                valid_pixel_fraction=valid_fraction,
                saturated_pixel_fraction=sat_fraction,
                mean_magnitude_px_frame=mag_mean,
                mean_downward_px_frame=down_mean,
                mean_net_x_px_frame=net_x_mean,
                mean_net_y_px_frame=net_y_mean,
            )
        )
        mag_values.append(mag_mean)
        downward_values.append(down_mean)
        net_x_values.append(net_x_mean)
        net_y_values.append(net_y_mean)
        valid_fractions.append(valid_fraction)
        saturated_fractions.append(sat_fraction)

    if not pair_summaries:
        return _failed_result(
            "No valid pixels passed the brightness mask for optical flow.",
            sample_id=sample_id,
            settings=settings,
            frame_count=len(frames),
            data_identity=data_identity,
            roi_bounds=roi_bounds,
            fingerprint=fingerprint,
        )

    mean_mag_px = float(np.mean(mag_values))
    mean_down_px = float(np.mean(downward_values))
    mean_net_x_px = float(np.mean(net_x_values))
    mean_net_y_px = float(np.mean(net_y_values))
    general_um_s = _px_per_frame_to_um_per_s(mean_mag_px, settings)
    downward_um_s = _px_per_frame_to_um_per_s(mean_down_px, settings)
    net_y_um_s = _px_per_frame_to_um_per_s(mean_net_y_px, settings)
    directionality: Optional[float] = None
    if mean_mag_px > 1e-12:
        directionality = mean_down_px / mean_mag_px

    return OpticalFlowResult(
        has_valid_result=True,
        optical_flow_general_movement_um_s=general_um_s,
        optical_flow_downward_motion_um_s=downward_um_s,
        optical_flow_net_y_velocity_um_s=net_y_um_s,
        optical_flow_directionality_ratio=directionality,
        optical_flow_valid_pixel_fraction=float(np.mean(valid_fractions)),
        optical_flow_saturated_pixel_fraction=float(np.mean(saturated_fractions)),
        mean_magnitude_px_frame=mean_mag_px,
        mean_downward_px_frame=mean_down_px,
        mean_net_x_px_frame=mean_net_x_px,
        mean_net_y_px_frame=mean_net_y_px,
        frame_count=len(frames),
        frame_pair_count=len(pair_summaries),
        frame_pair_summaries=pair_summaries,
        fingerprint=fingerprint,
        analysis_timestamp_utc=datetime.now(timezone.utc).isoformat(),
        sample_id=sample_id,
        data_identity=data_identity,
        roi_bounds=roi_bounds,
        settings=settings,
    )


def build_optical_flow_fingerprint(
    *,
    sample_id: str,
    roi_bounds: tuple[int, int, int, int],
    settings: OpticalFlowSettings,
    data_identity: str = "",
    frame_count: int = 0,
) -> str:
    """Stable hash of inputs that define optical-flow reproducibility."""
    canonical = {
        "algorithm": ALGORITHM_NAME,
        "algorithm_version": ALGORITHM_VERSION,
        "sample_id": sample_id,
        "data_identity": data_identity,
        "roi_bounds": list(roi_bounds),
        "frame_count": frame_count,
        "settings": asdict(settings),
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def is_optical_flow_result_stale(saved_fingerprint: str, current_fingerprint: str) -> bool:
    if not saved_fingerprint or not current_fingerprint:
        return True
    return saved_fingerprint != current_fingerprint


def result_to_dict(result: OpticalFlowResult) -> dict[str, Any]:
    return result.summary_dict()


def result_from_dict(data: dict[str, Any]) -> OpticalFlowResult:
    settings_data = data.get("settings")
    settings = OpticalFlowSettings(**settings_data) if isinstance(settings_data, dict) else None
    roi_raw = data.get("roi_bounds", (0, 0, 0, 0))
    roi_bounds = tuple(int(v) for v in roi_raw) if roi_raw else (0, 0, 0, 0)
    summaries = []
    for item in data.get("frame_pair_summaries", []) or []:
        if isinstance(item, dict):
            summaries.append(FramePairSummary(**item))
    return OpticalFlowResult(
        has_valid_result=bool(data.get("has_valid_result")),
        failure_reason=str(data.get("failure_reason", "")),
        optical_flow_general_movement_um_s=_optional_float(
            data.get("optical_flow_general_movement_um_s")
        ),
        optical_flow_downward_motion_um_s=_optional_float(
            data.get("optical_flow_downward_motion_um_s")
        ),
        optical_flow_net_y_velocity_um_s=_optional_float(
            data.get("optical_flow_net_y_velocity_um_s")
        ),
        optical_flow_directionality_ratio=_optional_float(
            data.get("optical_flow_directionality_ratio")
        ),
        optical_flow_valid_pixel_fraction=_optional_float(
            data.get("optical_flow_valid_pixel_fraction")
        ),
        optical_flow_saturated_pixel_fraction=_optional_float(
            data.get("optical_flow_saturated_pixel_fraction")
        ),
        mean_magnitude_px_frame=_optional_float(data.get("mean_magnitude_px_frame")),
        mean_downward_px_frame=_optional_float(data.get("mean_downward_px_frame")),
        mean_net_x_px_frame=_optional_float(data.get("mean_net_x_px_frame")),
        mean_net_y_px_frame=_optional_float(data.get("mean_net_y_px_frame")),
        frame_count=int(data.get("frame_count", 0) or 0),
        frame_pair_count=int(data.get("frame_pair_count", 0) or 0),
        frame_pair_summaries=summaries,
        fingerprint=str(data.get("fingerprint", "")),
        analysis_timestamp_utc=str(data.get("analysis_timestamp_utc", "")),
        sample_id=str(data.get("sample_id", "")),
        data_identity=str(data.get("data_identity", "")),
        roi_bounds=roi_bounds,  # type: ignore[arg-type]
        settings=settings,
    )


def _optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
