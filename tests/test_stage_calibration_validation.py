"""Tests for Layer 2 stage-calibration validation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from actintrack_app.stage_calibration_validation import (
    StageCalibrationThresholds,
    _agreement_stats,
    build_synthetic_manifest,
    load_stage_calibration_manifest,
    measure_landmark_displacement_px,
    run_synthetic_stage_calibration,
    run_stage_calibration_validation,
)


class StageCalibrationValidationTests(unittest.TestCase):
    def test_agreement_stats(self) -> None:
        stats = _agreement_stats([0.1, -0.05, 0.0, 0.15])
        self.assertEqual(stats["count"], 4)
        self.assertAlmostEqual(stats["bias"], 0.05, places=6)
        self.assertGreater(stats["mae"], 0.0)

    def test_load_example_manifest(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest_path = root / "examples" / "layer2_stage_calibration.manifest.example.json"
        manifest = load_stage_calibration_manifest(manifest_path, base_dir=root)
        self.assertEqual(manifest.protocol_version, 1)
        self.assertGreaterEqual(len(manifest.recordings), 6)
        self.assertEqual(manifest.recordings[0].direction, "zero")

    def test_synthetic_layer2_gate_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = run_synthetic_stage_calibration(
                output_dir=Path(tmp),
                seed=20260630,
                thresholds=StageCalibrationThresholds(
                    max_abs_bias_um_per_frame=0.25,
                    max_rmse_um_per_frame=0.35,
                    max_zero_motion_um_per_frame=0.15,
                ),
            )
            self.assertTrue(report["passed"], report.get("failure_reasons"))
            self.assertGreaterEqual(report["passed_recording_count"], 6)
            self.assertTrue(Path(report["report_json"]).is_file())

    def test_measure_landmark_displacement_from_trajectory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "tracks.csv"
            csv_path.write_text(
                "track_id,frame_index,dx_px,dy_px\n"
                "0,1,2.0,1.0\n"
                "0,2,2.0,1.0\n",
                encoding="utf-8",
            )
            dx, dy = measure_landmark_displacement_px(csv_path)
            self.assertAlmostEqual(dx, 2.0)
            self.assertAlmostEqual(dy, 1.0)

    def test_build_synthetic_manifest_writes_videos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest = build_synthetic_manifest(output_dir=out / "videos")
            self.assertGreaterEqual(len(manifest.recordings), 6)
            for recording in manifest.recordings:
                self.assertTrue(Path(recording.source_path).is_file())

    def test_manifest_analysis_writes_report_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = build_synthetic_manifest(output_dir=root / "videos")
            report = run_stage_calibration_validation(
                manifest,
                output_dir=root / "results",
            )
            payload = json.loads(Path(report["report_json"]).read_text(encoding="utf-8"))
            self.assertIn("agreement", payload)
            self.assertIn("recordings", payload)


if __name__ == "__main__":
    unittest.main()
