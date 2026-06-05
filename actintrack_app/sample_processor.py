"""Export oriented, ROI-cropped samples to processed/<group>/<batch_name>/."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

import cv2
import numpy as np

from actintrack_app.export_naming import (
    processed_image_path,
    processed_sample_metadata_path,
    processed_video_path,
    raw_debug_preview_path,
    roi_and_crop_preview_paths,
)
from actintrack_app.orientation import (
    OrientationState,
    RectROI,
    apply_orientation,
    crop_rect_roi,
)
from actintrack_app.project_manager import get_processed_batch_dir
from actintrack_app.image_processing import draw_rect_roi_preview
from actintrack_app.utils import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, relative_to_root
from actintrack_app.video_processing import (
    MediaLoadError,
    get_tiff_page_count,
    get_video_frame_count,
    load_media_frame,
    load_tiff_page,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_video_fps(path: Path) -> float:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return 6.0
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        if fps > 0.5:
            return fps
    finally:
        cap.release()
    return 6.0


def iter_sample_frames(path: Path) -> Iterator[tuple[int, np.ndarray]]:
    """Yield (index, bgr_frame) for video, TIFF stack pages, or single image."""
    path = Path(path)
    ext = path.suffix.lower()

    if ext in VIDEO_EXTENSIONS:
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise MediaLoadError(f"Cannot open video: {path}")
        try:
            idx = 0
            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                yield idx, frame
                idx += 1
            if idx == 0:
                raise MediaLoadError(f"Video has no readable frames: {path}")
        finally:
            cap.release()
        return

    if ext in {".tif", ".tiff"}:
        total = get_tiff_page_count(path)
        for i in range(total):
            yield i, load_tiff_page(path, i)
        return

    if ext in IMAGE_EXTENSIONS:
        frame, _, _ = load_media_frame(path, 0)
        yield 0, frame
        return

    raise MediaLoadError(f"Unsupported file type: {ext}")


def transform_frame(
    frame: np.ndarray,
    orientation: OrientationState,
    roi: RectROI,
) -> np.ndarray:
    oriented = apply_orientation(frame, orientation)
    return crop_rect_roi(oriented, roi.clamp(oriented.shape[1], oriented.shape[0]))


def crop_video_to_roi(
    source_path: Path,
    output_path: Path,
    orientation: OrientationState,
    roi: RectROI,
    *,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[int, int, int, float]:
    """Crop every frame; returns (frame_count, cropped_w, cropped_h, fps)."""
    fps = get_video_fps(source_path)
    roi_oriented = roi
    video_writer: cv2.VideoWriter | None = None
    frame_count = 0
    cropped_w, cropped_h = 0, 0
    try:
        total_estimate = max(1, get_video_frame_count(source_path))
    except MediaLoadError:
        total_estimate = 1

    for idx, frame in iter_sample_frames(source_path):
        cropped = transform_frame(frame, orientation, roi_oriented)
        cropped_h, cropped_w = cropped.shape[:2]
        if video_writer is None:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            video_writer = cv2.VideoWriter(
                str(output_path),
                fourcc,
                fps,
                (cropped_w, cropped_h),
            )
            if not video_writer.isOpened():
                video_writer.release()
                raise MediaLoadError(
                    "Failed to create cropped video (codec mp4v). "
                    "Try a different output location or check disk permissions."
                )
        video_writer.write(cropped)
        frame_count += 1
        if progress_callback is not None:
            progress_callback(idx + 1, total_estimate)

    if video_writer is not None:
        video_writer.release()
    if frame_count == 0:
        raise MediaLoadError(f"Video has no readable frames: {source_path}")
    return frame_count, cropped_w, cropped_h, fps


def crop_image_to_roi_file(
    source_path: Path,
    output_path: Path,
    orientation: OrientationState,
    roi: RectROI,
    reference_frame_index: int = 0,
) -> tuple[int, int, int]:
    """Crop still image; returns (frame_count, cropped_w, cropped_h)."""
    frame, _, _ = load_media_frame(source_path, reference_frame_index)
    cropped = transform_frame(frame, orientation, roi)
    cropped_h, cropped_w = cropped.shape[:2]
    if not cv2.imwrite(str(output_path), cropped):
        raise MediaLoadError(f"Failed to write cropped image: {output_path}")
    return 1, cropped_w, cropped_h


def process_sample_to_disk(
    *,
    root: Path,
    sample_id: str,
    group: str,
    batch_name: str,
    batch_number: int,
    final_export_name: str,
    source_path: Path,
    orientation: OrientationState,
    roi: RectROI,
    reference_frame_index: int = 0,
    export_frames: bool = False,
    is_video: bool | None = None,
    roi_original: RectROI | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """
    Apply orientation + rectangular ROI and write flat outputs under
    processed/<group>/<batch_name>/ using final_export_name.
    """
    root = Path(root).resolve()
    out_dir = get_processed_batch_dir(root, group, batch_name)
    out_dir.mkdir(parents=True, exist_ok=True)

    ext = source_path.suffix.lower()
    if is_video is None:
        is_video = ext in VIDEO_EXTENSIONS

    ref_frame, _, _ = load_media_frame(source_path, reference_frame_index)
    oriented_ref = apply_orientation(ref_frame, orientation)
    roi_ref = roi.clamp(oriented_ref.shape[1], oriented_ref.shape[0])

    if roi_original is None:
        from actintrack_app.roi_workflow import oriented_roi_to_original

        bh, bw = ref_frame.shape[:2]
        oh, ow = oriented_ref.shape[:2]
        roi_original = oriented_roi_to_original(
            roi_ref, orig_w=bw, orig_h=bh, oriented_w=ow, oriented_h=oh, state=orientation
        )

    roi_preview_path, crop_preview_path = roi_and_crop_preview_paths(
        out_dir, final_export_name
    )
    debug_raw_path = raw_debug_preview_path(out_dir, final_export_name)
    roi_vis = draw_rect_roi_preview(
        oriented_ref, roi_ref.clamp(oriented_ref.shape[1], oriented_ref.shape[0])
    )
    cv2.imwrite(str(roi_preview_path), roi_vis)
    raw_vis = draw_rect_roi_preview(
        ref_frame,
        roi_original.clamp(ref_frame.shape[1], ref_frame.shape[0]),
    )
    cv2.imwrite(str(debug_raw_path), raw_vis)
    cropped_ref = crop_rect_roi(oriented_ref, roi_ref)
    cv2.imwrite(str(crop_preview_path), cropped_ref)

    output_file: Path
    frame_count = 0
    cropped_w, cropped_h = 0, 0
    video_fps = 0.0

    if is_video:
        output_file = processed_video_path(out_dir, final_export_name)
        frame_count, cropped_w, cropped_h, video_fps = crop_video_to_roi(
            source_path,
            output_file,
            orientation,
            roi_ref,
            progress_callback=progress_callback,
        )
    else:
        output_file = processed_image_path(out_dir, final_export_name)
        frame_count, cropped_w, cropped_h = crop_image_to_roi_file(
            source_path,
            output_file,
            orientation,
            roi_ref,
            reference_frame_index=reference_frame_index,
        )

    orig_h, orig_w = ref_frame.shape[:2]
    orient_h, orient_w = oriented_ref.shape[:2]

    result = {
        "output_dir": str(out_dir),
        "output_file": str(output_file),
        "roi_preview": str(roi_preview_path),
        "crop_preview": str(crop_preview_path),
        "raw_debug_preview": str(debug_raw_path),
        "metadata_file": str(
            processed_sample_metadata_path(out_dir, final_export_name)
        ),
        "frame_count": frame_count,
        "cropped_dimensions": {"width": cropped_w, "height": cropped_h},
        "original_dimensions": {"width": orig_w, "height": orig_h},
        "oriented_dimensions": {"width": orient_w, "height": orient_h},
        "has_video": is_video,
        "video_fps": video_fps,
        "final_export_name": final_export_name,
        "processed_output_path": relative_to_root(root, output_file),
        "processing_date": _utc_now_iso(),
    }
    return result


def write_processed_metadata(
    out_dir: Path,
    metadata: dict[str, Any],
    *,
    batch_number: int | None = None,
    group: str | None = None,
    final_export_name: str | None = None,
) -> Path:
    if final_export_name:
        path = processed_sample_metadata_path(out_dir, final_export_name)
    elif group and batch_number is not None:
        from actintrack_app.export_naming import batch_metadata_base_name, processed_metadata_path

        base = batch_metadata_base_name(group, batch_number)
        path = processed_metadata_path(out_dir, base)
    else:
        name = metadata.get("final_export_name") or metadata.get("sample_id", "metadata")
        path = out_dir / f"{name}_metadata.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    return path
