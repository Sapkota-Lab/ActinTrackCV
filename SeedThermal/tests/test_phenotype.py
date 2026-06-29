"""Tests for SeedThermal phenotype helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from seedthermal.phenotype import (
    RoiRect,
    default_frame_roi,
    load_roi_config,
    parse_roi_spec,
    roi_temperature_stats,
)


class PhenotypeTests(unittest.TestCase):
    def test_parse_roi_spec_with_id(self) -> None:
        roi = parse_roi_spec("seed_a:10,20,30,40")
        self.assertEqual(roi.roi_id, "seed_a")
        self.assertEqual((roi.x, roi.y, roi.width, roi.height), (10, 20, 30, 40))

    def test_parse_roi_spec_without_id(self) -> None:
        roi = parse_roi_spec("5,6,7,8")
        self.assertEqual(roi.roi_id, "roi")
        self.assertEqual((roi.x, roi.y, roi.width, roi.height), (5, 6, 7, 8))

    def test_roi_stats(self) -> None:
        celsius = np.arange(100, dtype=np.float64).reshape(10, 10)
        roi = RoiRect("box", 2, 2, 3, 3)
        stats = roi_temperature_stats(celsius, roi)
        self.assertEqual(stats["pixel_count"], 9)
        self.assertAlmostEqual(stats["mean_c"], float(np.mean(celsius[2:5, 2:5])))

    def test_default_frame_roi(self) -> None:
        celsius = np.zeros((640, 480))
        roi = default_frame_roi(celsius)
        self.assertEqual((roi.width, roi.height), (480, 640))

    def test_load_roi_config(self) -> None:
        payload = {
            "reference_roi": {"id": "paper", "x": 1, "y": 2, "w": 3, "h": 4},
            "rois": [{"id": "plate", "x": 0, "y": 0, "width": 10, "height": 10}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rois.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            rois, reference = load_roi_config(path)
        self.assertEqual(len(rois), 1)
        self.assertEqual(rois[0].roi_id, "plate")
        self.assertIsNotNone(reference)
        assert reference is not None
        self.assertEqual(reference.roi_id, "paper")


if __name__ == "__main__":
    unittest.main()
