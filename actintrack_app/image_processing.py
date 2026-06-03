"""Image processing — placeholders for phases 2+."""

from __future__ import annotations

from typing import Any

import numpy as np


def segment_cell(frame: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    """Phase 2: whole-cell segmentation mask."""
    raise NotImplementedError("Cell segmentation will be added in phase 2.")


def compute_cell_axis(mask: np.ndarray) -> float:
    """Phase 2: principal axis angle in degrees."""
    raise NotImplementedError("Cell axis computation will be added in phase 2.")


def rotate_image_and_mask(
    image: np.ndarray,
    mask: np.ndarray | None,
    angle: float,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Phase 2: rotate image and optional mask."""
    raise NotImplementedError("Rotation will be added in phase 2.")


def apply_flip(image: np.ndarray, flip_180: bool) -> np.ndarray:
    """Phase 2: optional 180° flip."""
    if not flip_180:
        return image
    import cv2

    return cv2.rotate(image, cv2.ROTATE_180)


def crop_above_cutoff(image: np.ndarray, cutoff_y: int) -> np.ndarray:
    """Phase 2: crop region above horizontal cutoff (y < cutoff_y)."""
    h = image.shape[0]
    y = max(0, min(int(cutoff_y), h))
    return image[0:y, :].copy()


def process_video_sample(sample: dict, rotation_angle: float, flip_180: bool, cutoff_y: int):
    """Phase 2: batch process all video frames."""
    raise NotImplementedError("Video batch processing will be added in phase 2.")


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
