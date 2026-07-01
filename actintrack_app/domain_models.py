"""Domain records for Breed / Sample (registry) / Data (imported file)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DataFileRecord:
    """One imported AVI/MP4 (or legacy image) data file."""

    data_id: str
    breed: str
    sample_number: int
    sample_name: str
    sample_id: str  # registry sample stable ID (v1 batch_id)
    condition_group_id: str = ""
    original_filename: str = ""
    stored_path: str = ""
    file_type: str = ""
    is_video: str = "false"
    is_image_sequence: str = "false"
    frame_number: str = "0"
    auto_export_name: str = ""
    custom_export_name: str = ""
    final_export_name: str = ""
    import_date: str = ""
    processing_status: str = ""
    annotation_source: str = ""
    review_status: str = ""
    notes: str = ""

    def to_v2_dict(self) -> dict[str, str]:
        return {
            "data_id": self.data_id,
            "condition_group_id": self.condition_group_id,
            "breed": self.breed,
            "sample_number": str(self.sample_number),
            "sample_name": self.sample_name,
            "sample_id": self.sample_id,
            "original_filename": self.original_filename,
            "stored_path": self.stored_path,
            "file_type": self.file_type,
            "is_video": self.is_video,
            "is_image_sequence": self.is_image_sequence,
            "frame_number": self.frame_number,
            "auto_export_name": self.auto_export_name,
            "custom_export_name": self.custom_export_name,
            "final_export_name": self.final_export_name,
            "import_date": self.import_date,
            "processing_status": self.processing_status,
            "annotation_source": self.annotation_source,
            "review_status": self.review_status,
            "notes": self.notes,
        }

    def to_v1_dict(self) -> dict[str, str]:
        """Legacy samples.csv row shape (data_id exposed as sample_id)."""
        d = self.to_v2_dict()
        return {
            "sample_id": d["data_id"],
            "condition_group_id": d["condition_group_id"],
            "group": d["condition_group_id"] or d["breed"],
            "batch_number": d["sample_number"],
            "batch_name": d["sample_name"],
            "batch_id": d["sample_id"],
            "original_filename": d["original_filename"],
            "stored_path": d["stored_path"],
            "file_type": d["file_type"],
            "is_video": d["is_video"],
            "is_image_sequence": d["is_image_sequence"],
            "frame_number": d["frame_number"],
            "auto_export_name": d["auto_export_name"],
            "custom_export_name": d["custom_export_name"],
            "final_export_name": d["final_export_name"],
            "import_date": d["import_date"],
            "processing_status": d["processing_status"],
            "annotation_source": d["annotation_source"],
            "review_status": d["review_status"],
            "notes": d["notes"],
        }

    @classmethod
    def from_v1_dict(cls, row: dict[str, Any]) -> DataFileRecord:
        if row.get("data_id"):
            data_id = str(row["data_id"])
            registry_id = str(row.get("sample_id", ""))
        else:
            data_id = str(row.get("sample_id", ""))
            registry_id = str(row.get("batch_id", ""))
        return cls(
            data_id=data_id,
            breed=str(row.get("breed") or row.get("group", "")),
            condition_group_id=str(
                row.get("condition_group_id") or row.get("group") or row.get("breed", "")
            ),
            sample_number=int(str(row.get("sample_number") or row.get("batch_number", 1) or 1)),
            sample_name=str(row.get("sample_name") or row.get("batch_name", "")),
            sample_id=registry_id,
            original_filename=str(row.get("original_filename", "")),
            stored_path=str(row.get("stored_path", "")),
            file_type=str(row.get("file_type", "")),
            is_video=str(row.get("is_video", "false")),
            is_image_sequence=str(row.get("is_image_sequence", "false")),
            frame_number=str(row.get("frame_number", "0")),
            auto_export_name=str(row.get("auto_export_name", "")),
            custom_export_name=str(row.get("custom_export_name", "")),
            final_export_name=str(row.get("final_export_name", "")),
            import_date=str(row.get("import_date", "")),
            processing_status=str(row.get("processing_status", "")),
            annotation_source=str(row.get("annotation_source", "")),
            review_status=str(row.get("review_status", "")),
            notes=str(row.get("notes", "")),
        )


@dataclass
class SampleRegistryRecord:
    """Registry entry for one biological sample (UI Sample)."""

    breed: str
    sample_number: int
    sample_name: str
    sample_id: str
    condition_group_id: str = ""
    contains_video: bool = False
    video_file_count: int = 0
    image_file_count: int = 0
    data_file_count: int = 0
    contains_data: bool = False
    created_date: str = ""
    renamed_date: str | None = None
    notes: str = ""
    auto_generated_name: bool = False
    source_filename: str = ""

    def to_v2_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "breed": self.breed,
            "condition_group_id": self.condition_group_id,
            "sample_number": self.sample_number,
            "sample_name": self.sample_name,
            "sample_id": self.sample_id,
            "contains_video": self.contains_video,
            "video_file_count": self.video_file_count,
            "image_file_count": self.image_file_count,
            "data_file_count": self.data_file_count,
            "contains_data": self.contains_data,
            "created_date": self.created_date,
            "renamed_date": self.renamed_date,
            "notes": self.notes,
        }
        if self.auto_generated_name:
            d["auto_generated_name"] = True
        if self.source_filename:
            d["source_filename"] = self.source_filename
        return d

    def to_v1_dict(self) -> dict[str, Any]:
        d = self.to_v2_dict()
        out: dict[str, Any] = {
            "group": d.get("condition_group_id") or d["breed"],
            "condition_group_id": d.get("condition_group_id", ""),
            "batch_number": d["sample_number"],
            "batch_name": d["sample_name"],
            "batch_id": d["sample_id"],
            "contains_video": d["contains_video"],
            "video_file_count": d["video_file_count"],
            "image_file_count": d["image_file_count"],
            "data_file_count": d["data_file_count"],
            "contains_data": d["contains_data"],
            "created_date": d["created_date"],
            "renamed_date": d["renamed_date"],
            "notes": d["notes"],
        }
        if d.get("auto_generated_name"):
            out["auto_generated_name"] = True
        if d.get("source_filename"):
            out["source_filename"] = d["source_filename"]
        return out

    @classmethod
    def from_v1_dict(cls, entry: dict[str, Any], breed: str) -> SampleRegistryRecord:
        return cls(
            breed=str(entry.get("breed") or entry.get("group", breed)),
            condition_group_id=str(
                entry.get("condition_group_id") or entry.get("group") or breed
            ),
            sample_number=int(entry.get("sample_number") or entry.get("batch_number", 1) or 1),
            sample_name=str(entry.get("sample_name") or entry.get("batch_name", "")),
            sample_id=str(entry.get("sample_id") or entry.get("batch_id", "")),
            contains_video=bool(entry.get("contains_video", False)),
            video_file_count=int(entry.get("video_file_count", 0) or 0),
            image_file_count=int(entry.get("image_file_count", 0) or 0),
            data_file_count=int(entry.get("data_file_count", 0) or 0),
            contains_data=bool(entry.get("contains_data", False)),
            created_date=str(entry.get("created_date", entry.get("created", ""))),
            renamed_date=entry.get("renamed_date"),
            notes=str(entry.get("notes", "")),
            auto_generated_name=bool(entry.get("auto_generated_name", False)),
            source_filename=str(entry.get("source_filename", "")),
        )
