"""Image processing helpers for ActinTrackCV."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class TrackingCrop:
    """Detected 2D tracking crop for the filament-rich cell region."""

    x0: int
    y0: int
    x1: int
    y1: int
    cutoff_y: int
    foreground_bbox: dict[str, int]
    confidence: float
    method: str
    signal_source: str
    notes: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _smooth_1d(values: np.ndarray, window: int) -> np.ndarray:
    window = max(3, int(window) | 1)
    if values.size < window:
        window = max(3, values.size | 1)
    kernel = np.ones(window, dtype=np.float32) / float(window)
    return np.convolve(values.astype(np.float32), kernel, mode="same")


def _normalise_signal(signal: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(signal, [1.0, 99.7])
    if hi <= lo:
        raise ValueError("Image has insufficient signal contrast for crop detection.")
    return np.clip((signal - lo) / (hi - lo), 0.0, 1.0).astype(np.float32)


def actin_signal_image(image: np.ndarray) -> tuple[np.ndarray, str]:
    """
    Return a normalized actin-dominant signal image.

    The current app previews frames as BGR. For color composites, actin is the
    cyan/green signal in Picture1/Montage references, while magenta context is
    de-emphasized. For grayscale video exports, the grayscale intensity is used.
    """
    if image.ndim == 2:
        return _normalise_signal(image.astype(np.float32)), "grayscale"

    if image.ndim != 3 or image.shape[2] < 3:
        raise ValueError(f"Unsupported image shape for crop detection: {image.shape}")

    b = image[..., 0].astype(np.float32)
    g = image[..., 1].astype(np.float32)
    r = image[..., 2].astype(np.float32)

    gray = (0.114 * b) + (0.587 * g) + (0.299 * r)
    cyan_actin = np.maximum(b, g) - (0.25 * r)
    cyan_actin = np.clip(cyan_actin, 0.0, None)
    markup_mask = (r > 180) & (g > 180) & (b < 120)
    cyan_actin[markup_mask] = 0.0
    gray[markup_mask] = 0.0

    if np.percentile(cyan_actin, 99) - np.percentile(cyan_actin, 5) < 5:
        return _normalise_signal(gray), "grayscale_fallback"
    return _normalise_signal(cyan_actin), "cyan_green_actin"


def _largest_foreground_component(signal: np.ndarray) -> tuple[np.ndarray, dict[str, int]]:
    import cv2

    signal_u8 = (signal * 255).astype(np.uint8)
    otsu_value, _ = cv2.threshold(
        signal_u8,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
    )
    threshold = max(0.04, min(0.12, float(otsu_value / 255.0) * 0.45))
    mask = (signal > threshold).astype(np.uint8)

    kernel = np.ones((5, 5), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if n_labels <= 1:
        raise ValueError("No foreground cell-like signal detected.")

    component_idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h, area = [int(v) for v in stats[component_idx]]
    if area < 50 or w < 5 or h < 5:
        raise ValueError("Detected foreground is too small for crop detection.")

    component = labels == component_idx
    bbox = {"x0": x, "y0": y, "x1": x + w, "y1": y + h, "area_px": area}
    return component, bbox


def detect_tracking_crop(image: np.ndarray) -> TrackingCrop:
    """
    Detect the upper/central filament ROI and exclude the lower perinuclear region.

    This implements the corrected Picture1 interpretation: A/B are biological
    tracking regions within the actin-rich shaft; C is the lower
    nucleus/perinuclear transition region. The cutoff is derived from the
    foreground mask, row-wise signal mass, and the sustained gradient into the
    brighter lower actin ring, not from fixed pixel fractions or panel widths.
    """
    if image.ndim < 2:
        raise ValueError(f"Expected image with at least 2 dimensions, got {image.shape}")

    image_h, image_w = image.shape[:2]
    signal, signal_source = actin_signal_image(image)
    component, bbox = _largest_foreground_component(signal)

    x0, y0, x1, y1 = bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"]
    comp = component[y0:y1, x0:x1]
    sig = signal[y0:y1, x0:x1]
    h = int(comp.shape[0])
    if h < 20:
        raise ValueError("Foreground height is too small for biological crop detection.")

    width_profile = comp.sum(axis=1).astype(np.float32)
    mass_profile = (sig * comp).sum(axis=1).astype(np.float32)
    mean_profile = mass_profile / np.maximum(width_profile, 1.0)

    smooth_window = max(7, h // 25)
    width_s = _smooth_1d(width_profile, smooth_window)
    mass_s = _smooth_1d(mass_profile, smooth_window)
    mean_s = _smooth_1d(mean_profile, smooth_window)

    width_n = width_s / (float(width_s.max()) + 1e-6)
    mass_n = mass_s / (float(mass_s.max()) + 1e-6)
    mean_n = mean_s / (float(mean_s.max()) + 1e-6)
    combined = (0.35 * width_n) + (0.45 * mass_n) + (0.20 * mean_n)

    gradient = _smooth_1d(np.gradient(combined), max(5, h // 40))
    start = max(0, int(h * 0.35))
    end = min(h - 1, int(h * 0.82))
    if end <= start:
        raise ValueError("Foreground is too short for gradient crop detection.")

    upper_baseline = float(np.median(combined[: max(3, int(h * 0.35))]))
    lower_peak = float(np.max(combined[int(h * 0.45) :]))
    transition_threshold = upper_baseline + (0.35 * (lower_peak - upper_baseline))

    local_window = max(5, h // 30)
    candidate = None
    for i in range(start, end):
        segment = combined[i : min(h, i + local_window)]
        if segment.size == 0:
            continue
        if np.mean(segment > transition_threshold) > 0.65 and gradient[i] >= -0.002:
            candidate = i
            break

    if candidate is None:
        candidate = start + int(np.argmax(gradient[start:end]))

    cutoff_y = int(max(y0 + 1, min(y0 + candidate, image_h - 1)))
    pad = max(3, int(round(min(image_h, image_w) * 0.015)))
    crop_x0 = max(0, x0 - pad)
    crop_y0 = max(0, y0 - pad)
    crop_x1 = min(image_w, x1 + pad)
    crop_y1 = cutoff_y

    confidence = max(0.0, min(1.0, lower_peak - upper_baseline))
    return TrackingCrop(
        x0=int(crop_x0),
        y0=int(crop_y0),
        x1=int(crop_x1),
        y1=int(crop_y1),
        cutoff_y=int(cutoff_y),
        foreground_bbox=bbox,
        confidence=round(float(confidence), 3),
        method="foreground_signal_gradient_v1",
        signal_source=signal_source,
        notes=(
            "Upper/central filament tracking ROI detected from actin-dominant "
            "foreground and row-wise signal-gradient transition into the lower "
            "perinuclear/nucleus-adjacent region."
        ),
    )


def crop_tracking_region(image: np.ndarray, crop: TrackingCrop | None = None) -> np.ndarray:
    """Crop the detected filament tracking ROI."""
    crop = crop or detect_tracking_crop(image)
    return image[crop.y0 : crop.y1, crop.x0 : crop.x1, ...].copy()


DEFAULT_SEGMENT_PARAMS: dict[str, Any] = {
    "threshold_method": "otsu",
    "manual_threshold": 128,
    "min_area": 500,
    "blur_kernel": 5,
    "morph_close": 2,
    "morph_open": 1,
}


def segment_cell(frame: np.ndarray, params: dict[str, Any] | None = None) -> np.ndarray:
    """
    Whole-cell binary mask (uint8 0/1) via classical CV.

    Used for long-axis orientation, not perfect segmentation.
    """
    import cv2

    p = {**DEFAULT_SEGMENT_PARAMS, **(params or {})}
    if frame.ndim == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame.astype(np.uint8)

    lo, hi = np.percentile(gray, [1.0, 99.5])
    if hi > lo:
        gray = np.clip((gray.astype(np.float32) - lo) * 255.0 / (hi - lo), 0, 255).astype(
            np.uint8
        )

    k = max(3, int(p["blur_kernel"]) | 1)
    blurred = cv2.GaussianBlur(gray, (k, k), 0)
    method = str(p.get("threshold_method", "otsu")).lower()

    if method == "adaptive":
        block = max(11, int(p.get("adaptive_block", 31)) | 1)
        mask = cv2.adaptiveThreshold(
            blurred,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            block,
            2,
        )
    elif method == "manual":
        thresh = int(p.get("manual_threshold", 128))
        _, mask = cv2.threshold(blurred, thresh, 255, cv2.THRESH_BINARY)
    else:
        _, mask = cv2.threshold(
            blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )

    close_k = max(1, int(p.get("morph_close", 2)))
    open_k = max(1, int(p.get("morph_open", 1)))
    kernel = np.ones((5, 5), dtype=np.uint8)
    if close_k > 0:
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=close_k)
    if open_k > 0:
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=open_k)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("No cell contour found for segmentation.")

    min_area = int(p.get("min_area", 500))
    contours = [c for c in contours if cv2.contourArea(c) >= min_area]
    if not contours:
        raise ValueError("No contour large enough to represent the cell.")

    largest = max(contours, key=cv2.contourArea)
    out = np.zeros(gray.shape, dtype=np.uint8)
    cv2.drawContours(out, [largest], -1, 1, thickness=cv2.FILLED)
    return out


def compute_cell_axis(mask: np.ndarray) -> float:
    """
    Principal-axis angle in degrees to rotate the cell long axis to vertical.

    Positive angle rotates counter-clockwise (OpenCV convention).
    """
    ys, xs = np.where(mask > 0)
    if len(xs) < 20:
        raise ValueError("Cell mask too small for axis estimation.")

    coords = np.column_stack([xs.astype(np.float64), ys.astype(np.float64)])
    mean = coords.mean(axis=0)
    centered = coords - mean
    cov = np.cov(centered.T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    major = eigvecs[:, int(np.argmax(eigvals))]
    angle_rad = np.arctan2(major[1], major[0])
    rotation_deg = float(np.degrees(np.pi / 2 - angle_rad))
    while rotation_deg > 180:
        rotation_deg -= 360
    while rotation_deg < -180:
        rotation_deg += 360
    return rotation_deg


def rotate_image_and_mask(
    image: np.ndarray,
    mask: np.ndarray | None,
    angle: float,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Rotate image and optional mask, expanding canvas to fit."""
    import cv2

    h, w = image.shape[:2]
    center = (w / 2.0, h / 2.0)
    matrix = cv2.getRotationMatrix2D(center, float(angle), 1.0)
    cos = abs(matrix[0, 0])
    sin = abs(matrix[0, 1])
    new_w = int(h * sin + w * cos)
    new_h = int(h * cos + w * sin)
    matrix[0, 2] += (new_w / 2.0) - center[0]
    matrix[1, 2] += (new_h / 2.0) - center[1]

    rotated = cv2.warpAffine(
        image,
        matrix,
        (new_w, new_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    rotated_mask = None
    if mask is not None:
        rotated_mask = cv2.warpAffine(
            mask.astype(np.uint8),
            matrix,
            (new_w, new_h),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
    return rotated, rotated_mask


def apply_flip(image: np.ndarray, flip_180: bool) -> np.ndarray:
    """Optional 180° flip."""
    if not flip_180:
        return image
    import cv2

    return cv2.rotate(image, cv2.ROTATE_180)


def auto_orient_cell(
    frame: np.ndarray,
    params: dict[str, Any] | None = None,
) -> tuple[float, np.ndarray]:
    """Segment cell and return rotation angle (degrees) to make long axis vertical."""
    mask = segment_cell(frame, params)
    angle = compute_cell_axis(mask)
    return angle, mask


def draw_orientation_overlay(
    image: np.ndarray,
    mask: np.ndarray | None,
    axis_angle_deg: float | None = None,
) -> np.ndarray:
    """Draw cell contour and optional principal axis on a BGR copy."""
    import cv2

    out = image.copy()
    if mask is not None:
        contours, _ = cv2.findContours(
            (mask > 0).astype(np.uint8),
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        cv2.drawContours(out, contours, -1, (0, 255, 255), 2)

    if axis_angle_deg is not None:
        h, w = out.shape[:2]
        cx, cy = w // 2, h // 2
        length = min(h, w) // 2
        rad = np.radians(float(axis_angle_deg) + 90)
        x2 = int(cx + length * np.cos(rad))
        y2 = int(cy + length * np.sin(rad))
        cv2.line(out, (cx, cy), (x2, y2), (255, 120, 0), 2)
    return out


def draw_rect_roi_preview(image: np.ndarray, roi: Any) -> np.ndarray:
    """Draw rectangle ROI on BGR image."""
    import cv2

    from actintrack_app.orientation import RectROI

    out = image.copy()
    r = roi if isinstance(roi, RectROI) else RectROI.from_dict(roi)
    cv2.rectangle(out, (r.x, r.y), (r.x1 - 1, r.y1 - 1), (80, 220, 120), 2)
    cv2.putText(
        out,
        "Analysis ROI",
        (r.x + 4, max(16, r.y + 16)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (80, 220, 120),
        1,
        cv2.LINE_AA,
    )
    return out


def crop_above_cutoff(image: np.ndarray, cutoff_y: int) -> np.ndarray:
    """Legacy: crop region above horizontal cutoff (y < cutoff_y)."""
    h = image.shape[0]
    y = max(0, min(int(cutoff_y), h))
    return image[0:y, :].copy()


def estimate_actin_velocity(cropped_frames):
    """
    Future step:
    Estimate average F-actin movement velocity in the cropped region.
    Possible methods:
    - optical flow
    - skeletonized filament tracking
    - keypoint detection
    - kymograph-inspired analysis
    """
    pass


def auto_detect_blurry_boundary(rotated_frame: np.ndarray):
    """
    Future step:
    Automatically detect the boundary between usable filament region
    and blurry nucleus-adjacent region.
    """
    pass


def rank_wt_vs_mutant(results_table):
    """
    Future step:
    Compare average movement index between 2_WT_550 and 3_Mutant_515.
    Initial goal is ranking rather than exact absolute velocity.
    """
    pass
