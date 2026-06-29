"""Tests for the Python bridge used by the R Shiny application."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from scripts.shiny_bridge import (
    crop_video_to_frames,
    extract_preview_frame,
    probe_media,
    transcode_preview_to_webm,
)


def _write_video(path: Path, frame_count: int = 5) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        5.0,
        (80, 60),
    )
    if not writer.isOpened():
        raise OSError(f"Could not create test video: {path}")
    try:
        for index in range(frame_count):
            frame = np.zeros((60, 80, 3), dtype=np.uint8)
            cv2.circle(frame, (20 + index, 30 + index), 3, (255, 255, 0), -1)
            writer.write(frame)
    finally:
        writer.release()


class ShinyBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.video = self.root / "source.avi"
        _write_video(self.video)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_probe_media(self) -> None:
        metadata = probe_media(self.video)

        self.assertEqual(metadata["frame_count"], 5)
        self.assertEqual(metadata["width"], 80)
        self.assertEqual(metadata["height"], 60)
        self.assertAlmostEqual(metadata["playback_fps"], 5.0, places=2)

    def test_extract_preview_frame_applies_rotation(self) -> None:
        output = self.root / "preview.png"
        metadata = extract_preview_frame(
            self.video,
            output,
            2,
            rotation=90,
        )

        image = cv2.imread(str(output), cv2.IMREAD_COLOR)
        self.assertIsNotNone(image)
        assert image is not None
        self.assertEqual(image.shape[:2], (80, 60))
        self.assertEqual(metadata["width"], 60)
        self.assertEqual(metadata["height"], 80)

    def test_crop_video_to_lossless_frames(self) -> None:
        frame_dir = self.root / "cropped"
        metadata = crop_video_to_frames(
            self.video,
            frame_dir,
            rotation=0,
            flip_horizontal=False,
            roi_x=10,
            roi_y=15,
            roi_width=40,
            roi_height=30,
        )

        frames = sorted(frame_dir.glob("*.png"))
        self.assertEqual(len(frames), 5)
        self.assertEqual(metadata["roi_width"], 40)
        self.assertEqual(metadata["roi_height"], 30)
        image = cv2.imread(str(frames[0]), cv2.IMREAD_COLOR)
        self.assertIsNotNone(image)
        assert image is not None
        self.assertEqual(image.shape[:2], (30, 40))

    def test_transcode_legacy_preview_to_browser_webm(self) -> None:
        output = self.root / "browser_preview.webm"

        metadata = transcode_preview_to_webm(self.video, output)

        self.assertTrue(output.is_file())
        self.assertGreater(output.stat().st_size, 0)
        self.assertIn(metadata["codec"], {"VP90", "VP80"})
        self.assertEqual(metadata["mime_type"], "video/webm")
        self.assertEqual(metadata["frame_count"], 5)
        capture = cv2.VideoCapture(str(output))
        try:
            self.assertTrue(capture.isOpened())
            self.assertEqual(int(capture.get(cv2.CAP_PROP_FRAME_COUNT)), 5)
        finally:
            capture.release()


if __name__ == "__main__":
    unittest.main()
