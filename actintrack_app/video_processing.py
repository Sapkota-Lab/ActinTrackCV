"""Video and image frame loading."""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

import cv2
import numpy as np

from actintrack_app.utils import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS


class MediaLoadError(Exception):
    """Raised when a file cannot be opened or has no frames."""


def load_video_frame(video_path: str | Path, frame_index: int = 0) -> np.ndarray:
    """Load a single frame from a video file (BGR, uint8)."""
    path = Path(video_path)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        cap.release()
        raise MediaLoadError(f"Cannot open video: {path}")

    try:
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if count <= 0:
            # Some codecs report 0; still try to read
            pass
        elif frame_index < 0 or frame_index >= count:
            cap.release()
            raise MediaLoadError(
                f"Frame index {frame_index} out of range (0–{max(0, count - 1)})"
            )

        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok or frame is None:
            raise MediaLoadError(f"No readable frame at index {frame_index}: {path}")
        return frame
    finally:
        cap.release()


def get_video_frame_count(video_path: str | Path) -> int:
    path = Path(video_path)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        cap.release()
        raise MediaLoadError(f"Cannot open video: {path}")
    try:
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if count > 0:
            return count
        # Fallback: count by reading
        n = 0
        while True:
            ok, _ = cap.read()
            if not ok:
                break
            n += 1
        if n == 0:
            raise MediaLoadError(f"Video has no readable frames: {path}")
        return n
    finally:
        cap.release()


def load_image(image_path: str | Path) -> np.ndarray:
    """Load a single image (BGR). For multi-page TIFF, first page only in phase 1."""
    path = Path(image_path)
    ext = path.suffix.lower()

    if ext in {".tif", ".tiff"}:
        return load_tiff_page(image_path, page_index=0)

    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise MediaLoadError(f"Cannot open image: {path}")
    return img


def load_tiff_page(image_path: str | Path, page_index: int = 0) -> np.ndarray:
    """
    Load one page from a TIFF (or single-page TIFF).

    Multi-frame TIFF stack navigation: extend here with tifffile or
    cv2.imreadmulti when full stack support is added.
    """
    path = Path(image_path)
    try:
        import tifffile

        with tifffile.TiffFile(str(path)) as tif:
            pages = len(tif.pages)
            if page_index < 0 or page_index >= pages:
                raise MediaLoadError(
                    f"TIFF page {page_index} out of range (0–{pages - 1}): {path}"
                )
            arr = tif.pages[page_index].asarray()
    except ImportError:
        # Fallback: OpenCV reads first page only
        if page_index != 0:
            raise MediaLoadError(
                "Multi-page TIFF navigation requires 'tifffile'. "
                "Install with: pip install tifffile"
            )
        arr = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if arr is None:
            raise MediaLoadError(f"Cannot open TIFF: {path}")

    return _array_to_bgr(arr)


def get_tiff_page_count(image_path: str | Path) -> int:
    """Return number of pages in a TIFF stack (1 for single-page)."""
    path = Path(image_path)
    try:
        import tifffile

        with tifffile.TiffFile(str(path)) as tif:
            return len(tif.pages)
    except ImportError:
        return 1


def _array_to_bgr(arr: np.ndarray) -> np.ndarray:
    if arr.ndim == 2:
        return cv2.cvtColor(arr.astype(np.uint8), cv2.COLOR_GRAY2BGR)
    if arr.ndim == 3:
        if arr.shape[2] == 3:
            # Assume RGB from scientific TIFF
            return cv2.cvtColor(arr.astype(np.uint8), cv2.COLOR_RGB2BGR)
        if arr.shape[2] == 4:
            return cv2.cvtColor(arr.astype(np.uint8), cv2.COLOR_RGBA2BGR)
    raise MediaLoadError(f"Unsupported image array shape: {arr.shape}")


def load_media_frame(
    path: str | Path,
    frame_index: int = 0,
) -> Tuple[np.ndarray, int, int]:
    """
    Load frame for preview. Returns (frame_bgr, frame_index_used, total_frames).
    """
    path = Path(path)
    ext = path.suffix.lower()

    if ext in VIDEO_EXTENSIONS:
        total = get_video_frame_count(path)
        idx = max(0, min(frame_index, total - 1))
        return load_video_frame(path, idx), idx, total

    if ext in {".tif", ".tiff"}:
        total = get_tiff_page_count(path)
        idx = max(0, min(frame_index, total - 1))
        return load_tiff_page(path, idx), idx, total

    if ext in IMAGE_EXTENSIONS:
        return load_image(path), 0, 1

    raise MediaLoadError(f"Unsupported file type: {ext}")
