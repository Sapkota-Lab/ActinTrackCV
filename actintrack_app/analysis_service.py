"""Read-only aggregation of tracking/index results by Breed and Sample."""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from actintrack_app.sample_registry import (
    display_sample_label,
    list_samples,
    sanitize_sample_name,
    sync_registry_from_data_files,
)
from actintrack_app.export_naming import motion_index_summary_json_path
from actintrack_app.metadata import load_samples_csv
from actintrack_app.project_manager import get_processed_batch_dir
from actintrack_app.utils import (
    GROUPS,
    METADATA_DIR,
    SAMPLES_CSV,
    STATUS_MOTION_INDEX_FAILED,
    STATUS_MOTION_INDEX_GENERATED,
)

DRAFT_TRACKING_DIR = "draft_tracking"


@dataclass(frozen=True)
class SampleMetrics:
    downward_velocity: Optional[float] = None
    general_movement: Optional[float] = None
    motion_index: Optional[float] = None
    valid_tracks: Optional[int] = None
    valid_steps: Optional[int] = None
    confidence: Optional[float] = None
    result_updated_at: Optional[str] = None
    has_valid_result: bool = False
    failure_reason: str = ""
    of_general_movement: Optional[float] = None
    of_downward_motion: Optional[float] = None
    of_net_y_velocity: Optional[float] = None
    of_directionality_ratio: Optional[float] = None
    of_valid_pixel_fraction: Optional[float] = None
    of_has_valid_result: bool = False
    of_failure_reason: str = ""


@dataclass(frozen=True)
class SampleAnalysisRow:
    breed: str
    sample_label: str
    batch_name: str
    status: str
    data_status: str
    metrics: SampleMetrics = field(default_factory=SampleMetrics)
    sample_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class BreedSummaryRow:
    breed: str
    sample_count: int
    samples_with_results: int
    avg_downward_velocity: Optional[float] = None
    avg_general_movement: Optional[float] = None
    avg_motion_index: Optional[float] = None
    std_downward_velocity: Optional[float] = None
    std_general_movement: Optional[float] = None
    avg_of_general_movement: Optional[float] = None
    avg_of_downward_motion: Optional[float] = None
    avg_of_net_y_velocity: Optional[float] = None
    avg_of_directionality_ratio: Optional[float] = None
    avg_of_valid_pixel_fraction: Optional[float] = None
    samples_with_of_results: int = 0


@dataclass(frozen=True)
class BreedComparisonRow:
    rank: int
    breed: str
    avg_downward_velocity: Optional[float] = None
    avg_general_movement: Optional[float] = None
    avg_motion_index: Optional[float] = None
    valid_sample_count: int = 0


@dataclass(frozen=True)
class AnalysisReport:
    breed_summaries: list[BreedSummaryRow]
    sample_details: list[SampleAnalysisRow]
    breed_comparisons: list[BreedComparisonRow]
    empty_message: str = ""


def _draft_tracking_path(root: Path, data_id: str) -> Path | None:
    from actintrack_app.schema_compat import resolve_draft_tracking_path

    return resolve_draft_tracking_path(root, data_id)


def _draft_optical_flow_path(root: Path, data_id: str) -> Path | None:
    from actintrack_app.schema_compat import resolve_draft_optical_flow_path

    return resolve_draft_optical_flow_path(root, data_id)


def _motion_index_path_for_row(root: Path, row: dict[str, Any]) -> Optional[Path]:
    group = str(row.get("group", "")).strip()
    batch_name = str(row.get("batch_name", "")).strip()
    final_name = str(row.get("final_export_name", "")).strip()
    if not group or not batch_name or not final_name:
        return None
    path = motion_index_summary_json_path(
        get_processed_batch_dir(root, group, batch_name),
        final_name,
    )
    return path if path.is_file() else None


