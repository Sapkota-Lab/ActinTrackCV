"""Orientation state, rectangular ROI, and coordinate transforms."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from actintrack_app.image_processing import apply_flip, rotate_image_and_mask


@dataclass
class RectROI:
    """Axis-aligned rectangle on the oriented reference frame (x, y, width, height)."""

    x: int
    y: int
    width: int
    height: int

    def as_dict(self) -> dict[str, int]:
        return {
            "x": int(self.x),
            "y": int(self.y),
            "width": int(self.width),
            "height": int(self.height),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RectROI:
        if "width" in data and "height" in data:
            return cls(
                int(data["x"]),
                int(data["y"]),
                int(data["width"]),
                int(data["height"]),
            )
        x0 = int(data.get("x0", data.get("x", 0)))
        y0 = int(data.get("y0", data.get("y", 0)))
        x1 = int(data.get("x1", x0 + int(data.get("width", 0))))
        y1 = int(data.get("y1", y0 + int(data.get("height", 0))))
        return cls(x0, y0, max(1, x1 - x0), max(1, y1 - y0))

    @classmethod
    def from_xyxy(cls, x0: int, y0: int, x1: int, y1: int) -> RectROI:
        return cls(
            min(x0, x1),
            min(y0, y1),
            max(1, abs(x1 - x0)),
            max(1, abs(y1 - y0)),
        )

    @property
    def x1(self) -> int:
        return self.x + self.width

    @property
    def y1(self) -> int:
        return self.y + self.height

    def clamp(self, image_width: int, image_height: int) -> RectROI:
        w, h = int(image_width), int(image_height)
        x = max(0, min(self.x, w - 1))
        y = max(0, min(self.y, h - 1))
        width = max(1, min(self.width, w - x))
        height = max(1, min(self.height, h - y))
        return RectROI(x, y, width, height)

    def crop_slice(self) -> tuple[slice, slice]:
        return slice(self.y, self.y + self.height), slice(self.x, self.x + self.width)


@dataclass
class OrientationState:
    rotation_angle_degrees: float = 0.0
    flipped_180: bool = False
    manual_rotation_steps: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rotation_angle_degrees": float(self.rotation_angle_degrees),
            "flipped_180": bool(self.flipped_180),
            "manual_rotation_steps": list(self.manual_rotation_steps),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OrientationState:
        steps = data.get("manual_rotation_steps") or []
        if isinstance(steps, str):
            steps = [steps] if steps else []
        return cls(
            rotation_angle_degrees=float(data.get("rotation_angle_degrees") or 0.0),
            flipped_180=bool(data.get("flipped_180")),
            manual_rotation_steps=[str(s) for s in steps],
        )

    def add_step(self, step: str) -> None:
        self.manual_rotation_steps.append(step)


def apply_orientation(image: np.ndarray, state: OrientationState) -> np.ndarray:
    """Apply cumulative rotation then optional 180° flip."""
    out = image
    angle = float(state.rotation_angle_degrees)
    if abs(angle) > 1e-6:
        out, _ = rotate_image_and_mask(out, None, angle)
    if state.flipped_180:
        out = apply_flip(out, True)
    return out


def crop_rect_roi(image: np.ndarray, roi: RectROI) -> np.ndarray:
    roi = roi.clamp(image.shape[1], image.shape[0])
    sy, sx = roi.crop_slice()
    return image[sy, sx].copy()


def scale_roi_to_frame(
    roi: RectROI,
    source_width: int,
    source_height: int,
    target_width: int,
    target_height: int,
    method: str,
) -> RectROI:
    """Map ROI from source oriented frame to target oriented frame dimensions."""
    if source_width == target_width and source_height == target_height:
        return roi.clamp(target_width, target_height)

    if method == "same_coordinates":
        return roi.clamp(target_width, target_height)

    sx = target_width / max(1, source_width)
    sy = target_height / max(1, source_height)
    scaled = RectROI(
        int(round(roi.x * sx)),
        int(round(roi.y * sy)),
        max(1, int(round(roi.width * sx))),
        max(1, int(round(roi.height * sy))),
    )
    return scaled.clamp(target_width, target_height)


def tracking_crop_to_rect(crop: Any) -> RectROI:
    """Convert legacy TrackingCrop to RectROI."""
    return RectROI.from_xyxy(int(crop.x0), int(crop.y0), int(crop.x1), int(crop.y1))
