"""Tests for user-facing Sample status label mapping."""

from __future__ import annotations

import unittest

from actintrack_app.utils import (
    STATUS_IMPORTED,
    STATUS_MOTION_INDEX_GENERATED,
    STATUS_PROCESSED,
    STATUS_RAW_IMPORTED,
    STATUS_ROI_APPROVED,
    STATUS_ROI_MARKED,
    STATUS_ROI_PROPAGATED,
    STATUS_UNANNOTATED,
    sample_status_label,
)


class SampleStatusLabelTests(unittest.TestCase):
    def test_raw_states_map_to_raw(self) -> None:
        for status in (
            "",
            STATUS_IMPORTED,
            STATUS_RAW_IMPORTED,
            STATUS_UNANNOTATED,
        ):
            self.assertEqual(sample_status_label(status), "Raw")

    def test_roi_states_map_to_roi_marked(self) -> None:
        for status in (
            STATUS_ROI_MARKED,
            STATUS_ROI_PROPAGATED,
            STATUS_ROI_APPROVED,
            STATUS_PROCESSED,
            STATUS_MOTION_INDEX_GENERATED,
        ):
            self.assertEqual(sample_status_label(status), "ROI marked")

    def test_no_legacy_raw_imported_label(self) -> None:
        # The internal enum value must never surface in the UI label.
        self.assertNotIn("raw_imported", sample_status_label(STATUS_RAW_IMPORTED))
        self.assertNotIn("imported", sample_status_label(STATUS_RAW_IMPORTED).lower())

    def test_missing_file_label(self) -> None:
        self.assertEqual(sample_status_label("missing_file"), "Missing file")

    def test_unknown_status_defaults_to_raw(self) -> None:
        self.assertEqual(sample_status_label("some_future_status"), "Raw")


if __name__ == "__main__":
    unittest.main()
