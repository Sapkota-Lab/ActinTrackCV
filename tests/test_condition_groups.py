"""Tests for user-defined Condition Groups with stable IDs (Phase 2)."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from actintrack_app.analysis_service import build_analysis_report
from actintrack_app.batch_manager import get_batch_by_name
from actintrack_app.condition_group_manager import (
    create_condition_group,
    delete_empty_condition_group,
    display_export_name_for_row,
    ensure_condition_groups_initialized,
    get_condition_group_name,
    get_condition_group_record,
    is_condition_group_id,
    list_condition_group_ids,
    list_condition_group_records,
    migrate_workspace_condition_groups_to_ids,
    normalize_condition_group_name,
    rename_condition_group,
    resolve_condition_group_id,
)
from actintrack_app.metadata import load_samples_csv
from actintrack_app.project_manager import create_project_structure
from actintrack_app.sample_service import create_sample_from_data
from actintrack_app.schema_compat import load_sample_registry_as_v1, read_workspace_schema_version
from actintrack_app.utils import CONDITION_GROUPS_JSON, METADATA_DIR, RAW_DIR, SCHEMA_V2

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "v1_workspace"


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


class ConditionGroupManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _groups_payload(self) -> dict:
        return json.loads(
            (self.root / METADATA_DIR / CONDITION_GROUPS_JSON).read_text(encoding="utf-8")
        )

    def test_new_workspace_starts_with_no_groups(self) -> None:
        create_project_structure(self.root)
        self.assertEqual(read_workspace_schema_version(self.root), SCHEMA_V2)
        self.assertEqual(list_condition_group_records(self.root), [])
        self.assertEqual(self._groups_payload().get("groups"), [])

    def test_create_generates_stable_id_and_object_schema(self) -> None:
        create_project_structure(self.root)
        record = create_condition_group(self.root, "  Control  ")
        self.assertTrue(is_condition_group_id(record.id))
        self.assertEqual(record.name, "Control")
        payload = self._groups_payload()
        self.assertIsInstance(payload["groups"][0], dict)
        self.assertEqual(payload["groups"][0]["id"], record.id)
        self.assertEqual(payload["groups"][0]["name"], "Control")

    def test_blank_name_rejected(self) -> None:
        create_project_structure(self.root)
        with self.assertRaises(ValueError):
            normalize_condition_group_name("   ")

    def test_duplicate_name_rejected(self) -> None:
        create_project_structure(self.root)
        create_condition_group(self.root, "Control")
        with self.assertRaises(ValueError):
            create_condition_group(self.root, "control")

    def test_rename_changes_name_preserves_id(self) -> None:
        create_project_structure(self.root)
        record = create_condition_group(self.root, "Control")
        renamed = rename_condition_group(self.root, record.id, "Control untreated")
        self.assertEqual(renamed, "Control untreated")
        reloaded = get_condition_group_record(self.root, record.id)
        assert reloaded is not None
        self.assertEqual(reloaded.id, record.id)
        self.assertEqual(reloaded.name, "Control untreated")

    def test_rename_preserves_sample_assignment(self) -> None:
        create_project_structure(self.root)
        record = create_condition_group(self.root, "Control")
        video = self.root / "clip.mp4"
        _write_test_video(video)
        batch, row = create_sample_from_data(self.root, record.id, video)
        self.assertIsNotNone(get_batch_by_name(self.root, record.id, batch["batch_name"]))

        rename_condition_group(self.root, record.id, "LatB Treatment")
        self.assertIsNotNone(
            get_batch_by_name(self.root, record.id, batch["batch_name"])
        )
        self.assertEqual(
            get_condition_group_name(self.root, record.id),
            "LatB Treatment",
        )
        df = load_samples_csv(self.root / METADATA_DIR / "data_files.csv")
        self.assertEqual(str(df.iloc[0]["condition_group_id"]), record.id)
        self.assertEqual(str(df.iloc[0]["group"]), record.id)
        self.assertEqual(
            get_condition_group_name(self.root, record.id),
            "LatB Treatment",
        )
        self.assertTrue(str(df.iloc[0]["stored_path"]).startswith(f"{RAW_DIR}/{record.id}/"))

    def test_delete_empty_group_by_id_succeeds(self) -> None:
        create_project_structure(self.root)
        record = create_condition_group(self.root, "Empty Group")
        delete_empty_condition_group(self.root, record.id)
        self.assertEqual(list_condition_group_ids(self.root), [])

    def test_delete_nonempty_group_blocked(self) -> None:
        create_project_structure(self.root)
        record = create_condition_group(self.root, "Control")
        video = self.root / "clip.mp4"
        _write_test_video(video)
        create_sample_from_data(self.root, record.id, video)
        with self.assertRaises(ValueError):
            delete_empty_condition_group(self.root, record.id)

    def test_legacy_workspace_migrates_name_based_groups(self) -> None:
        shutil.copytree(FIXTURES / "metadata", self.root / "metadata")
        (self.root / "raw" / "1_WT_218").mkdir(parents=True)
        (self.root / "processed").mkdir()
        (self.root / "previews").mkdir()
        self.assertTrue(migrate_workspace_condition_groups_to_ids(self.root))
        records = list_condition_group_records(self.root)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].name, "1_WT_218")
        self.assertTrue(is_condition_group_id(records[0].id))
        registry = load_sample_registry_as_v1(self.root)
        self.assertIn(records[0].id, registry)
        self.assertNotIn("1_WT_218", registry)

    def test_analysis_uses_display_name_not_id(self) -> None:
        create_project_structure(self.root)
        record_a = create_condition_group(self.root, "Group A")
        create_condition_group(self.root, "Group B")
        video = self.root / "clip.mp4"
        _write_test_video(video)
        create_sample_from_data(self.root, record_a.id, video)
        report = build_analysis_report(self.root)
        breeds = {row.breed for row in report.breed_summaries if row.sample_count}
        self.assertEqual(breeds, {"Group A"})
        self.assertTrue(all(not is_condition_group_id(row.breed) for row in report.breed_summaries))

    def test_display_export_name_refreshes_after_group_rename(self) -> None:
        create_project_structure(self.root)
        record = create_condition_group(self.root, "Control")
        video = self.root / "clip.mp4"
        _write_test_video(video)
        _batch, row = create_sample_from_data(self.root, record.id, video)
        row_dict = row if isinstance(row, dict) else dict(row)
        before = display_export_name_for_row(self.root, row_dict)
        self.assertTrue(before.startswith("Control--"))

        rename_condition_group(self.root, record.id, "Control untreated")
        df = load_samples_csv(self.root / METADATA_DIR / "data_files.csv")
        refreshed = display_export_name_for_row(self.root, df.iloc[0].to_dict())
        self.assertTrue(refreshed.startswith("Control untreated--"))
        self.assertNotEqual(before, refreshed)
        # Stored auto export name remains from import time (display-only refresh).
        self.assertTrue(str(df.iloc[0]["auto_export_name"]).startswith("Control--"))

    def test_resolve_id_from_name(self) -> None:
        create_project_structure(self.root)
        record = create_condition_group(self.root, "Control")
        self.assertEqual(resolve_condition_group_id(self.root, "control"), record.id)
        self.assertEqual(resolve_condition_group_id(self.root, record.id), record.id)


if __name__ == "__main__":
    unittest.main()
