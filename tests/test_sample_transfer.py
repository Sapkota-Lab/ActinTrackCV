"""Tests for moving Samples between Condition Groups (Phase 4B)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from actintrack_app.batch_manager import get_batch_by_name, list_batches
from actintrack_app.condition_group_manager import create_condition_group
from actintrack_app.explorer_sidebar import (
    is_draggable_sample_meta,
    is_valid_sample_drop_target_meta,
    sample_tree_meta,
)
from actintrack_app.metadata import (
    get_sample_annotation,
    load_samples_csv,
    save_sample_crop_annotation,
)
from actintrack_app.project_manager import create_project_structure, get_raw_batch_dir
from actintrack_app.sample_service import create_sample_from_data
from actintrack_app.sample_transfer import (
    MoveSampleResult,
    SampleMoveError,
    move_sample_to_condition_group,
)
from actintrack_app.schema_compat import load_sample_registry_as_v1
from actintrack_app.utils import CROP_METADATA_JSON, METADATA_DIR, RAW_DIR, SAMPLES_CSV


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


class SampleTransferTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        create_project_structure(self.root)
        self.group_a = create_condition_group(self.root, "Control")
        self.group_b = create_condition_group(self.root, "LatB Treatment")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _import_sample(self, group_id: str, name: str) -> dict:
        video = self.root / name
        _write_test_video(video)
        _batch, row = create_sample_from_data(self.root, group_id, video)
        return row if isinstance(row, dict) else dict(row)

    def test_move_sample_updates_metadata_and_raw_path(self) -> None:
        row = self._import_sample(self.group_a.id, "move_me.mp4")
        sample_id = str(row["sample_id"])
        batch_name = str(row["batch_name"])
        old_raw = get_raw_batch_dir(self.root, self.group_a.id, batch_name)
        self.assertTrue(old_raw.is_dir())

        result = move_sample_to_condition_group(
            self.root, sample_id, self.group_b.id
        )
        self.assertTrue(result.moved)
        self.assertEqual(result.source_condition_group_id, self.group_a.id)
        self.assertEqual(result.target_condition_group_id, self.group_b.id)

        df = load_samples_csv(self.root / METADATA_DIR / SAMPLES_CSV)
        moved = df[df["sample_id"].astype(str) == sample_id].iloc[0]
        self.assertEqual(str(moved["group"]), self.group_b.id)
        self.assertEqual(str(moved["condition_group_id"]), self.group_b.id)
        self.assertIn(f"{RAW_DIR}/{self.group_b.id}/", str(moved["stored_path"]))
        self.assertFalse(old_raw.exists())
        new_raw = get_raw_batch_dir(self.root, self.group_b.id, batch_name)
        self.assertTrue(new_raw.is_dir())
        self.assertTrue((self.root / str(moved["stored_path"])).is_file())

        registry = load_sample_registry_as_v1(self.root)
        self.assertIsNone(get_batch_by_name(self.root, self.group_a.id, batch_name))
        self.assertIsNotNone(get_batch_by_name(self.root, self.group_b.id, batch_name))
        self.assertEqual(list_batches(self.root, self.group_a.id), [])

    def test_move_sample_persists_after_reload(self) -> None:
        row = self._import_sample(self.group_a.id, "persist.mp4")
        sample_id = str(row["sample_id"])
        move_sample_to_condition_group(self.root, sample_id, self.group_b.id)

        df = load_samples_csv(self.root / METADATA_DIR / SAMPLES_CSV)
        reloaded = df[df["sample_id"].astype(str) == sample_id].iloc[0]
        self.assertEqual(str(reloaded["group"]), self.group_b.id)

    def test_same_group_move_is_no_op(self) -> None:
        row = self._import_sample(self.group_a.id, "noop.mp4")
        sample_id = str(row["sample_id"])
        stored_before = str(row["stored_path"])

        result = move_sample_to_condition_group(
            self.root, sample_id, self.group_a.id
        )
        self.assertIsInstance(result, MoveSampleResult)
        self.assertFalse(result.moved)

        df = load_samples_csv(self.root / METADATA_DIR / SAMPLES_CSV)
        current = df[df["sample_id"].astype(str) == sample_id].iloc[0]
        self.assertEqual(str(current["stored_path"]), stored_before)
        self.assertEqual(
            len(list_batches(self.root, self.group_a.id)),
            1,
        )

    def test_blocks_batch_name_collision_in_target_group(self) -> None:
        row_a = self._import_sample(self.group_a.id, "shared_name.mp4")
        self._import_sample(self.group_b.id, "shared_name.mp4")
        batch_name = str(row_a["batch_name"])
        sample_id = str(row_a["sample_id"])

        with self.assertRaises(SampleMoveError) as ctx:
            move_sample_to_condition_group(self.root, sample_id, self.group_b.id)
        self.assertIn(batch_name, str(ctx.exception))

        df = load_samples_csv(self.root / METADATA_DIR / SAMPLES_CSV)
        still = df[df["sample_id"].astype(str) == sample_id].iloc[0]
        self.assertEqual(str(still["group"]), self.group_a.id)
        self.assertTrue(
            get_raw_batch_dir(self.root, self.group_a.id, str(row_a["batch_name"])).is_dir()
        )

    def test_crop_metadata_survives_move(self) -> None:
        row = self._import_sample(self.group_a.id, "roi_move.mp4")
        sample_id = str(row["sample_id"])
        crop_path = self.root / METADATA_DIR / CROP_METADATA_JSON
        save_sample_crop_annotation(
            crop_path,
            sample_id,
            {"sample_id": sample_id, "notes": "moved", "status": "roi_marked"},
        )
        move_sample_to_condition_group(self.root, sample_id, self.group_b.id)
        ann = get_sample_annotation(self.root, sample_id)
        self.assertIsNotNone(ann)
        assert ann is not None
        self.assertEqual(str(ann.get("notes")), "moved")


class ExplorerDragDropMetaTests(unittest.TestCase):
    def test_only_sample_rows_are_draggable(self) -> None:
        row = {"sample_id": "sid", "group": "cg_x", "item_type": "sample"}
        self.assertTrue(is_draggable_sample_meta(sample_tree_meta(row)))
        self.assertFalse(is_draggable_sample_meta({"item_type": "empty_sample"}))
        self.assertFalse(is_draggable_sample_meta({"item_type": "condition_group"}))

    def test_valid_drop_targets_include_group_and_sample_rows(self) -> None:
        self.assertTrue(
            is_valid_sample_drop_target_meta(
                {"item_type": "condition_group", "condition_group_id": "cg_a"}
            )
        )
        self.assertTrue(
            is_valid_sample_drop_target_meta(
                {"item_type": "sample", "group": "cg_a", "sample_id": "s1"}
            )
        )
        self.assertFalse(is_valid_sample_drop_target_meta(None))


if __name__ == "__main__":
    unittest.main()
