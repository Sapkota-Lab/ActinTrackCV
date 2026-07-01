"""Tests for schema v1/v2 compatibility and migration."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from actintrack_app.domain_models import DataFileRecord
from actintrack_app.metadata import (
    get_sample_annotation,
    load_crop_metadata,
    load_samples_csv,
    migrate_workspace_schema,
    save_crop_metadata,
    save_sample_crop_annotation,
)
from actintrack_app.project_manager import create_project_structure
from actintrack_app.schema_compat import (
    migrate_workspace_to_v2,
    read_workspace_schema_version,
)
from actintrack_app.sample_registry import list_samples
from actintrack_app.utils import (
    DATA_FILES_CSV,
    METADATA_DIR,
    SAMPLE_REGISTRY_JSON,
    SAMPLES_CSV,
    SCHEMA_V2,
    WORKSPACE_JSON,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "v1_workspace"


class SchemaCompatTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        shutil.copytree(FIXTURES / "metadata", self.root / "metadata")
        (self.root / "raw").mkdir()
        (self.root / "processed").mkdir()
        (self.root / "previews").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_v1_load_returns_legacy_columns(self) -> None:
        self.assertEqual(read_workspace_schema_version(self.root), 1)
        df = load_samples_csv(self.root / METADATA_DIR / SAMPLES_CSV)
        self.assertEqual(str(df.iloc[0]["sample_id"]), "WT218_0001")
        self.assertEqual(str(df.iloc[0]["group"]), "1_WT_218")
        self.assertEqual(str(df.iloc[0]["batch_id"]), "1_WT_218_B001")

    def test_data_file_record_roundtrip(self) -> None:
        row = load_samples_csv(self.root / METADATA_DIR / SAMPLES_CSV).iloc[0].to_dict()
        record = DataFileRecord.from_v1_dict(row)
        self.assertEqual(record.data_id, "WT218_0001")
        self.assertEqual(record.breed, "1_WT_218")
        self.assertEqual(record.sample_id, "1_WT_218_B001")
        back = record.to_v1_dict()
        self.assertEqual(back["sample_id"], "WT218_0001")
        self.assertEqual(back["batch_id"], "1_WT_218_B001")

    def test_migrate_to_v2_writes_canonical_files(self) -> None:
        self.assertTrue(migrate_workspace_to_v2(self.root))
        self.assertEqual(read_workspace_schema_version(self.root), SCHEMA_V2)
        self.assertTrue((self.root / METADATA_DIR / DATA_FILES_CSV).is_file())
        self.assertTrue((self.root / METADATA_DIR / SAMPLE_REGISTRY_JSON).is_file())
        self.assertTrue((self.root / METADATA_DIR / WORKSPACE_JSON).is_file())
        self.assertTrue((self.root / METADATA_DIR / f"{SAMPLES_CSV}.v1.bak").is_file())

        df = load_samples_csv(self.root / METADATA_DIR / DATA_FILES_CSV)
        self.assertEqual(str(df.iloc[0]["sample_id"]), "WT218_0001")

        samples = list_samples(self.root, "1_WT_218")
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0]["batch_id"], "1_WT_218_B001")

    def test_migrate_idempotent(self) -> None:
        migrate_workspace_to_v2(self.root)
        self.assertFalse(migrate_workspace_to_v2(self.root))

    def test_crop_metadata_v2_save(self) -> None:
        migrate_workspace_to_v2(self.root)
        crop_path = self.root / METADATA_DIR / "crop_metadata.json"
        save_sample_crop_annotation(
            crop_path,
            "WT218_0001",
            {"sample_id": "WT218_0001", "group": "1_WT_218", "status": "roi_marked"},
        )
        loaded = load_crop_metadata(crop_path)
        self.assertIn("WT218_0001", loaded["samples"])
        ann = get_sample_annotation(self.root, "WT218_0001")
        self.assertIsNotNone(ann)
        self.assertEqual(ann.get("status"), "roi_marked")

    def test_new_workspace_is_v2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_project_structure(root)
            self.assertEqual(read_workspace_schema_version(root), SCHEMA_V2)
            self.assertTrue((root / METADATA_DIR / DATA_FILES_CSV).is_file())
            from actintrack_app.condition_group_manager import list_condition_group_records

            self.assertEqual(list_condition_group_records(root), [])

    def test_migrate_workspace_schema_end_to_end(self) -> None:
        migrate_workspace_schema(self.root)
        self.assertEqual(read_workspace_schema_version(self.root), SCHEMA_V2)
        raw = json.loads(
            (self.root / METADATA_DIR / SAMPLE_REGISTRY_JSON).read_text(encoding="utf-8")
        )
        self.assertTrue(any("1_WT_218" in str(v) for v in raw.values()))
        self.assertTrue(all(str(k).startswith("cg_") for k in raw.keys()))


class SmokeTests(unittest.TestCase):
    def test_main_window_import(self) -> None:
        from actintrack_app.gui import MainWindow

        self.assertIsNotNone(MainWindow)


if __name__ == "__main__":
    unittest.main()
