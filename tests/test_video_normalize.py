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


class StoreRoutingTest(unittest.TestCase):
    """store_imported_video routing without invoking ffmpeg."""

    def test_even_dimensions_are_copied_byte_for_byte(self) -> None:
        with mock.patch.object(
            video_normalize, "needs_even_padding", return_value=False
        ):
            with tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / "even.mp4"
                src.write_bytes(b"raw-bytes-123")
                dest = Path(tmp) / "stored.mp4"
                video_normalize.store_imported_video(src, dest)
                self.assertEqual(dest.read_bytes(), b"raw-bytes-123")

    def test_odd_dimensions_are_normalized_not_copied(self) -> None:
        with mock.patch.object(
            video_normalize, "needs_even_padding", return_value=True
        ), mock.patch.object(
            video_normalize, "normalize_video_to_even"
        ) as norm:
            video_normalize.store_imported_video("odd.mp4", "stored.mp4")
            norm.assert_called_once()


class NormalizeFailureTest(unittest.TestCase):
    """A failed normalization surfaces MediaLoadError, not a raw subprocess error."""

    def test_ffmpeg_nonzero_exit_raises_media_load_error(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr=b"some ffmpeg failure\n"
        )
        with mock.patch.object(
            video_normalize, "_ffmpeg_exe", return_value="ffmpeg"
        ), mock.patch.object(
            video_normalize.subprocess, "run", return_value=completed
        ):
            with tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / "odd.mp4"
                src.write_bytes(b"not-a-real-video")
                dest = Path(tmp) / "out.mp4"
                with self.assertRaises(video_normalize.MediaLoadError):
                    video_normalize.normalize_video_to_even(src, dest)

    def test_ffmpeg_missing_raises_media_load_error(self) -> None:
        with mock.patch.object(
            video_normalize, "_ffmpeg_exe", return_value="ffmpeg"
        ), mock.patch.object(
            video_normalize.subprocess, "run", side_effect=OSError("not found")
        ):
            with tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / "odd.mp4"
                src.write_bytes(b"not-a-real-video")
                dest = Path(tmp) / "out.mp4"
                with self.assertRaises(video_normalize.MediaLoadError):
                    video_normalize.normalize_video_to_even(src, dest)

    def test_ffmpeg_resolution_error_raises_media_load_error(self) -> None:
        # imageio_ffmpeg.get_ffmpeg_exe() can raise RuntimeError/ValueError in a
        # frozen build; that must become MediaLoadError, not an uncaught crash.
        for exc in (RuntimeError("no ffmpeg exe"), ValueError("bad ffmpeg")):
            with mock.patch.object(
                video_normalize, "_ffmpeg_exe", side_effect=exc
            ):
                with tempfile.TemporaryDirectory() as tmp:
                    src = Path(tmp) / "odd.mp4"
                    src.write_bytes(b"not-a-real-video")
                    dest = Path(tmp) / "out.mp4"
                    with self.assertRaises(video_normalize.MediaLoadError):
                        video_normalize.normalize_video_to_even(src, dest)


if __name__ == "__main__":
    unittest.main()
