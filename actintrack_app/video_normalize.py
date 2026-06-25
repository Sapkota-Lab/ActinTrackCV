"""Normalize imported videos so every stored frame has even pixel dimensions.

Odd-height (and, defensively, odd-width) ``yuv420p`` videos are stored padded
with a crop flag. Some FFmpeg builds - notably the one bundled inside the frozen
Windows OpenCV - mishandle that crop on the YUV->BGR path and decode to black or
color-garbled frames. Since OpenCV is the component that mis-decodes, we cannot
re-decode through it to fix the pixels; instead we pad odd-dimension videos to
even with a standalone ffmpeg binary (imageio-ffmpeg) at import time.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import cv2

from actintrack_app.utils import VIDEO_EXTENSIONS
from actintrack_app.video_processing import MediaLoadError


def even_padded_dimensions(width: int, height: int) -> tuple[int, int]:
    """Return ``(width, height)`` rounded up to the next even number each."""
    return (width + (width % 2), height + (height % 2))


def video_pixel_dimensions(path: str | Path) -> tuple[int, int]:
    """Return ``(width, height)`` reported by the container.

    Dimension reporting via ``CAP_PROP_*`` is reliable even when pixel decoding
    is broken for the file, so this is safe to use on the affected platform.
    """
    path = Path(path)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        cap.release()
        raise MediaLoadError(f"Cannot open data file: {path}")
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        cap.release()
    if width <= 0 or height <= 0:
        raise MediaLoadError(f"Could not read frame dimensions: {path}")
    return width, height


def needs_even_padding(path: str | Path) -> bool:
    """True when a video has an odd width or height and must be normalized."""
    path = Path(path)
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        return False
    width, height = video_pixel_dimensions(path)
    return (width % 2 != 0) or (height % 2 != 0)


def _ffmpeg_exe() -> str:
    """Path to the bundled ffmpeg binary."""
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def normalize_video_to_even(src: str | Path, dest: str | Path) -> None:
    """Pad ``src`` to even dimensions and write a lossless re-encode to ``dest``.

    The pad is anchored at the top-left (0, 0), so existing pixel coordinates and
    the microns-per-pixel calibration are preserved; at most a one-pixel black
    border is added on the right/bottom. The destination container is inferred
    from ``dest``'s extension, so the source format/extension is kept.
    """
    src_path = Path(src)
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        _ffmpeg_exe(),
        "-y",
        "-i",
        str(src_path),
        "-vf",
        "pad=ceil(iw/2)*2:ceil(ih/2)*2:0:0:color=black",
        "-c:v",
        "libx264",
        "-qp",
        "0",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(dest_path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except (OSError, ImportError) as exc:
        raise MediaLoadError(
            f"Could not normalize video dimensions for {src_path.name}: {exc}"
        ) from exc
    if proc.returncode != 0 or not dest_path.is_file():
        detail = proc.stderr.decode("utf-8", errors="replace").strip().splitlines()
        tail = detail[-1] if detail else f"ffmpeg exited with {proc.returncode}"
        raise MediaLoadError(
            f"Could not normalize video dimensions for {src_path.name}: {tail}"
        )


def store_imported_video(src: str | Path, dest: str | Path) -> None:
    """Copy a video into the workspace, normalizing odd dimensions to even.

    Even-dimension videos (the common case) are copied byte-for-byte unchanged.
    Odd-dimension videos are padded to even and re-encoded losslessly so the
    stored file decodes correctly on every platform.
    """
    src_path = Path(src)
    dest_path = Path(dest)
    if needs_even_padding(src_path):
        normalize_video_to_even(src_path, dest_path)
    else:
        shutil.copy2(src_path, dest_path)
