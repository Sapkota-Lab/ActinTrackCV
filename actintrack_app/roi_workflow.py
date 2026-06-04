"""ROI validation, coordinate transforms, and crop/export orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

from actintrack_app.export_naming import (
    processed_image_path,
    processed_sample_metadata_path,
    processed_video_path,
    roi_and_crop_preview_paths,
)
from actintrack_app.image_processing import draw_rect_roi_preview
from actintrack_app.orientation import (
    OrientationState,
    RectROI,
    apply_orientation,
    crop_rect_roi,
)
from actintrack_app.project_manager import get_processed_batch_dir
from actintrack_app.sample_processor import process_sample_to_disk, write_processed_metadata
from actintrack_app.utils import (
    RAW_MICROSCOPY_EXTENSIONS,
    STATUS_PROCESSED,
    STATUS_ROI_APPROVED,
    VIDEO_EXTENSIONS,
)
from actintrack_app.video_processing import MediaLoadError, load_media_frame

ROI_COORDINATE_SPACE = "original_frame_pixels"
MIN_ROI_WIDTH = 8
MIN_ROI_HEIGHT = 8
MIN_ROI_AREA_FRACTION = 0.001


@dataclass
class RoiValidationResult:
    ok: bool
    message: str
    roi_oriented: RectROI | None = None
    roi_original: RectROI | None = None


def _rotation_matrix(orig_w: int, orig_h: int, angle_deg: float) -> tuple[np.ndarray, int, int]:
    center = (orig_w / 2.0, orig_h / 2.0)
    matrix = cv2.getRotationMatrix2D(center, float(angle_deg), 1.0)
    cos = abs(matrix[0, 0])
    sin = abs(matrix[0, 1])
    new_w = int(orig_h * sin + orig_w * cos)
    new_h = int(orig_h * cos + orig_w * sin)
    matrix[0, 2] += (new_w / 2.0) - center[0]
    matrix[1, 2] += (new_h / 2.0) - center[1]
    return matrix, new_w, new_h


def oriented_point_to_original(
    x: float,
    y: float,
    *,
    orig_w: int,
    orig_h: int,
    oriented_w: int,
    oriented_h: int,
    state: OrientationState,
) -> tuple[int, int]:
    """Map a point from oriented reference pixels to original frame pixels."""
    angle = float(state.rotation_angle_degrees)
    matrix, rot_w, rot_h = _rotation_matrix(orig_w, orig_h, angle)
    xo, yo = float(x), float(y)
    if state.flipped_180:
        xo = rot_w - 1 - xo
        yo = rot_h - 1 - yo
    inv = cv2.invertAffineTransform(matrix)
    pts = np.array([[[xo, yo]]], dtype=np.float32)
    out = cv2.transform(pts, inv)
    ox = int(round(out[0, 0, 0]))
    oy = int(round(out[0, 0, 1]))
    return max(0, min(ox, orig_w - 1)), max(0, min(oy, orig_h - 1))


def original_point_to_oriented(
    x: float,
    y: float,
    *,
    orig_w: int,
    orig_h: int,
    state: OrientationState,
) -> tuple[int, int]:
    """Map a point from original frame pixels to oriented reference pixels."""
    angle = float(state.rotation_angle_degrees)
    matrix, rot_w, rot_h = _rotation_matrix(orig_w, orig_h, angle)
    pts = np.array([[[float(x), float(y)]]], dtype=np.float32)
    out = cv2.transform(pts, matrix)
    xo = int(round(out[0, 0, 0]))
    yo = int(round(out[0, 0, 1]))
    if state.flipped_180:
        xo = rot_w - 1 - xo
        yo = rot_h - 1 - yo
    return xo, yo


def oriented_roi_to_original(
    roi: RectROI,
    *,
    orig_w: int,
    orig_h: int,
    oriented_w: int,
    oriented_h: int,
    state: OrientationState,
) -> RectROI:
    corners = [
        (roi.x, roi.y),
        (roi.x1, roi.y),
        (roi.x1, roi.y1),
        (roi.x, roi.y1),
    ]
    mapped = [
        oriented_point_to_original(
            cx,
            cy,
            orig_w=orig_w,
            orig_h=orig_h,
            oriented_w=oriented_w,
            oriented_h=oriented_h,
            state=state,
        )
        for cx, cy in corners
    ]
    xs = [p[0] for p in mapped]
    ys = [p[1] for p in mapped]
    return RectROI.from_xyxy(min(xs), min(ys), max(xs), max(ys)).clamp(orig_w, orig_h)


def original_roi_to_oriented(
    roi: RectROI,
    *,
    orig_w: int,
    orig_h: int,
    state: OrientationState,
) -> RectROI:
    oriented = apply_orientation(
        np.zeros((orig_h, orig_w, 3), dtype=np.uint8), state
    )
    oh, ow = oriented.shape[:2]
    corners = [
        (roi.x, roi.y),
        (roi.x1, roi.y),
        (roi.x1, roi.y1),
        (roi.x, roi.y1),
    ]
    mapped = [
        original_point_to_oriented(cx, cy, orig_w=orig_w, orig_h=orig_h, state=state)
        for cx, cy in corners
    ]
    xs = [p[0] for p in mapped]
    ys = [p[1] for p in mapped]
    return RectROI.from_xyxy(min(xs), min(ys), max(xs), max(ys)).clamp(ow, oh)


def roi_original_as_dict(roi: RectROI) -> dict[str, Any]:
    return {
        "roi_x": int(roi.x),
        "roi_y": int(roi.y),
        "roi_width": int(roi.width),
        "roi_height": int(roi.height),
        "roi_coordinate_space": ROI_COORDINATE_SPACE,
    }


def roi_from_original_dict(data: dict[str, Any]) -> RectROI | None:
    if data.get("roi_coordinate_space") != ROI_COORDINATE_SPACE:
        if "roi_x" not in data:
            return None
    try:
        return RectROI(
            int(data["roi_x"]),
            int(data["roi_y"]),
            int(data["roi_width"]),
            int(data["roi_height"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def validate_roi(
    roi: RectROI | None,
    *,
    frame_width: int,
    frame_height: int,
    label: str = "ROI",
) -> RoiValidationResult:
    if roi is None:
        return RoiValidationResult(False, "No ROI selected. Draw a rectangle on the preview.")
    w, h = int(frame_width), int(frame_height)
    if w <= 0 or h <= 0:
        return RoiValidationResult(False, "No readable frame is loaded.")
    r = roi.clamp(w, h)
    if r.width < MIN_ROI_WIDTH or r.height < MIN_ROI_HEIGHT:
        return RoiValidationResult(
            False,
            f"{label} is too small (minimum {MIN_ROI_WIDTH}×{MIN_ROI_HEIGHT} pixels).",
        )
    if r.x < 0 or r.y < 0 or r.x1 > w or r.y1 > h:
        return RoiValidationResult(False, f"{label} extends outside the image bounds.")
    area_frac = (r.width * r.height) / max(1, w * h)
    if area_frac < MIN_ROI_AREA_FRACTION:
        return RoiValidationResult(
            False,
            f"{label} covers too little of the frame ({area_frac:.2%}). Enlarge the selection.",
        )
    if r.x != roi.x or r.y != roi.y or r.width != roi.width or r.height != roi.height:
        return RoiValidationResult(
            False,
            f"{label} is mostly outside the frame. Adjust the rectangle.",
            roi_oriented=r,
        )
    return RoiValidationResult(True, "", roi_oriented=r)


def validate_roi_for_sample(
    roi_oriented: RectROI | None,
    *,
    base_frame: np.ndarray,
    orientation: OrientationState,
) -> RoiValidationResult:
    oriented = apply_orientation(base_frame, orientation)
    oh, ow = oriented.shape[:2]
    check = validate_roi(roi_oriented, frame_width=ow, frame_height=oh)
    if not check.ok:
        return check
    bh, bw = base_frame.shape[:2]
    roi_orig = oriented_roi_to_original(
        check.roi_oriented,  # type: ignore[arg-type]
        orig_w=bw,
        orig_h=bh,
        oriented_w=ow,
        oriented_h=oh,
        state=orientation,
    )
    orig_check = validate_roi(roi_orig, frame_width=bw, frame_height=bh, label="ROI (original)")
    if not orig_check.ok:
        return orig_check
    return RoiValidationResult(
        True,
        "",
        roi_oriented=check.roi_oriented,
        roi_original=roi_orig,
    )


def crop_image_to_roi(image: np.ndarray, roi: RectROI) -> np.ndarray:
    return crop_rect_roi(image, roi)


def save_roi_preview(
    reference_frame: np.ndarray,
    roi_original: RectROI,
    path: Path,
) -> None:
    vis = draw_rect_roi_preview(reference_frame, roi_original.clamp(
        reference_frame.shape[1], reference_frame.shape[0]
    ))
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), vis)


def save_crop_preview(cropped: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), cropped)


def preview_cropped_reference(
    source_path: Path,
    orientation: OrientationState,
    roi_oriented: RectROI,
    reference_frame_index: int,
) -> np.ndarray:
    ref_frame, _, _ = load_media_frame(source_path, reference_frame_index)
    oriented = apply_orientation(ref_frame, orientation)
    roi = roi_oriented.clamp(oriented.shape[1], oriented.shape[0])
    return crop_rect_roi(oriented, roi)


def build_export_metadata(
    *,
    sample_row: dict[str, Any],
    annotation: dict[str, Any],
    roi_original: RectROI,
    roi_oriented: RectROI,
    process_result: dict[str, Any],
    input_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    orig = annotation.get("original_dimensions", process_result.get("original_dimensions", {}))
    cropped = process_result.get("cropped_dimensions", {})
    ow = int(orig.get("width", 0))
    oh = int(orig.get("height", 0))
    meta = {
        "sample_id": str(sample_row.get("sample_id", annotation.get("sample_id", ""))),
        "group": str(sample_row.get("group", annotation.get("group", ""))),
        "batch_number": int(sample_row.get("batch_number", 0) or 0),
        "batch_name": str(sample_row.get("batch_name", annotation.get("batch_name", ""))),
        "input_file": str(input_path),
        "output_file": str(output_path),
        "file_type": str(sample_row.get("file_type", "")),
        "is_video": str(sample_row.get("is_video", "")).lower() == "true",
        "reference_frame_index": int(annotation.get("reference_frame_index", 0)),
        **roi_original_as_dict(roi_original),
        "rectangle_roi_oriented": roi_oriented.as_dict(),
        "original_frame_width": ow,
        "original_frame_height": oh,
        "cropped_width": int(cropped.get("width", 0)),
        "cropped_height": int(cropped.get("height", 0)),
        "auto_export_name": str(sample_row.get("auto_export_name", "")),
        "custom_export_name": str(sample_row.get("custom_export_name", "")) or None,
        "final_export_name": str(sample_row.get("final_export_name", "")),
        "annotation_source": str(annotation.get("annotation_source", "manual")),
        "review_status": str(annotation.get("review_status", "approved")),
        "processing_status": STATUS_PROCESSED,
        "processing_date": process_result.get("processing_date"),
        "notes": str(annotation.get("notes", sample_row.get("notes", ""))),
        "frame_count_exported": process_result.get("frame_count"),
        "rotation_angle_degrees": float(annotation.get("rotation_angle_degrees", 0)),
        "flipped_180": bool(annotation.get("flipped_180", False)),
    }
    if meta["custom_export_name"] == "":
        meta["custom_export_name"] = None
    return meta


def list_output_paths_for_export(
    root: Path,
    group: str,
    batch_name: str,
    final_export_name: str,
    is_video: bool,
) -> list[Path]:
    out_dir = get_processed_batch_dir(root, group, batch_name)
    paths = []
    if is_video:
        paths.append(processed_video_path(out_dir, final_export_name))
    else:
        paths.append(processed_image_path(out_dir, final_export_name))
    roi_p, crop_p = roi_and_crop_preview_paths(out_dir, final_export_name)
    paths.extend([roi_p, crop_p, processed_sample_metadata_path(out_dir, final_export_name)])
    return paths


def is_wip_sample_path(path: Path) -> bool:
    ext = path.suffix.lower()
    if ext in RAW_MICROSCOPY_EXTENSIONS:
        return True
    if ext in {".tif", ".tiff"}:
        try:
            from actintrack_app.video_processing import get_tiff_page_count

            return get_tiff_page_count(path) > 1
        except Exception:
            return True
    return False


def resolve_oriented_roi_from_annotation(
    ann: dict[str, Any],
    base_frame: np.ndarray,
    orientation: OrientationState,
) -> RectROI | None:
    if ann.get("rectangle_roi"):
        return RectROI.from_dict(ann["rectangle_roi"])
    bh, bw = base_frame.shape[:2]
    roi_orig = roi_from_original_dict(ann)
    if roi_orig is not None:
        return original_roi_to_oriented(
            roi_orig, orig_w=bw, orig_h=bh, state=orientation
        )
    return None


def process_sample_roi(
    *,
    root: Path,
    sample_row: dict[str, Any],
    annotation: dict[str, Any],
    source_path: Path,
    orientation: OrientationState,
    roi_oriented: RectROI,
    roi_original: RectROI,
    overwrite: bool = False,
    export_frames: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Crop/export one sample and write previews + metadata."""
    root = Path(root).resolve()
    sid = str(sample_row["sample_id"])
    group = str(sample_row["group"])
    batch_name = str(sample_row.get("batch_name", ""))
    try:
        batch_number = int(sample_row.get("batch_number", 1) or 1)
    except ValueError:
        batch_number = 1
    final_name = str(sample_row.get("final_export_name", "")).strip()
    if not final_name:
        raise ValueError(f"Missing export name for sample {sid}")

    is_video = str(sample_row.get("is_video", "")).lower() == "true" or (
        source_path.suffix.lower() in VIDEO_EXTENSIONS
    )
    if is_wip_sample_path(source_path):
        raise MediaLoadError(
            "Raw or 3D microscopy format is not supported in the 2D crop workflow."
        )

    out_paths = list_output_paths_for_export(
        root, group, batch_name, final_name, is_video
    )
    existing = [p for p in out_paths if p.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            f"Output already exists: {existing[0].name}. Confirm overwrite to replace."
        )

    result = process_sample_to_disk(
        root=root,
        sample_id=sid,
        group=group,
        batch_name=batch_name,
        batch_number=batch_number,
        final_export_name=final_name,
        source_path=source_path,
        orientation=orientation,
        roi=roi_oriented,
        reference_frame_index=int(annotation.get("reference_frame_index", 0)),
        export_frames=export_frames and not is_video,
        is_video=is_video,
        roi_original=roi_original,
        progress_callback=progress_callback,
    )

    export_meta = build_export_metadata(
        sample_row=sample_row,
        annotation=annotation,
        roi_original=roi_original,
        roi_oriented=roi_oriented,
        process_result=result,
        input_path=source_path,
        output_path=Path(result["output_file"]),
    )
    result["export_metadata"] = export_meta
    result["metadata_file"] = str(
        write_processed_metadata(
            Path(result["output_dir"]),
            export_meta,
            final_export_name=final_name,
        )
    )
    return result


