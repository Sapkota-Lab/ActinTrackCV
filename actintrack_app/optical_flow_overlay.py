"""Optical-flow visualization overlay and QC formatting for cropped ROI preview."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import cv2
import numpy as np

from actintrack_app.optical_flow_motion_index import (
    OpticalFlowResult,
    OpticalFlowSettings,
    compute_dense_flow_pair,
    is_optical_flow_result_stale,
)


@dataclass(frozen=True)
class OpticalFlowVisualizationSettings:
    arrow_spacing_px: int = 8
    arrow_scale: float = 0.8

    def __post_init__(self) -> None:
        if self.arrow_spacing_px < 4:
            raise ValueError("arrow_spacing_px must be at least 4.")
        if self.arrow_scale <= 0:
            raise ValueError("arrow_scale must be positive.")


@dataclass(frozen=True)
class FlowArrow:
    x: int
    y: int
    dx: float
    dy: float


@dataclass
class OpticalFlowFlowCache:
    sample_id: str
    fingerprint: str
    pair_flows: list[np.ndarray]
    pair_masks: list[np.ndarray]

    def pair_count(self) -> int:
        return len(self.pair_flows)


def resolve_frame_pair_index(frame_index: int, frame_count: int) -> Optional[int]:
    """Map displayed frame index to a stored frame-pair index."""
    if frame_count < 2:
        return None
    max_pair = frame_count - 2
    if frame_index < frame_count - 1:
        return max(0, min(frame_index, max_pair))
    if frame_count >= 2:
        return max_pair
    return None


def build_flow_cache(
    frames: Sequence[np.ndarray],
    settings: OpticalFlowSettings,
    *,
    sample_id: str,
    fingerprint: str,
) -> OpticalFlowFlowCache:
    """Compute and cache dense flow fields for all consecutive frame pairs."""
    pair_flows: list[np.ndarray] = []
    pair_masks: list[np.ndarray] = []
    for i in range(len(frames) - 1):
        pair = compute_dense_flow_pair(
            frames[i], frames[i + 1], settings, frame_a=i, frame_b=i + 1
        )
        pair_flows.append(pair.flow)
        pair_masks.append(pair.mask)
    return OpticalFlowFlowCache(
        sample_id=sample_id,
        fingerprint=fingerprint,
        pair_flows=pair_flows,
        pair_masks=pair_masks,
    )


def sample_flow_vectors(
    flow: np.ndarray,
    mask: np.ndarray,
    viz: OpticalFlowVisualizationSettings,
) -> list[FlowArrow]:
    """Sample masked dense flow on a grid for arrow overlay."""
    if flow.size == 0 or not np.any(mask):
        return []

    h, w = mask.shape[:2]
    spacing = max(4, int(viz.arrow_spacing_px))
    arrows: list[FlowArrow] = []
    for y in range(spacing // 2, h, spacing):
        for x in range(spacing // 2, w, spacing):
            if not mask[y, x]:
                continue
            dx = float(flow[y, x, 0])
            dy = float(flow[y, x, 1])
            if abs(dx) < 1e-6 and abs(dy) < 1e-6:
                continue
            arrows.append(FlowArrow(x=x, y=y, dx=dx * viz.arrow_scale, dy=dy * viz.arrow_scale))
    return arrows


def get_flow_arrows_for_frame(
    cache: OpticalFlowFlowCache,
    frame_index: int,
    frame_count: int,
    viz: OpticalFlowVisualizationSettings,
) -> list[FlowArrow]:
    pair_idx = resolve_frame_pair_index(frame_index, frame_count)
    if pair_idx is None or pair_idx >= cache.pair_count():
        return []
    return sample_flow_vectors(
        cache.pair_flows[pair_idx],
        cache.pair_masks[pair_idx],
        viz,
    )


def render_optical_flow_overlay(
    frame: np.ndarray,
    arrows: Sequence[FlowArrow],
) -> np.ndarray:
    """Draw sampled flow arrows on a copy of the preview frame."""
    if frame.ndim == 2:
        display = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    else:
        display = frame.copy()

    color = (80, 220, 180)
    for arrow in arrows:
        x1, y1 = int(arrow.x), int(arrow.y)
        x2 = int(round(x1 + arrow.dx))
        y2 = int(round(y1 + arrow.dy))
        cv2.arrowedLine(display, (x1, y1), (x2, y2), color, 1, tipLength=0.35)
    return display


def _fmt_optional(value: Optional[float], *, places: int = 4) -> str:
    if value is None:
        return "—"
    return f"{value:.{places}f}"


def format_optical_flow_qc(result: Optional[OpticalFlowResult]) -> dict[str, str]:
    if result is None:
        return {
            "general_movement": "—",
            "downward_motion": "—",
            "net_y_velocity": "—",
            "directionality_ratio": "—",
            "valid_pixel_fraction": "—",
            "saturated_pixel_fraction": "—",
            "frame_pairs_used": "—",
        }
    return {
        "general_movement": _fmt_optional(result.optical_flow_general_movement_um_s),
        "downward_motion": _fmt_optional(result.optical_flow_downward_motion_um_s),
        "net_y_velocity": _fmt_optional(result.optical_flow_net_y_velocity_um_s),
        "directionality_ratio": _fmt_optional(result.optical_flow_directionality_ratio),
        "valid_pixel_fraction": _fmt_optional(result.optical_flow_valid_pixel_fraction),
        "saturated_pixel_fraction": _fmt_optional(
            result.optical_flow_saturated_pixel_fraction
        ),
        "frame_pairs_used": (
            str(result.frame_pair_count) if result.frame_pair_count else "—"
        ),
    }


def resolve_qc_status(
    *,
    result: Optional[OpticalFlowResult],
    is_computing: bool,
    is_stale_flag: bool,
    current_fingerprint: str = "",
) -> str:
    if is_computing:
        return "Computing…"
    if result is None:
        return "Not computed"
    if not result.has_valid_result:
        return "Error"
    if is_stale_flag:
        return "Stale"
    if current_fingerprint and is_optical_flow_result_stale(
        result.fingerprint, current_fingerprint
    ):
        return "Stale"
    return "Fresh"
