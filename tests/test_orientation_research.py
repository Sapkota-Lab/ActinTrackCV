"""Deterministic tests for R7A structural-orientation method research."""

from __future__ import annotations

import unittest

import cv2
import numpy as np

from actintrack_app.orientation_research import (
    ORIENTATION_METHODS,
    METHOD_STRUCTURE_TENSOR,
    OrientationResearchSettings,
    angle_relative_to_nucleus_deg,
    axial_angle_error_deg,
    axial_circular_mean_deg,
    normalize_hough_lines_p,
    run_orientation_method,
)


def _line_frame(
    angle_deg: float,
    *,
    intensity: int = 220,
    noise_sigma: float = 4.0,
    seed: int = 741,
) -> np.ndarray:
    rng = np.random.default_rng(seed + int(angle_deg * 10))
    image = rng.normal(10.0, noise_sigma, (128, 128)).clip(0, 255).astype(np.uint8)
    center = np.array([82.0, 64.0])
    direction = np.array(
        [np.cos(np.deg2rad(angle_deg)), np.sin(np.deg2rad(angle_deg))]
    )
    p0 = tuple(np.round(center - direction * 38).astype(int))
    p1 = tuple(np.round(center + direction * 38).astype(int))
    cv2.line(image, p0, p1, intensity, 3, cv2.LINE_AA)
    return cv2.GaussianBlur(image, (3, 3), 0)


class AxialAngleSemanticsTests(unittest.TestCase):
    def test_relative_angle_convention_exact_cases(self) -> None:
        nucleus = (0.0, 0.0)
        point = (10.0, 0.0)
        for expected in (0.0, 30.0, 45.0, 60.0, 90.0):
            with self.subTest(expected=expected):
                measured = angle_relative_to_nucleus_deg(
                    expected,
                    point[0],
                    point[1],
                    nucleus,
                )
                self.assertAlmostEqual(measured, expected, places=10)

    def test_traversal_direction_is_irrelevant(self) -> None:
        first = angle_relative_to_nucleus_deg(35.0, 10.0, 4.0, (0.0, 0.0))
        reverse = angle_relative_to_nucleus_deg(215.0, 10.0, 4.0, (0.0, 0.0))
        self.assertAlmostEqual(first, reverse, places=10)

    def test_axial_error_wraps_at_180_degrees(self) -> None:
        self.assertAlmostEqual(axial_angle_error_deg(179.0, 1.0), 2.0)
        self.assertAlmostEqual(axial_angle_error_deg(91.0, 89.0), 2.0)

    def test_angle_is_undefined_at_nucleus_center(self) -> None:
        with self.assertRaises(ValueError):
            angle_relative_to_nucleus_deg(30.0, 5.0, 5.0, (5.0, 5.0))


class StructureTensorResearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = OrientationResearchSettings(
            threshold_percentile=70.0,
            window_size_px=15,
            sample_spacing_px=6,
        )

    def test_known_straight_angles_are_recovered(self) -> None:
        for expected in (0.0, 30.0, 45.0, 60.0, 90.0):
            with self.subTest(expected=expected):
                result = run_orientation_method(
                    METHOD_STRUCTURE_TENSOR,
                    _line_frame(expected),
                    settings=self.settings,
                )
                mean = axial_circular_mean_deg(result.estimates)
                self.assertIsNotNone(mean)
                assert mean is not None
                self.assertLess(axial_angle_error_deg(mean, expected), 7.0)

    def test_weak_filament_remains_measurable(self) -> None:
        result = run_orientation_method(
            METHOD_STRUCTURE_TENSOR,
            _line_frame(30.0, intensity=45, noise_sigma=7.0),
            settings=self.settings,
        )
        mean = axial_circular_mean_deg(result.estimates)
        self.assertIsNotNone(mean)
        assert mean is not None
        self.assertLess(axial_angle_error_deg(mean, 30.0), 8.0)

    def test_noisy_background_remains_measurable(self) -> None:
        result = run_orientation_method(
            METHOD_STRUCTURE_TENSOR,
            _line_frame(60.0, intensity=150, noise_sigma=22.0),
            settings=self.settings,
        )
        mean = axial_circular_mean_deg(result.estimates)
        self.assertIsNotNone(mean)
        assert mean is not None
        self.assertLess(axial_angle_error_deg(mean, 60.0), 10.0)

    def test_valid_mask_excludes_measurements(self) -> None:
        frame = np.maximum(_line_frame(0.0), _line_frame(90.0))
        mask = np.zeros(frame.shape, dtype=bool)
        mask[:, :64] = True
        result = run_orientation_method(
            METHOD_STRUCTURE_TENSOR,
            frame,
            valid_mask=mask,
            settings=self.settings,
        )
        self.assertGreater(len(result.estimates), 0)
        for estimate in result.estimates:
            self.assertTrue(mask[int(estimate.y_px), int(estimate.x_px)])

    def test_crossing_center_has_lower_coherence_than_line_arms(self) -> None:
        frame = np.full((128, 128), 10, dtype=np.uint8)
        cv2.line(frame, (20, 20), (108, 108), 220, 3, cv2.LINE_AA)
        cv2.line(frame, (20, 108), (108, 20), 220, 3, cv2.LINE_AA)
        result = run_orientation_method(
            METHOD_STRUCTURE_TENSOR,
            frame,
            settings=OrientationResearchSettings(
                threshold_percentile=80.0,
                window_size_px=15,
                sample_spacing_px=2,
                minimum_confidence=0.0,
            ),
        )
        center = [
            item
            for item in result.estimates
            if abs(item.x_px - 64.0) <= 4 and abs(item.y_px - 64.0) <= 4
        ]
        arms = [
            item
            for item in result.estimates
            if 20 <= item.x_px <= 45 and 20 <= item.y_px <= 45
        ]
        self.assertTrue(center)
        self.assertTrue(arms)
        self.assertLess(
            float(np.mean([item.confidence for item in center])),
            float(np.mean([item.confidence for item in arms])),
        )

    def test_curved_filament_preserves_multiple_local_orientations(self) -> None:
        frame = np.full((128, 128), 10, dtype=np.uint8)
        cv2.ellipse(frame, (64, 82), (42, 35), 0, 190, 350, 220, 3, cv2.LINE_AA)
        result = run_orientation_method(
            METHOD_STRUCTURE_TENSOR,
            frame,
            settings=self.settings,
        )
        orientations = [item.local_orientation_deg for item in result.estimates]
        self.assertGreater(len(orientations), 10)
        self.assertGreater(float(np.std(orientations)), 15.0)

    def test_all_research_methods_execute(self) -> None:
        frame = _line_frame(45.0)
        for method in ORIENTATION_METHODS:
            with self.subTest(method=method):
                result = run_orientation_method(
                    method,
                    frame,
                    settings=self.settings,
                )
                self.assertEqual(result.method, method)
                self.assertGreaterEqual(result.runtime_ms, 0.0)


class HoughLinesPShapeNormalizationTests(unittest.TestCase):
    def test_nested_and_flat_shapes_are_equivalent(self) -> None:
        nested = np.array([[[10, 20, 40, 50]], [[5, 6, 7, 18]]], dtype=np.int32)
        flat = np.array([[10, 20, 40, 50], [5, 6, 7, 18]], dtype=np.int32)
        out_nested = normalize_hough_lines_p(nested)
        out_flat = normalize_hough_lines_p(flat)
        self.assertEqual(out_nested.shape, (2, 4))
        self.assertEqual(out_flat.shape, (2, 4))
        np.testing.assert_allclose(out_nested, out_flat)

    def test_none_and_empty_become_zero_rows(self) -> None:
        empty = normalize_hough_lines_p(None)
        self.assertEqual(empty.shape, (0, 4))
        empty_nested = normalize_hough_lines_p(np.empty((0, 1, 4), dtype=np.int32))
        self.assertEqual(empty_nested.shape, (0, 4))

    def test_malformed_shapes_are_rejected(self) -> None:
        for bad in (
            np.array([[1.0, 2.0], [3.0, 4.0]]),
            np.array([[[1, 2, 3]]]),
            np.array([1, 2, 3, 4]),
            np.zeros((2, 2, 4)),
        ):
            with self.subTest(shape=bad.shape):
                with self.assertRaises(ValueError):
                    normalize_hough_lines_p(bad)


if __name__ == "__main__":
    unittest.main()