@dataclass
class BatchProcessReport:
    processed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


def process_batch_approved_rois(
    *,
    root: Path,
    group: str,
    batch_name: str,
    overwrite: bool = False,
    export_frames: bool = False,
) -> tuple[list[str], list[str], BatchProcessReport]:
    """
    Return (approved_ids, skipped_ids, report) for pre-export summary.
    Only processes samples with roi_approved status and valid saved ROI.
    """
    import pandas as pd

    from actintrack_app.batch_manager import sanitize_batch_name
    from actintrack_app.metadata import get_sample_annotation
    from actintrack_app.utils import METADATA_DIR, SAMPLES_CSV

    root = Path(root).resolve()
    df = pd.read_csv(root / METADATA_DIR / SAMPLES_CSV, dtype=str, keep_default_na=False)
    safe = sanitize_batch_name(batch_name)
    sub = df[
        (df["group"] == group)
        & (df["batch_name"].astype(str).apply(sanitize_batch_name) == safe)
    ]
    approved_ids: list[str] = []
    skipped_ids: list[str] = []
    for _, row in sub.iterrows():
        sid = str(row["sample_id"])
        status = str(row.get("processing_status", ""))
        if status != STATUS_ROI_APPROVED:
            skipped_ids.append(sid)
            continue
        ann = get_sample_annotation(root, sid)
        if not ann or not (
            ann.get("rectangle_roi") or roi_from_original_dict(ann) is not None
        ):
            skipped_ids.append(sid)
            continue
        approved_ids.append(sid)

    report = BatchProcessReport()
    for sid in approved_ids:
        row = sub[sub["sample_id"] == sid].iloc[0].to_dict()
        path = root / str(row["stored_path"])
        if not path.is_file():
            report.skipped += 1
            report.errors.append(f"{sid}: file not found")
            continue
        if is_wip_sample_path(path):
            report.skipped += 1
            report.errors.append(f"{sid}: WIP/unsupported format")
            continue
        ann = get_sample_annotation(root, sid)
        try:
            orientation = OrientationState.from_dict(ann)
            ref_idx = int(ann.get("reference_frame_index", 0))
            ref_frame, _, _ = load_media_frame(path, ref_idx)
            roi_oriented = resolve_oriented_roi_from_annotation(ann, ref_frame, orientation)
            if roi_oriented is None:
                report.skipped += 1
                report.errors.append(f"{sid}: no valid ROI")
                continue
            bh, bw = ref_frame.shape[:2]
            oriented = apply_orientation(ref_frame, orientation)
            oh, ow = oriented.shape[:2]
            roi_orig = oriented_roi_to_original(
                roi_oriented.clamp(ow, oh),
                orig_w=bw,
                orig_h=bh,
                oriented_w=ow,
                oriented_h=oh,
                state=orientation,
            )
            from actintrack_app.annotation_schema import merge_processed_into_annotation
            from actintrack_app.metadata import (
                save_sample_crop_annotation,
                update_samples_csv,
            )
            from actintrack_app.utils import CROP_METADATA_JSON

            result = process_sample_roi(
                root=root,
                sample_row=row,
                annotation=ann,
                source_path=path,
                orientation=orientation,
                roi_oriented=roi_oriented.clamp(ow, oh),
                roi_original=roi_orig,
                overwrite=overwrite,
                export_frames=export_frames,
            )
            ann = merge_processed_into_annotation(ann, result)
            ann.update(result.get("export_metadata", {}))
            ann["review_status"] = "approved"
            save_sample_crop_annotation(root / METADATA_DIR / CROP_METADATA_JSON, sid, ann)
            update_samples_csv(
                root / METADATA_DIR / SAMPLES_CSV,
                {"sample_id": sid, "processing_status": STATUS_PROCESSED},
            )
            report.processed += 1
        except Exception as e:
            report.failed += 1
            report.errors.append(f"{sid}: {e}")

    return approved_ids, skipped_ids, report