def _parse_tracking_payload(data: dict[str, Any], *, source_path: Path) -> SampleMetrics:
    tracks_used = int(data.get("num_tracks_with_valid_steps", 0) or 0)
    if tracks_used <= 0:
        reason = str(
            data.get("tracking_warning")
            or data.get("track_preview_error")
            or data.get("failure_reason")
            or ""
        ).strip()
        return SampleMetrics(
            has_valid_result=False,
            failure_reason=reason or "Tracking produced no valid steps.",
        )

    downward = float(data.get("downward_velocity_index_um_per_s", 0.0))
    general = float(
        data.get(
            "absolute_velocity_index_um_per_s",
            data.get("general_movement_index_um_per_s", 0.0),
        )
    )
    motion_index = float(data.get("primary_velocity_index_um_per_s", general))
    params = data.get("parameters") or {}
    confidence = None
    if isinstance(params, dict) and params.get("min_template_confidence") is not None:
        try:
            confidence = float(params["min_template_confidence"])
        except (TypeError, ValueError):
            pass

    updated = str(data.get("analysis_timestamp_utc", "")).strip()
    if not updated:
        try:
            mtime = source_path.stat().st_mtime
            updated = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        except OSError:
            updated = None

    return SampleMetrics(
        downward_velocity=downward,
        general_movement=general,
        motion_index=motion_index,
        valid_tracks=tracks_used,
        valid_steps=int(data.get("total_valid_steps", 0) or 0),
        confidence=confidence,
        result_updated_at=updated,
        has_valid_result=True,
    )


def load_tracking_metrics_for_sample(
    root: Path,
    sample_id: str,
    sample_row: Optional[dict[str, Any]] = None,
) -> SampleMetrics:
    """Load saved tracking/index metrics for one sample_id (read-only, no recompute)."""
    root = Path(root).resolve()
    if sample_row is not None:
        finalized = _motion_index_path_for_row(root, sample_row)
        if finalized is not None:
            try:
                data = json.loads(finalized.read_text(encoding="utf-8"))
                return _parse_tracking_payload(data, source_path=finalized)
            except (OSError, json.JSONDecodeError):
                pass

    draft = _draft_tracking_path(root, sample_id)
    if draft is not None and draft.is_file():
        try:
            data = json.loads(draft.read_text(encoding="utf-8"))
            metrics = _parse_tracking_payload(data, source_path=draft)
            if metrics.has_valid_result:
                return metrics
            if metrics.failure_reason:
                return metrics
        except (OSError, json.JSONDecodeError):
            pass

    if sample_row is not None:
        proc_status = str(sample_row.get("processing_status", ""))
        if proc_status == STATUS_MOTION_INDEX_FAILED:
            return SampleMetrics(
                has_valid_result=False,
                failure_reason="Motion index generation failed.",
            )

    return SampleMetrics(has_valid_result=False)


def _parse_optical_flow_payload(data: dict[str, Any]) -> SampleMetrics:
    if not data.get("has_valid_result"):
        reason = str(data.get("failure_reason", "")).strip()
        return SampleMetrics(
            of_has_valid_result=False,
            of_failure_reason=reason or "Optical flow not computed.",
        )

    def _opt_float(key: str) -> Optional[float]:
        value = data.get(key)
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return SampleMetrics(
        of_general_movement=_opt_float("optical_flow_general_movement_um_s"),
        of_downward_motion=_opt_float("optical_flow_downward_motion_um_s"),
        of_net_y_velocity=_opt_float("optical_flow_net_y_velocity_um_s"),
        of_directionality_ratio=_opt_float("optical_flow_directionality_ratio"),
        of_valid_pixel_fraction=_opt_float("optical_flow_valid_pixel_fraction"),
        of_has_valid_result=True,
    )


def load_optical_flow_metrics_for_sample(root: Path, sample_id: str) -> SampleMetrics:
    root = Path(root).resolve()
    draft = _draft_optical_flow_path(root, sample_id)
    if draft is not None:
        try:
            data = json.loads(draft.read_text(encoding="utf-8"))
            return _parse_optical_flow_payload(data)
        except (OSError, json.JSONDecodeError):
            pass
    return SampleMetrics(of_has_valid_result=False)


