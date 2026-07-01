"""Tests for unified metric scheduling constants and batch ROI export filter."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from actintrack_app.utils import METRIC_DEBOUNCE_MS
from actintrack_app.optical_flow_motion_index import OpticalFlowSettings
from actintrack_app.optical_flow_overlay import OpticalFlowVisualizationSettings
from actintrack_app.roi_workflow import process_batch_approved_rois
from actintrack_app.utils import METADATA_DIR, SAMPLES_CSV, STATUS_ROI_MARKED


class MetricSchedulingTests(unittest.TestCase):
    def test_metric_debounce_is_two_point_five_seconds(self) -> None:
        self.assertEqual(METRIC_DEBOUNCE_MS, 2500)

    def test_overlay_defaults(self) -> None:
        defaults = OpticalFlowVisualizationSettings()
        self.assertEqual(defaults.arrow_spacing_px, 8)
        self.assertEqual(defaults.arrow_scale, 0.8)

    def test_optical_flow_mask_percentile_default(self) -> None:
        defaults = OpticalFlowSettings()
        self.assertEqual(defaults.mask_percentile, 65.0)

    def test_batch_export_accepts_roi_marked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            meta = root / METADATA_DIR
            meta.mkdir(parents=True)
            df = pd.DataFrame(
                [
                    {
                        "sample_id": "S1",
                        "group": "Col-0",
                        "batch_name": "batch1",
                        "batch_number": "1",
                        "stored_path": "raw_source/S1.avi",
                        "processing_status": STATUS_ROI_MARKED,
                    },
                    {
                        "sample_id": "S2",
                        "group": "Col-0",
                        "batch_name": "batch1",
                        "batch_number": "1",
                        "stored_path": "raw_source/S2.avi",
                        "processing_status": "imported",
                    },
                ]
            )
            df.to_csv(meta / SAMPLES_CSV, index=False)
            crop = {
                "version": 2,
                "samples": {
                    "S1": {
                        "sample_id": "S1",
                        "rectangle_roi": {"x": 1, "y": 2, "width": 10, "height": 12},
                    }
                },
            }
            import json

            (meta / "crop_metadata.json").write_text(json.dumps(crop), encoding="utf-8")

            approved, skipped, _ = process_batch_approved_rois(
                root=root,
                group="Col-0",
                batch_name="batch1",
            )
            self.assertEqual(approved, ["S1"])
            self.assertEqual(skipped, ["S2"])


if __name__ == "__main__":
    unittest.main()
