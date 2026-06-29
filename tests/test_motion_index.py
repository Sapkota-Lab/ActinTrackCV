"""Tests for the traditional-CV motion-index tracker."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from actintrack_app.motion_index import (
    TRACKING_METHOD_BRIGHTEST_LOCAL,
    TRACKING_METHOD_TEMPLATE,
    MotionIndexParams,
    PointTrack,
    TrackPoint,
    compute_motion_indices,
    compute_velocity_summary,
    save_trajectory_csv,
    select_starting_points,
    track_points,
    write_track_preview_video,
    write_track_preview_webm,
)
from actintrack_app.tracker_validation import (
    DEFAULT_SCENARIOS,
    validate_scenario,
    run_synthetic_validation,
)


def _frame_with_spots(
    spots: list[tuple[float, float, float]],
    *,
    shape: tuple[int, int] = (80, 80),
) -> np.ndarray:
    frame = np.zeros(shape, dtype=np.float32)
    for x, y, intensity in spots:
        cx = int(round(x))
        cy = int(round(y))
        frame[max(0, cy - 1) : cy + 2, max(0, cx - 1) : cx + 2] = intensity
    return frame


class MotionIndexTests(unittest.TestCase):
    def test_defaults_match_dr_ju_bright_point_direction(self) -> None:
        params = MotionIndexParams()

        self.assertEqual(params.num_starting_points, 10)
        self.assertEqual(params.seconds_per_frame, 30.0)
        self.assertEqual(params.tracking_method, TRACKING_METHOD_BRIGHTEST_LOCAL)

    def test_starting_points_avoid_nucleus_void_and_perinuclear_ring(self) -> None:
        frame = np.full((120, 120, 3), 70, dtype=np.uint8)
        frame[18:22, 18:22] = (40, 180, 180)
        frame[18:22, 95:99] = (40, 175, 175)
        frame[95:99, 50:54] = (40, 170, 170)
        cv2.circle(frame, (60, 72), 24, (8, 8, 8), thickness=-1)
        cv2.circle(frame, (60, 72), 27, (30, 240, 240), thickness=2)

        params = MotionIndexParams(
            num_starting_points=10,
            min_point_spacing_px=12,
            search_radius_px=8,
            min_template_confidence=0.2,
        )
        starts = select_starting_points(frame, params)

        self.assertGreaterEqual(len(starts), 2)
        for x, y in starts:
            dist = ((x - 60.0) ** 2 + (y - 72.0) ** 2) ** 0.5
            self.assertGreater(
                dist,
                20.0,
                msg=f"Starting point ({x:.1f}, {y:.1f}) landed on the nucleus ring",
            )

    def test_brightest_local_tracker_reports_absolute_velocity(self) -> None:
        frames = [
            _frame_with_spots([(20 + (2 * i), 30 + (3 * i), 255)])
            for i in range(4)
        ]
        params = MotionIndexParams(
            num_starting_points=1,
            min_point_spacing_px=8,
            search_radius_px=6,
            min_template_confidence=0.2,
            microns_per_pixel=1.0,
            seconds_per_frame=1.0,
        )

        starts = select_starting_points(frames[0], params)
        tracks = track_points(frames, starts, params)
        downward, general, summaries = compute_motion_indices(tracks, params)

        self.assertEqual(len(starts), 1)
        self.assertEqual(len(tracks[0].points), 4)
        self.assertAlmostEqual(tracks[0].points[-1].x, 26.0, places=3)
        self.assertAlmostEqual(tracks[0].points[-1].y, 39.0, places=3)
        self.assertAlmostEqual(general, float(np.hypot(2, 3)), places=3)
        self.assertAlmostEqual(downward, 3.0, places=3)
        self.assertAlmostEqual(
            summaries[0]["general_movement_index_um_per_s"],
            float(np.hypot(2, 3)),
            places=3,
        )
        self.assertTrue(summaries[0]["active_to_end"])
        self.assertEqual(summaries[0]["end_reason"], "reached_last_frame")

    def test_tracking_assignments_do_not_collapse_onto_one_point(self) -> None:
        frames = [
            _frame_with_spots([(20, 20, 120), (40, 20, 110)]),
            _frame_with_spots([(25, 20, 255), (40, 20, 110)]),
        ]
        params = MotionIndexParams(
            num_starting_points=2,
            min_point_spacing_px=10,
            search_radius_px=25,
            min_template_confidence=0.2,
            microns_per_pixel=1.0,
            seconds_per_frame=1.0,
        )

        starts = select_starting_points(frames[0], params)
        tracks = track_points(frames, starts, params)
        frame_one_points = {
            (round(track.points[1].x), round(track.points[1].y))
            for track in tracks
            if len(track.points) > 1
        }

        self.assertEqual(len(frame_one_points), 2)

    def test_trajectory_csv_includes_per_step_velocity_columns(self) -> None:
        frames = [
            _frame_with_spots([(20 + (2 * i), 30 + (3 * i), 255)])
            for i in range(2)
        ]
        params = MotionIndexParams(
            num_starting_points=1,
            min_point_spacing_px=8,
            search_radius_px=6,
            min_template_confidence=0.2,
            microns_per_pixel=1.0,
            seconds_per_frame=1.0,
        )
        tracks = track_points(frames, select_starting_points(frames[0], params), params)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trajectory.csv"
            save_trajectory_csv(path, tracks, params)
            with path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)

        assert reader.fieldnames is not None
        self.assertIn("absolute_velocity_um_per_s", reader.fieldnames)
        self.assertIn("displacement_um", reader.fieldnames)
        self.assertIn("motion_angle_deg", reader.fieldnames)
        self.assertIn("turning_angle_deg", reader.fieldnames)
        self.assertEqual(rows[0]["absolute_velocity_um_per_s"], "")
        self.assertAlmostEqual(
            float(rows[1]["absolute_velocity_um_per_s"]),
            float(np.hypot(2, 3)),
            places=3,
        )

    def test_trajectory_angles_and_wrapped_turning_angles(self) -> None:
        track = PointTrack(
            track_id=0,
            start_x=10.0,
            start_y=10.0,
            points=[
                TrackPoint(0, 0, 10.0, 10.0, 1.0),
                TrackPoint(0, 1, 11.0, 10.0, 1.0),  # 0 degrees
                TrackPoint(0, 2, 11.0, 11.0, 1.0),  # 90 degrees
                TrackPoint(0, 3, 10.0, 11.0, 1.0),  # 180 degrees
                TrackPoint(0, 4, 10.0, 10.0, 1.0),  # -90 degrees
            ],
        )
        params = MotionIndexParams(microns_per_pixel=1.0, seconds_per_frame=1.0)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "angles.csv"
            save_trajectory_csv(path, [track], params)
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(rows[0]["motion_angle_deg"], "")
        self.assertEqual(rows[1]["turning_angle_deg"], "")
        self.assertEqual(
            [float(row["motion_angle_deg"]) for row in rows[1:]],
            [0.0, 90.0, 180.0, -90.0],
        )
        self.assertEqual(
            [float(row["turning_angle_deg"]) for row in rows[2:]],
            [90.0, 90.0, 90.0],
        )

    def test_explicit_vertical_metrics_have_distinct_denominators(self) -> None:
        track = PointTrack(
            track_id=0,
            start_x=0.0,
            start_y=0.0,
            points=[
                TrackPoint(0, 0, 0.0, 0.0, 1.0),
                TrackPoint(0, 1, 0.0, 2.0, 1.0),
                TrackPoint(0, 2, 0.0, 1.0, 1.0),
                TrackPoint(0, 3, 0.0, 1.0, 1.0),
            ],
        )
        params = MotionIndexParams(microns_per_pixel=1.0, seconds_per_frame=1.0)

        metrics = compute_velocity_summary([track], params)

        self.assertAlmostEqual(metrics.conditional_positive_downward_speed_um_per_s, 2.0)
        self.assertAlmostEqual(metrics.signed_vertical_velocity_um_per_s, 1.0 / 3.0)
        self.assertAlmostEqual(metrics.downward_velocity_contribution_um_per_s, 2.0 / 3.0)
        self.assertAlmostEqual(metrics.time_weighted_mean_speed_um_per_s, 1.0)

    def test_time_weighted_speed_handles_lookahead_frame_gaps(self) -> None:
        track = PointTrack(
            track_id=0,
            start_x=0.0,
            start_y=0.0,
            points=[
                TrackPoint(0, 0, 0.0, 0.0, 1.0),
                TrackPoint(0, 2, 2.0, 0.0, 1.0, recovered_with_lookahead=True),
                TrackPoint(0, 3, 4.0, 0.0, 1.0),
            ],
        )
        params = MotionIndexParams(microns_per_pixel=1.0, seconds_per_frame=1.0)

        metrics = compute_velocity_summary([track], params)

        self.assertAlmostEqual(metrics.mean_step_speed_um_per_s, 1.5)
        self.assertAlmostEqual(metrics.time_weighted_mean_speed_um_per_s, 4.0 / 3.0)

    def test_default_synthetic_ground_truth_benchmark_passes(self) -> None:
        report = run_synthetic_validation()

        self.assertTrue(report["passed"])
        self.assertEqual(report["scenario_count"], len(DEFAULT_SCENARIOS))
        results = report["results"]
        assert isinstance(results, list)
        self.assertTrue(all(row["point_recall"] >= 0.95 for row in results))

    def test_template_tracker_passes_subpixel_benchmark(self) -> None:
        result = validate_scenario(
            DEFAULT_SCENARIOS[1],
            tracking_method=TRACKING_METHOD_TEMPLATE,
        )

        self.assertTrue(result.passed)
        self.assertLess(result.speed_relative_error, 0.10)

    def test_validation_report_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = run_synthetic_validation(output_dir=tmp)

            self.assertTrue(Path(str(report["report_json"])).is_file())
            self.assertTrue(Path(str(report["scenario_csv"])).is_file())

    def test_browser_compatible_preview_formats_are_written(self) -> None:
        frames = [
            cv2.cvtColor(
                _frame_with_spots([(20 + i, 30 + i, 255)]).astype(np.uint8),
                cv2.COLOR_GRAY2BGR,
            )
            for i in range(3)
        ]
        params = MotionIndexParams(
            num_starting_points=1,
            min_point_spacing_px=8,
            search_radius_px=4,
            min_template_confidence=0.2,
            microns_per_pixel=1.0,
            seconds_per_frame=1.0,
        )
        tracks = track_points(frames, select_starting_points(frames[0], params), params)

        with tempfile.TemporaryDirectory() as tmp:
            mp4 = Path(tmp) / "preview.mp4"
            webm = Path(tmp) / "preview.webm"
            try:
                mp4_codec = write_track_preview_video(mp4, frames, tracks)
            except OSError as exc:
                if "unavailable" in str(exc).lower():
                    self.skipTest(f"H.264 encoder unavailable: {exc}")
                raise
            webm_codec = write_track_preview_webm(webm, frames, tracks)

            self.assertIn(mp4_codec, {"avc1", "H264"})
            self.assertIn(webm_codec, {"VP90", "VP80"})
            self.assertGreater(mp4.stat().st_size, 0)
            self.assertGreater(webm.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