def _merge_sample_metrics(
    template: SampleMetrics,
    optical_flow: SampleMetrics,
) -> SampleMetrics:
    return SampleMetrics(
        downward_velocity=template.downward_velocity,
        general_movement=template.general_movement,
        motion_index=template.motion_index,
        valid_tracks=template.valid_tracks,
        valid_steps=template.valid_steps,
        confidence=template.confidence,
        result_updated_at=template.result_updated_at,
        has_valid_result=template.has_valid_result,
        failure_reason=template.failure_reason,
        of_general_movement=optical_flow.of_general_movement,
        of_downward_motion=optical_flow.of_downward_motion,
        of_net_y_velocity=optical_flow.of_net_y_velocity,
        of_directionality_ratio=optical_flow.of_directionality_ratio,
        of_valid_pixel_fraction=optical_flow.of_valid_pixel_fraction,
        of_has_valid_result=optical_flow.of_has_valid_result,
        of_failure_reason=optical_flow.of_failure_reason,
    )


def _status_label(
    *,
    has_data: bool,
    metrics: SampleMetrics,
    processing_status: str,
) -> str:
    if not has_data:
        return "No data imported"
    if metrics.has_valid_result:
        if processing_status == STATUS_MOTION_INDEX_GENERATED:
            return "Motion index generated"
        return "Draft tracking result"
    if metrics.failure_reason:
        return "Tracking failed"
    return "No result yet"


