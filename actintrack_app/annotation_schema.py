"""Build and merge Phase 2 sample annotations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from actintrack_app.orientation import OrientationState, RectROI
from actintrack_app.roi_workflow import (
    ORIENTED_ROI_COORDINATE_SPACE,
    original_roi_to_oriented,
    roi_from_original_dict,
    roi_oriented_as_dict,
    roi_original_as_dict,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_sample_annotation(
    *,
    sample_id: str,
    group: str,
    batch_name: str = "",
    batch_id: str = "",
    original_file: str,
    stored_raw_path: str,
    reference_frame_index: int,
    orientation: OrientationState,
    roi: RectROI,
    roi_original: RectROI | None = None,
    original_dimensions: dict[str, int],
    oriented_dimensions: dict[str, int],
    notes: str = "",
    annotation_source: str = "manual",
    suggestion_method: str | None = None,
    roi_method: str = "manual_rectangle",
    segmentation_method: str | None = None,
    segmentation_parameters: dict[str, Any] | None = None,
    cell_mask_path: str | None = None,
    propagated_from: dict[str, Any] | None = None,
    processed_output_path: str | None = None,
    cropped_dimensions: dict[str, int] | None = None,
    status: str = "roi_marked",
    requires_review: bool = False,
    review_status: str = "approved",
) -> dict[str, Any]:
    """Structured annotation for training and export."""
    ann: dict[str, Any] = {
        "sample_id": str(sample_id),
        "group": str(group),
        "batch_name": str(batch_name),
        "batch_id": str(batch_id),
        "original_file": str(original_file),
        "stored_raw_path": str(stored_raw_path),
        "reference_frame_index": int(reference_frame_index),
        "rotation_angle_degrees": float(orientation.rotation_angle_degrees),
        "flipped_180": bool(orientation.flipped_180),
        "manual_rotation_steps": list(orientation.manual_rotation_steps),
        "rectangle_roi": roi_oriented_as_dict(roi),
        "roi_method": roi_method,
        **(
            roi_original_as_dict(roi_original)
            if roi_original is not None
            else {}
        ),
        "annotation_source": annotation_source,
        "roi_coordinate_space": ORIENTED_ROI_COORDINATE_SPACE,
        "original_dimensions": original_dimensions,
        "oriented_dimensions": oriented_dimensions,
        "segmentation_method": segmentation_method or "not_applied",
        "segmentation_parameters": segmentation_parameters or {},
        "processing_date": _utc_now_iso(),
        "status": status,
        "requires_review": requires_review,
        "review_status": review_status,
        "notes": notes,
    }
    if suggestion_method:
        ann["suggestion_method"] = suggestion_method
    if cell_mask_path:
        ann["cell_mask_path"] = cell_mask_path
    if propagated_from:
        ann["propagation"] = propagated_from
    if processed_output_path:
        ann["processed_output_path"] = processed_output_path
    if cropped_dimensions:
        ann["cropped_dimensions"] = cropped_dimensions
    return ann


def merge_processed_into_annotation(
    annotation: dict[str, Any],
    process_result: dict[str, Any],
) -> dict[str, Any]:
    """Update annotation after successful export."""
    out = dict(annotation)
    out["processed_output_path"] = process_result.get("processed_output_path")
    out["cropped_dimensions"] = process_result.get("cropped_dimensions")
    out["frame_count_exported"] = process_result.get("frame_count")
    out["status"] = "processed"
    out["requires_review"] = False
    out["processing_date"] = _utc_now_iso()
    return out


def annotation_from_legacy(ann: dict[str, Any]) -> tuple[OrientationState, RectROI | None]:
    """Load orientation and ROI from Phase 1 or Phase 2 metadata."""
    orientation = OrientationState.from_dict(ann)
    # Prefer oriented-space rectangle_roi when present (matches the on-canvas box at save).
    # Reconstructing from roi_original via corner mapping inflates the box after rotation.
    if ann.get("rectangle_roi"):
        return orientation, RectROI.from_dict(ann["rectangle_roi"])
    w = int(
        ann.get("original_dimensions", {}).get("width", 0)
        or ann.get("original_frame_width", 0)
        or ann.get("oriented_dimensions", {}).get("width", 0)
    )
    h = int(
        ann.get("original_dimensions", {}).get("height", 0)
        or ann.get("original_frame_height", 0)
        or ann.get("oriented_dimensions", {}).get("height", 0)
    )
    roi_orig = roi_from_original_dict(ann)
    if roi_orig is not None and w and h:
        return orientation, original_roi_to_oriented(
            roi_orig, orig_w=w, orig_h=h, state=orientation
        )

    if ann.get("analysis_region_coords"):
        coords = ann["analysis_region_coords"]
        return orientation, RectROI.from_xyxy(
            int(coords.get("x0", 0)),
            int(coords.get("y0", 0)),
            int(coords.get("x1", w)),
            int(coords.get("y1", ann.get("cutoff_y", h))),
        )
    if ann.get("cutoff_y") is not None and w and h:
        y = int(ann["cutoff_y"])
        tracking = ann.get("tracking_roi") or {}
        x0 = int(tracking.get("x0", 0))
        x1 = int(tracking.get("x1", w))
        return orientation, RectROI(x0, 0, max(1, x1 - x0), max(1, y))
    return orientation, None
