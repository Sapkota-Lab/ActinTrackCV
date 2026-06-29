"""Propagate orientation + ROI within samples and breeds (legacy batch/group storage)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from actintrack_app.annotation_schema import build_sample_annotation
from actintrack_app.batch_manager import sanitize_batch_name
from actintrack_app.metadata import load_crop_metadata, load_samples_csv
from actintrack_app.orientation import (
    OrientationState,
    RectROI,
    apply_orientation,
    scale_roi_to_frame,
)
from actintrack_app.utils import (
    CROP_METADATA_JSON,
    METADATA_DIR,
    PROTECTED_ANNOTATION_STATUSES,
    SAMPLES_CSV,
    SCOPE_ALL_IN_GROUP,
    SCOPE_SAME_BATCH,
    SCOPE_SELECTED,
    SCOPE_UNPROCESSED_IN_BATCH,
    STATUS_ROI_PROPAGATED,
    UNPROCESSED_STATUSES,
)
from actintrack_app.video_processing import load_media_frame


def resolve_propagation_targets(
    root: Path,
    source_sample_id: str,
    scope: str,
    selected_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Resolve targets for annotation propagation.

    Default scope is same_biological_batch (other files from the same sample/line).
    """
    root = Path(root).resolve()
    df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)
    source_rows = df[df["sample_id"].astype(str) == str(source_sample_id)]
    if source_rows.empty:
        return []
    source = source_rows.iloc[0]
    source_group = str(source["group"])
    source_batch = sanitize_batch_name(str(source.get("batch_name", "")))

    def exclude_source(mask: pd.Series) -> pd.Series:
        return mask & (df["sample_id"].astype(str) != str(source_sample_id))

    if scope == SCOPE_SELECTED and selected_ids:
        mask = df["sample_id"].astype(str).isin([str(s) for s in selected_ids])
        return [row.to_dict() for _, row in df[exclude_source(mask)].iterrows()]

    if scope == SCOPE_UNPROCESSED_IN_BATCH:
        mask = (df["group"] == source_group) & (
            df["batch_name"].astype(str).apply(sanitize_batch_name) == source_batch
        ) & (df["processing_status"].astype(str).isin(UNPROCESSED_STATUSES))
        return [row.to_dict() for _, row in df[exclude_source(mask)].iterrows()]

    if scope == SCOPE_SAME_BATCH:
        mask = (df["group"] == source_group) & (
            df["batch_name"].astype(str).apply(sanitize_batch_name) == source_batch
        )
        return [row.to_dict() for _, row in df[exclude_source(mask)].iterrows()]

    if scope == SCOPE_ALL_IN_GROUP:
        mask = df["group"] == source_group
        return [row.to_dict() for _, row in df[exclude_source(mask)].iterrows()]

    return []


def annotation_is_protected(status: str) -> bool:
    return str(status) in PROTECTED_ANNOTATION_STATUSES


def propagate_annotation(
    root: Path,
    source_annotation: dict[str, Any],
    target_sample: dict[str, Any],
    scaling_method: str = "proportional_scaled",
) -> dict[str, Any]:
    """Build propagated annotation for one target sample."""
    root = Path(root).resolve()
    source_id = str(source_annotation["sample_id"])
    target_id = str(target_sample["sample_id"])
    stored = str(target_sample["stored_path"])
    path = root / stored

    orientation = OrientationState.from_dict(source_annotation)
    src_orient = source_annotation.get("oriented_dimensions") or source_annotation.get(
        "original_dimensions", {}
    )
    src_w = int(src_orient.get("width", 0))
    src_h = int(src_orient.get("height", 0))
    roi = RectROI.from_dict(source_annotation["rectangle_roi"])

    ref_idx = int(source_annotation.get("reference_frame_index", 0))
    frame, _, _ = load_media_frame(path, ref_idx)
    tgt_h, tgt_w = frame.shape[:2]
    tgt_orient = apply_orientation_dims(tgt_w, tgt_h, orientation)

    scaled_roi = scale_roi_to_frame(
        roi, src_w, src_h, tgt_orient["width"], tgt_orient["height"], scaling_method
    )
    from actintrack_app.roi_workflow import oriented_roi_to_original

    tgt_oriented = apply_orientation(frame, orientation)
    oh, ow = tgt_oriented.shape[:2]
    roi_orig = oriented_roi_to_original(
        scaled_roi.clamp(ow, oh),
        orig_w=tgt_w,
        orig_h=tgt_h,
        oriented_w=ow,
        oriented_h=oh,
        state=orientation,
    )

    source_group = str(source_annotation.get("group", target_sample.get("group", "")))
    source_batch = sanitize_batch_name(
        str(source_annotation.get("batch_name", ""))
    )
    target_batch = sanitize_batch_name(str(target_sample.get("batch_name", "")))

    return build_sample_annotation(
        sample_id=target_id,
        group=str(target_sample["group"]),
        batch_name=target_batch,
        batch_id=str(target_sample.get("batch_id", "")),
        original_file=str(target_sample["original_filename"]),
        stored_raw_path=stored,
        reference_frame_index=ref_idx,
        orientation=orientation,
        roi=scaled_roi.clamp(ow, oh),
        roi_original=roi_orig,
        original_dimensions={"width": tgt_w, "height": tgt_h},
        oriented_dimensions=tgt_orient,
        notes=str(source_annotation.get("notes", "")),
        annotation_source="propagated",
        roi_method=str(source_annotation.get("roi_method", "propagated_rectangle")),
        segmentation_method=source_annotation.get("segmentation_method"),
        segmentation_parameters=source_annotation.get("segmentation_parameters"),
        status=STATUS_ROI_PROPAGATED,
        requires_review=True,
        review_status="pending",
        propagated_from={
            "annotation_source": "propagated",
            "source_sample_id": source_id,
            "source_group": source_group,
            "source_batch": source_batch,
            "target_batch": target_batch,
            "roi_scaling_method": scaling_method,
            "requires_review": True,
            "review_status": "pending",
        },
    )


def apply_orientation_dims(width: int, height: int, orientation: OrientationState) -> dict[str, int]:
    """Compute oriented frame size without loading full image."""
    import numpy as np

    from actintrack_app.image_processing import rotate_image_and_mask

    dummy = np.zeros((height, width, 3), dtype=np.uint8)
    oriented = dummy
    angle = float(orientation.rotation_angle_degrees)
    if abs(angle) > 1e-6:
        oriented, _ = rotate_image_and_mask(oriented, None, angle)
    if orientation.flipped_180:
        import cv2

        oriented = cv2.rotate(oriented, cv2.ROTATE_180)
    h, w = oriented.shape[:2]
    return {"width": int(w), "height": int(h)}


def save_propagated_annotations(
    root: Path,
    annotations: list[dict[str, Any]],
) -> int:
    from actintrack_app.metadata import save_sample_crop_annotation

    root = Path(root).resolve()
    crop_path = root / METADATA_DIR / CROP_METADATA_JSON
    for ann in annotations:
        save_sample_crop_annotation(crop_path, str(ann["sample_id"]), ann)
    return len(annotations)


def existing_annotation_status(root: Path, sample_id: str) -> str | None:
    data = load_crop_metadata(root / METADATA_DIR / CROP_METADATA_JSON)
    ann = data.get("samples", {}).get(str(sample_id))
    if not ann:
        return None
    return str(ann.get("status", ""))
