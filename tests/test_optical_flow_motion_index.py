"""Unit tests for dense Farnebäck optical-flow motion index."""

from __future__ import annotations

import unittest

import numpy as np

from actintrack_app.optical_flow_motion_index import (
    OpticalFlowSettings,
    build_optical_flow_fingerprint,
    compute_optical_flow_motion_index,
    is_optical_flow_result_stale,
    result_from_dict,
    result_to_dict,
)


def _shifted_frames(
    height: int = 64,
    width: int = 64,
    count: int = 5,
    dy: int = 2,
) -> list[np.ndarray]:
    """Bright band shifted downward each frame on dark background."""
    frames: list[np.ndarray] = []
    for i in range(count):
        frame = np.zeros((height, width), dtype=np.uint8)
        y0 = 10 + i * dy
        frame[y0 : y0 + 12, 16:48] = 220
        frames.append(frame)
    return frames


class OpticalFlowMotionIndexTests(unittest.TestCase):
    def test_downward_shift_produces_positive_metrics(self) -> None:
        settings = OpticalFlowSettings(mask_percentile=50, gaussian_blur_kernel=3)
        result = compute_optical_flow_motion_index(_shifted_frames(), settings)
        self.assertTrue(result.has_valid_result)
        self.assertIsNotNone(result.optical_flow_general_movement_um_s)
        self.assertGreater(result.optical_flow_general_movement_um_s or 0.0, 0.0)
        self.assertGreater(result.optical_flow_downward_motion_um_s or 0.0, 0.0)
        self.assertGreater(result.optical_flow_net_y_velocity_um_s or 0.0, 0.0)
        self.assertIsNotNone(result.optical_flow_directionality_ratio)

    def test_mask_excludes_dark_background(self) -> None:
        settings = OpticalFlowSettings(mask_percentile=80, gaussian_blur_kernel=0)
        result = compute_optical_flow_motion_index(_shifted_frames(), settings)
        self.assertTrue(result.has_valid_result)
        self.assertLess((result.optical_flow_valid_pixel_fraction or 1.0), 0.5)

    def test_fewer_than_two_frames_fails(self) -> None:
        settings = OpticalFlowSettings()
        result = compute_optical_flow_motion_index(
            [np.zeros((32, 32), dtype=np.uint8)], settings
        )
        self.assertFalse(result.has_valid_result)
        self.assertIn("2 frames", result.failure_reason)

    def test_all_dark_frames_fail(self) -> None:
        settings = OpticalFlowSettings(mask_percentile=99)
        dark = [np.zeros((32, 32), dtype=np.uint8) for _ in range(4)]
        result = compute_optical_flow_motion_index(dark, settings)
        self.assertFalse(result.has_valid_result)

    def test_fingerprint_changes_with_settings(self) -> None:
        base = OpticalFlowSettings()
        alt = OpticalFlowSettings(mask_percentile=70)
        fp1 = build_optical_flow_fingerprint(
            sample_id="S1",
            roi_bounds=(0, 0, 100, 100),
            settings=base,
            data_identity="video.avi",
            frame_count=10,
        )
        fp2 = build_optical_flow_fingerprint(
            sample_id="S1",
            roi_bounds=(0, 0, 100, 100),
            settings=alt,
            data_identity="video.avi",
            frame_count=10,
        )
        self.assertNotEqual(fp1, fp2)

    def test_staleness_detection(self) -> None:
        self.assertTrue(is_optical_flow_result_stale("a", "b"))
        self.assertFalse(is_optical_flow_result_stale("same", "same"))

    def test_json_round_trip(self) -> None:
        settings = OpticalFlowSettings()
        original = compute_optical_flow_motion_index(
            _shifted_frames(),
            settings,
            sample_id="WT550_0001",
            fingerprint="abc",
        )
        restored = result_from_dict(result_to_dict(original))
        self.assertEqual(original.has_valid_result, restored.has_valid_result)
        self.assertAlmostEqual(
            original.optical_flow_general_movement_um_s or 0.0,
            restored.optical_flow_general_movement_um_s or 0.0,
            places=4,
        )

    def test_directionality_zero_when_no_movement(self) -> None:
        settings = OpticalFlowSettings(mask_percentile=50)
        static = [np.full((40, 40), 200, dtype=np.uint8) for _ in range(3)]
        result = compute_optical_flow_motion_index(static, settings)
        if result.has_valid_result:
            ratio = result.optical_flow_directionality_ratio
            self.assertTrue(ratio is None or ratio == 0.0)


if __name__ == "__main__":
    unittest.main()
