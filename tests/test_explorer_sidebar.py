"""Tests for explorer sidebar display labels (Phase 4A)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from actintrack_app.condition_group_manager import (
    create_condition_group,
    rename_condition_group,
)
from actintrack_app.explorer_sidebar import (
    ITEM_TYPE_CONDITION_GROUP,
    ITEM_TYPE_SAMPLE,
    label_excludes_condition_group_name,
    sample_sidebar_display_label,
    sample_tree_meta,
    tree_item_condition_group_id,
)
from actintrack_app.project_manager import create_project_structure
from actintrack_app.sample_service import create_sample_from_data


def _write_test_video(path: Path, frames: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        10.0,
        (32, 32),
    )
    for i in range(frames):
        frame = np.zeros((32, 32, 3), dtype=np.uint8)
        frame[:, :] = (i * 40, 0, 0)
        writer.write(frame)
    writer.release()


class ExplorerSidebarLabelTests(unittest.TestCase):
    def test_sample_label_uses_original_filename_not_group_prefix(self) -> None:
        row = {
            "sample_id": "cg_abc_B001_D001",
            "original_filename": "02_676-6-2.mp4",
            "batch_name": "02_676-6-2",
            "batch_number": 1,
            "auto_export_name": "Control--01",
            "breed": "Control",
            "group": "cg_abc",
        }
        label = sample_sidebar_display_label(row)
        self.assertEqual(label, "02_676-6-2.mp4")
        self.assertTrue(label_excludes_condition_group_name(label, "Control"))
        self.assertNotIn("Control--", label)
        self.assertNotIn("Sample 1", label)

    def test_sample_label_prefers_filename_over_generic_batch_name(self) -> None:
        row = {
            "sample_id": "x",
            "original_filename": "03_676-6-3.mp4",
            "batch_name": "Batch 1",
            "batch_number": 1,
        }
        self.assertEqual(sample_sidebar_display_label(row), "03_676-6-3.mp4")

    def test_sample_label_falls_back_to_batch_name_when_no_filename(self) -> None:
        row = {
            "sample_id": "x",
            "original_filename": "",
            "batch_name": "01_676-8-2",
            "batch_number": 2,
        }
        self.assertEqual(sample_sidebar_display_label(row), "01_676-8-2")

    def test_tree_meta_carries_stable_ids(self) -> None:
        row = {
            "sample_id": "sid-1",
            "group": "cg_deadbeef",
            "condition_group_id": "cg_deadbeef",
            "original_filename": "clip.avi",
        }
        meta = sample_tree_meta(row)
        self.assertEqual(meta["item_type"], ITEM_TYPE_SAMPLE)
        self.assertEqual(meta["sample_id"], "sid-1")
        self.assertEqual(
            tree_item_condition_group_id(meta),
            "cg_deadbeef",
        )

    def test_group_meta_uses_condition_group_id(self) -> None:
        from actintrack_app.explorer_sidebar import condition_group_tree_meta

        meta = condition_group_tree_meta("cg_a1b2c3d4")
        self.assertEqual(meta["item_type"], ITEM_TYPE_CONDITION_GROUP)
        self.assertEqual(
            tree_item_condition_group_id(meta),
            "cg_a1b2c3d4",
        )

    def test_rename_group_does_not_change_sample_sidebar_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_project_structure(root)
            record = create_condition_group(root, "Control")
            video = root / "02_676-6-2.mp4"
            _write_test_video(video)
            _batch, row = create_sample_from_data(root, record.id, video)
            row_dict = row if isinstance(row, dict) else dict(row)
            before = sample_sidebar_display_label(row_dict)
            rename_condition_group(root, record.id, "LatB Treatment")
            self.assertEqual(before, "02_676-6-2.mp4")
            self.assertEqual(sample_sidebar_display_label(row_dict), before)


if __name__ == "__main__":
    unittest.main()
