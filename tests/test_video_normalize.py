import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2

from actintrack_app import video_normalize


def _ffmpeg_available() -> bool:
    try:
        import imageio_ffmpeg

        return Path(imageio_ffmpeg.get_ffmpeg_exe()).is_file()
    except Exception:
        return False


class EvenPaddedDimensionsTest(unittest.TestCase):
    def test_odd_height_rounds_up(self) -> None:
        self.assertEqual(video_normalize.even_padded_dimensions(326, 741), (326, 742))

    def test_odd_width_rounds_up(self) -> None:
        self.assertEqual(video_normalize.even_padded_dimensions(335, 676), (336, 676))

    def test_both_odd_round_up(self) -> None:
        self.assertEqual(video_normalize.even_padded_dimensions(335, 741), (336, 742))

    def test_even_dimensions_unchanged(self) -> None:
        self.assertEqual(video_normalize.even_padded_dimensions(320, 240), (320, 240))


class NeedsEvenPaddingTest(unittest.TestCase):
    def test_non_video_extension_skipped(self) -> None:
        self.assertFalse(video_normalize.needs_even_padding(Path("frame.png")))

    def test_odd_height_needs_padding(self) -> None:
        with mock.patch.object(
            video_normalize, "video_pixel_dimensions", return_value=(326, 741)
        ):
            self.assertTrue(video_normalize.needs_even_padding(Path("clip.mp4")))

    def test_odd_width_needs_padding(self) -> None:
        with mock.patch.object(
            video_normalize, "video_pixel_dimensions", return_value=(335, 676)
        ):
            self.assertTrue(video_normalize.needs_even_padding(Path("clip.avi")))

    def test_even_dimensions_skipped(self) -> None:
        with mock.patch.object(
            video_normalize, "video_pixel_dimensions", return_value=(320, 240)
        ):
            self.assertFalse(video_normalize.needs_even_padding(Path("clip.mp4")))


@unittest.skipUnless(_ffmpeg_available(), "bundled ffmpeg not available")
class NormalizeIntegrationTest(unittest.TestCase):
    def _make_odd_height_clip(self, dest: Path) -> None:
        # libx264/yuv420p cannot encode odd dimensions, so synthesize the
        # odd-height source with MJPEG 4:4:4 (no chroma subsampling), which is a
        # realistic stand-in for the odd-height files that trigger the bug.
        import imageio_ffmpeg

        cmd = [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x241:rate=5:duration=1",
            "-c:v",
            "mjpeg",
            "-pix_fmt",
            "yuvj444p",
            "-an",
            str(dest),
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    def test_normalize_pads_odd_height_to_even(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "odd.avi"
            dest = Path(tmp) / "even.mp4"
            self._make_odd_height_clip(src)

            self.assertTrue(video_normalize.needs_even_padding(src))
            video_normalize.normalize_video_to_even(src, dest)

            self.assertTrue(dest.is_file())
            width, height = video_normalize.video_pixel_dimensions(dest)
            self.assertEqual(width % 2, 0)
            self.assertEqual(height % 2, 0)
            self.assertEqual((width, height), (320, 242))

            cap = cv2.VideoCapture(str(dest))
            try:
                ok, frame = cap.read()
                self.assertTrue(ok)
                self.assertIsNotNone(frame)
            finally:
                cap.release()

    def test_store_copies_even_file_byte_for_byte(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "even_src.mp4"
            dest = Path(tmp) / "even_dest.mp4"
            import imageio_ffmpeg

            subprocess.run(
                [
                    imageio_ffmpeg.get_ffmpeg_exe(),
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=size=320x240:rate=5:duration=1",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-an",
                    str(src),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )

            video_normalize.store_imported_video(src, dest)
            self.assertEqual(src.read_bytes(), dest.read_bytes())


if __name__ == "__main__":
    unittest.main()
