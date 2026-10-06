"""Research-only comparison of local F-actin orientation estimators.

All orientations are axial (0–180 degrees); traversal direction is irrelevant.
This module does not define a production metric or persist workspace results.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Callable

import cv2
import numpy as np

from actintrack_app.motion_index import frame_to_signal

METHOD_STRUCTURE_TENSOR = "structure_tensor"
METHOD_LOCAL_PCA = "local_pca"
METHOD_SKELETON_TANGENT = "skeleton_tangent"
METHOD_HOUGH_LINES = "hough_lines"
ORIENTATION_RESEARCH_VERSION = 1


@dataclass(frozen=True)
class OrientationResearchSettings:
    threshold_percentile: float = 70.0
    window_size_px: int = 15
    sample_spacing_px: int = 6
    minimum_confidence: float = 0.05
    hough_min_line_length_px: int = 12
    hough_max_line_gap_px: int = 4

    def __post_init__(self) -> None:
        if not 0.0 <= self.threshold_percentile <= 100.0:
            raise ValueError("threshold_percentile must be between 0 and 100.")
        if self.window_size_px < 5 or self.window_size_px % 2 == 0:
            raise ValueError("window_size_px must be an odd integer >= 5.")
        if self.sample_spacing_px < 1:
            raise ValueError("sample_spacing_px must be positive.")
        if not 0.0 <= self.minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence must be between 0 and 1.")


@dataclass(frozen=True)
class OrientationEstimate:
    x_px: float
    y_px: float
    local_orientation_deg: float
    confidence: float
    method: str


@dataclass(frozen=True)
class OrientationMethodResult:
    method: str
    estimates: tuple[OrientationEstimate, ...]
    runtime_ms: float
    foreground_pixel_count: int
    valid_pixel_count: int
    settings: OrientationResearchSettings

    def as_dict(self) -> dict[str, object]:
        return {
            "method": self.method,
            "runtime_ms": self.runtime_ms,
            "foreground_pixel_count": self.foreground_pixel_count,
            "valid_pixel_count": self.valid_pixel_count,
            "settings": asdict(self.settings),
            "estimates": [asdict(item) for item in self.estimates],
        }


def axial_angle_error_deg(measured_deg: float, expected_deg: float) -> float:
    """Smallest difference between two undirected line orientations."""
    return abs(((float(measured_deg) - float(expected_deg) + 90.0) % 180.0) - 90.0)


def angle_relative_to_nucleus_deg(
    local_orientation_deg: float,
    x_px: float,
    y_px: float,
    nucleus_xy_px: tuple[float, float],
) -> float:
    """Return 0–90 degree axial angle between a cable and radial direction."""
    radial_x = float(x_px) - float(nucleus_xy_px[0])
    radial_y = float(y_px) - float(nucleus_xy_px[1])
    radial_norm = float(np.hypot(radial_x, radial_y))
    if radial_norm <= 1e-12:
        raise ValueError("Orientation is undefined at the nucleus center.")
    theta = np.deg2rad(float(local_orientation_deg))
    filament = np.array([np.cos(theta), np.sin(theta)], dtype=np.float64)
    radial = np.array([radial_x, radial_y], dtype=np.float64) / radial_norm
    return float(np.degrees(np.arccos(np.clip(abs(float(filament @ radial)), 0.0, 1.0))))


def axial_circular_mean_deg(
    estimates: tuple[OrientationEstimate, ...] | list[OrientationEstimate],
) -> float | None:
    if not estimates:
        return None
    weights = np.array([max(0.0, item.confidence) for item in estimates], dtype=np.float64)
    if float(weights.sum()) <= 0:
        weights = np.ones(len(estimates), dtype=np.float64)
    angles = np.deg2rad([2.0 * item.local_orientation_deg for item in estimates])
    x = float(np.sum(weights * np.cos(angles)))
    y = float(np.sum(weights * np.sin(angles)))
    return float((0.5 * np.degrees(np.arctan2(y, x))) % 180.0)


def _inputs(
    frame: np.ndarray,
    valid_mask: np.ndarray | None,
    settings: OrientationResearchSettings,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    signal = frame_to_signal(frame).astype(np.float32)
    h, w = signal.shape
    if valid_mask is None:
        valid = np.ones((h, w), dtype=bool)
    else:
        valid = np.asarray(valid_mask, dtype=bool)
        if valid.shape != (h, w):
            raise ValueError(
                f"valid_mask shape {valid.shape} does not match frame {(h, w)}."
            )
    values = signal[valid]
    if values.size == 0:
        return signal, valid, np.zeros((h, w), dtype=bool)
    percentile_threshold = float(
        np.percentile(values, settings.threshold_percentile)
    )
    robust_floor = float(np.median(values))
    robust_high = float(np.percentile(values, 99.0))
    contrast_threshold = robust_floor + 0.15 * max(
        0.0,
        robust_high - robust_floor,
    )
    threshold = max(percentile_threshold, contrast_threshold)
    foreground = valid & (signal >= threshold) & (signal > float(values.min()))
    return signal, valid, foreground


def _sample_mask(
    mask: np.ndarray,
    spacing: int,
    *,
    scores: np.ndarray | None = None,
) -> list[tuple[int, int]]:
    ys, xs = np.where(mask)
    if ys.size == 0:
        return []
    best_by_cell: dict[tuple[int, int], tuple[float, int, int]] = {}
    for index in range(ys.size):
        x, y = int(xs[index]), int(ys[index])
        cell = (x // spacing, y // spacing)
        score = float(scores[y, x]) if scores is not None else 0.0
        candidate = (score, -y, -x)
        current = best_by_cell.get(cell)
        if current is None or candidate > current:
            best_by_cell[cell] = candidate
    return sorted(
        [(-item[2], -item[1]) for item in best_by_cell.values()],
        key=lambda xy: (xy[1], xy[0]),
    )


def _pca_orientation(
    xs: np.ndarray,
    ys: np.ndarray,
    weights: np.ndarray,
) -> tuple[float, float] | None:
    if xs.size < 3 or float(weights.sum()) <= 1e-12:
        return None
    mean_x = float(np.average(xs, weights=weights))
    mean_y = float(np.average(ys, weights=weights))
    centered = np.column_stack((xs - mean_x, ys - mean_y))
    covariance = np.cov(centered.T, aweights=weights)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    major_index = int(np.argmax(eigenvalues))
    major = eigenvectors[:, major_index]
    major_value = float(max(eigenvalues[major_index], 0.0))
    minor_value = float(max(eigenvalues[1 - major_index], 0.0))
    confidence = (major_value - minor_value) / (major_value + minor_value + 1e-12)
    angle = float(np.degrees(np.arctan2(major[1], major[0])) % 180.0)
    return angle, float(np.clip(confidence, 0.0, 1.0))


def _result(
    method: str,
    estimates: list[OrientationEstimate],
    started: float,
    foreground: np.ndarray,
    valid: np.ndarray,
    settings: OrientationResearchSettings,
) -> OrientationMethodResult:
    return OrientationMethodResult(
        method=method,
        estimates=tuple(estimates),
        runtime_ms=(time.perf_counter() - started) * 1000.0,
        foreground_pixel_count=int(np.count_nonzero(foreground)),
        valid_pixel_count=int(np.count_nonzero(valid)),
        settings=settings,
    )


def structure_tensor_orientations(
    frame: np.ndarray,
    *,
    valid_mask: np.ndarray | None = None,
    settings: OrientationResearchSettings | None = None,
) -> OrientationMethodResult:
    settings = settings or OrientationResearchSettings()
    started = time.perf_counter()
    signal, valid, foreground = _inputs(frame, valid_mask, settings)
    gx = cv2.Sobel(signal, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(signal, cv2.CV_32F, 0, 1, ksize=3)
    kernel = settings.window_size_px
    jxx = cv2.GaussianBlur(gx * gx, (kernel, kernel), 0)
    jyy = cv2.GaussianBlur(gy * gy, (kernel, kernel), 0)
    jxy = cv2.GaussianBlur(gx * gy, (kernel, kernel), 0)
    coherence = np.sqrt((jxx - jyy) ** 2 + 4.0 * jxy**2) / (
        jxx + jyy + 1e-12
    )
    gradient_angle = 0.5 * np.arctan2(2.0 * jxy, jxx - jyy)
    tangent_angle = (np.degrees(gradient_angle) + 90.0) % 180.0
    sample_mask = foreground & (coherence >= settings.minimum_confidence)
    estimates = [
        OrientationEstimate(
            x_px=float(x),
            y_px=float(y),
            local_orientation_deg=float(tangent_angle[y, x]),
            confidence=float(np.clip(coherence[y, x], 0.0, 1.0)),
            method=METHOD_STRUCTURE_TENSOR,
        )
        for x, y in _sample_mask(
            sample_mask,
            settings.sample_spacing_px,
            scores=coherence,
        )
    ]
    return _result(
        METHOD_STRUCTURE_TENSOR,
        estimates,
        started,
        foreground,
        valid,
        settings,
    )


def local_pca_orientations(
    frame: np.ndarray,
    *,
    valid_mask: np.ndarray | None = None,
    settings: OrientationResearchSettings | None = None,
) -> OrientationMethodResult:
    settings = settings or OrientationResearchSettings()
    started = time.perf_counter()
    signal, valid, foreground = _inputs(frame, valid_mask, settings)
    half = settings.window_size_px // 2
    estimates: list[OrientationEstimate] = []
    for x, y in _sample_mask(
        foreground,
        settings.sample_spacing_px,
        scores=signal,
    ):
        x0, x1 = max(0, x - half), min(signal.shape[1], x + half + 1)
        y0, y1 = max(0, y - half), min(signal.shape[0], y + half + 1)
        local = foreground[y0:y1, x0:x1]
        ys, xs = np.where(local)
        if ys.size < 3:
            continue
        values = signal[y0:y1, x0:x1][ys, xs].astype(np.float64)
        weights = np.maximum(values - float(values.min()) + 1e-6, 1e-6)
        estimate = _pca_orientation(
            xs.astype(np.float64) + x0,
            ys.astype(np.float64) + y0,
            weights,
        )
        if estimate is None or estimate[1] < settings.minimum_confidence:
            continue
        estimates.append(
            OrientationEstimate(
                float(x),
                float(y),
                estimate[0],
                estimate[1],
                METHOD_LOCAL_PCA,
            )
        )
    return _result(METHOD_LOCAL_PCA, estimates, started, foreground, valid, settings)


def _morphological_skeleton(binary: np.ndarray) -> np.ndarray:
    image = (binary.astype(np.uint8) * 255).copy()
    skeleton = np.zeros_like(image)
    element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    while cv2.countNonZero(image) > 0:
        eroded = cv2.erode(image, element)
        opened = cv2.dilate(eroded, element)
        skeleton = cv2.bitwise_or(skeleton, cv2.subtract(image, opened))
        image = eroded
    return skeleton > 0


def skeleton_tangent_orientations(
    frame: np.ndarray,
    *,
    valid_mask: np.ndarray | None = None,
    settings: OrientationResearchSettings | None = None,
) -> OrientationMethodResult:
    settings = settings or OrientationResearchSettings()
    started = time.perf_counter()
    _signal, valid, foreground = _inputs(frame, valid_mask, settings)
    skeleton = _morphological_skeleton(foreground) & valid
    half = settings.window_size_px // 2
    estimates: list[OrientationEstimate] = []
    for x, y in _sample_mask(skeleton, settings.sample_spacing_px):
        x0, x1 = max(0, x - half), min(skeleton.shape[1], x + half + 1)
        y0, y1 = max(0, y - half), min(skeleton.shape[0], y + half + 1)
        ys, xs = np.where(skeleton[y0:y1, x0:x1])
        estimate = _pca_orientation(
            xs.astype(np.float64) + x0,
            ys.astype(np.float64) + y0,
            np.ones(xs.size, dtype=np.float64),
        )
        if estimate is None or estimate[1] < settings.minimum_confidence:
            continue
        estimates.append(
            OrientationEstimate(
                float(x),
                float(y),
                estimate[0],
                estimate[1],
                METHOD_SKELETON_TANGENT,
            )
        )
    return _result(
        METHOD_SKELETON_TANGENT,
        estimates,
        started,
        foreground,
        valid,
        settings,
    )


def normalize_hough_lines_p(lines: np.ndarray | None) -> np.ndarray:
    """Normalize ``cv2.HoughLinesP`` output to shape ``(N, 4)``.

    OpenCV may return either ``(N, 1, 4)`` or ``(N, 4)`` where each row is
    ``(x1, y1, x2, y2)``. Those layouts are semantically equivalent. Other
    shapes are rejected rather than silently reinterpreted.
    """
    if lines is None:
        return np.empty((0, 4), dtype=np.float64)
    arr = np.asarray(lines)
    if arr.size == 0:
        return np.empty((0, 4), dtype=np.float64)
    if arr.ndim == 3 and arr.shape[1] == 1 and arr.shape[2] == 4:
        arr = arr[:, 0, :]
    elif arr.ndim == 2 and arr.shape[1] == 4:
        pass
    else:
        raise ValueError(
            f"Unexpected HoughLinesP array shape {arr.shape}; "
            "expected (N, 1, 4) or (N, 4)."
        )
    return np.asarray(arr, dtype=np.float64)


def hough_line_orientations(
    frame: np.ndarray,
    *,
    valid_mask: np.ndarray | None = None,
    settings: OrientationResearchSettings | None = None,
) -> OrientationMethodResult:
    settings = settings or OrientationResearchSettings()
    started = time.perf_counter()
    signal, valid, foreground = _inputs(frame, valid_mask, settings)
    image = np.where(foreground, signal, 0.0)
    scaled = cv2.normalize(image, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    edges = cv2.Canny(scaled, 40, 120)
    edges[~valid] = 0
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180.0,
        threshold=8,
        minLineLength=settings.hough_min_line_length_px,
        maxLineGap=settings.hough_max_line_gap_px,
    )
    estimates: list[OrientationEstimate] = []
    normalized = normalize_hough_lines_p(lines)
    if normalized.size:
        diagonal = float(np.hypot(*signal.shape))
        for raw in normalized:
            x0, y0, x1, y1 = map(float, raw)
            x, y = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            xi, yi = int(round(x)), int(round(y))
            if not (0 <= yi < valid.shape[0] and 0 <= xi < valid.shape[1]):
                continue
            if not valid[yi, xi]:
                continue
            length = float(np.hypot(x1 - x0, y1 - y0))
            estimates.append(
                OrientationEstimate(
                    x,
                    y,
                    float(np.degrees(np.arctan2(y1 - y0, x1 - x0)) % 180.0),
                    float(np.clip(length / max(diagonal, 1.0), 0.0, 1.0)),
                    METHOD_HOUGH_LINES,
                )
            )
    return _result(METHOD_HOUGH_LINES, estimates, started, foreground, valid, settings)


ORIENTATION_METHODS: dict[
    str,
    Callable[..., OrientationMethodResult],
] = {
    METHOD_STRUCTURE_TENSOR: structure_tensor_orientations,
    METHOD_LOCAL_PCA: local_pca_orientations,
    METHOD_SKELETON_TANGENT: skeleton_tangent_orientations,
    METHOD_HOUGH_LINES: hough_line_orientations,
}


def run_orientation_method(
    method: str,
    frame: np.ndarray,
    *,
    valid_mask: np.ndarray | None = None,
    settings: OrientationResearchSettings | None = None,
) -> OrientationMethodResult:
    try:
        runner = ORIENTATION_METHODS[method]
    except KeyError as exc:
        raise ValueError(f"Unknown orientation method: {method}") from exc
    return runner(frame, valid_mask=valid_mask, settings=settings)