def _data_status_label(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No data"
    statuses = {str(r.get("processing_status", "")).strip() for r in rows}
    if len(statuses) == 1:
        return next(iter(statuses)) or "Imported"
    return "Mixed"


def compute_sample_analysis(
    root: Path,
    breed: str,
    batch: dict[str, Any],
    data_rows: list[dict[str, Any]],
) -> SampleAnalysisRow:
    batch_name = str(batch.get("batch_name", ""))
    batch_num = int(batch.get("batch_number", 1) or 1)
    sample_label = display_sample_label(batch_num, batch_name)
    sample_ids = tuple(str(r.get("sample_id", "")).strip() for r in data_rows if r.get("sample_id"))

    if not data_rows:
        return SampleAnalysisRow(
            breed=breed,
            sample_label=sample_label,
            batch_name=batch_name,
            status="No data imported",
            data_status="No data",
            sample_ids=sample_ids,
        )

    primary = data_rows[0]
    primary_id = str(primary.get("sample_id", "")).strip()
    template_metrics = (
        load_tracking_metrics_for_sample(root, primary_id, primary)
        if primary_id
        else SampleMetrics(has_valid_result=False)
    )
    of_metrics = (
        load_optical_flow_metrics_for_sample(root, primary_id)
        if primary_id
        else SampleMetrics(of_has_valid_result=False)
    )
    metrics = _merge_sample_metrics(template_metrics, of_metrics)
    proc_status = str(primary.get("processing_status", "")).strip()
    return SampleAnalysisRow(
        breed=breed,
        sample_label=sample_label,
        batch_name=batch_name,
        status=_status_label(
            has_data=True,
            metrics=metrics,
            processing_status=proc_status,
        ),
        data_status=_data_status_label(data_rows),
        metrics=metrics,
        sample_ids=sample_ids,
    )


def _mean(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _std(values: list[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    return statistics.stdev(values)


def compute_breed_analysis(
    breed: str,
    sample_rows: list[SampleAnalysisRow],
) -> BreedSummaryRow:
    valid = [r for r in sample_rows if r.metrics.has_valid_result]
    downward = [
        r.metrics.downward_velocity
        for r in valid
        if r.metrics.downward_velocity is not None
    ]
    general = [r.metrics.general_movement for r in valid if r.metrics.general_movement is not None]
    motion = [r.metrics.motion_index for r in valid if r.metrics.motion_index is not None]
    of_valid = [r for r in sample_rows if r.metrics.of_has_valid_result]
    of_general = [
        r.metrics.of_general_movement for r in of_valid if r.metrics.of_general_movement is not None
    ]
    of_downward = [
        r.metrics.of_downward_motion for r in of_valid if r.metrics.of_downward_motion is not None
    ]
    of_net_y = [
        r.metrics.of_net_y_velocity for r in of_valid if r.metrics.of_net_y_velocity is not None
    ]
    of_dir = [
        r.metrics.of_directionality_ratio
        for r in of_valid
        if r.metrics.of_directionality_ratio is not None
    ]
    of_valid_frac = [
        r.metrics.of_valid_pixel_fraction
        for r in of_valid
        if r.metrics.of_valid_pixel_fraction is not None
    ]

    return BreedSummaryRow(
        breed=breed,
        sample_count=len(sample_rows),
        samples_with_results=len(valid),
        avg_downward_velocity=_mean(downward),
        avg_general_movement=_mean(general),
        avg_motion_index=_mean(motion),
        std_downward_velocity=_std(downward),
        std_general_movement=_std(general),
        avg_of_general_movement=_mean(of_general),
        avg_of_downward_motion=_mean(of_downward),
        avg_of_net_y_velocity=_mean(of_net_y),
        avg_of_directionality_ratio=_mean(of_dir),
        avg_of_valid_pixel_fraction=_mean(of_valid_frac),
        samples_with_of_results=len(of_valid),
    )


def _comparison_sort_key(row: BreedSummaryRow) -> tuple[float, float, float, str]:
    general = row.avg_general_movement if row.avg_general_movement is not None else float("-inf")
    downward = row.avg_downward_velocity if row.avg_downward_velocity is not None else float("-inf")
    motion = row.avg_motion_index if row.avg_motion_index is not None else float("-inf")
    return (general, motion, downward, row.breed)


def build_breed_comparisons(summaries: list[BreedSummaryRow]) -> list[BreedComparisonRow]:
    ranked = sorted(
        [s for s in summaries if s.samples_with_results > 0],
        key=_comparison_sort_key,
        reverse=True,
    )
    out: list[BreedComparisonRow] = []
    for idx, summary in enumerate(ranked, start=1):
        out.append(
            BreedComparisonRow(
                rank=idx,
                breed=summary.breed,
                avg_downward_velocity=summary.avg_downward_velocity,
                avg_general_movement=summary.avg_general_movement,
                avg_motion_index=summary.avg_motion_index,
                valid_sample_count=summary.samples_with_results,
            )
        )
    return out


def build_analysis_report(root: Path) -> AnalysisReport:
    """Aggregate tracking/index metrics for all breeds and samples in a workspace."""
    root = Path(root).resolve()
    sync_registry_from_data_files(root)
    df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)

    breed_summaries: list[BreedSummaryRow] = []
    sample_details: list[SampleAnalysisRow] = []

    breeds = [g for g in GROUPS]
    any_samples = False

    for breed in breeds:
        batches = list_samples(root, breed)
        if batches:
            any_samples = True

        breed_sample_rows: list[SampleAnalysisRow] = []
        for batch in batches:
            safe = sanitize_sample_name(str(batch.get("batch_name", "")))
            data_rows = []
            if not df.empty and "group" in df.columns:
                sub = df[
                    (df["group"] == breed)
                    & (df["batch_name"].astype(str).apply(sanitize_sample_name) == safe)
                ]
                data_rows = [row.to_dict() for _, row in sub.iterrows()]
            row = compute_sample_analysis(root, breed, batch, data_rows)
            breed_sample_rows.append(row)
            sample_details.append(row)

        breed_summaries.append(compute_breed_analysis(breed, breed_sample_rows))

    empty_message = ""
    if not any_samples:
        empty_message = (
            "No samples found in this workspace. Create samples and import data "
            "to populate the analysis view."
        )

    return AnalysisReport(
        breed_summaries=breed_summaries,
        sample_details=sample_details,
        breed_comparisons=build_breed_comparisons(breed_summaries),
        empty_message=empty_message,
    )
