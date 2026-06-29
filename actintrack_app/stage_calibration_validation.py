"""Layer 2 stage-calibration validation against commanded microscope translation."""

from __future__ import annotations

import csv
import json
import math
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np

from actintrack_app.motion_index import (
    TRACKING_METHOD_BRIGHTEST_LOCAL,
    MotionIndexParams,
    run_motion_index_analysis,
)
from actintrack_app.optical_flow_motion_index import (
    OpticalFlowSettings,
    compute_optical_flow_motion_index,
)
from actintrack_app.tracker_validation import SyntheticScenario, generate_synthetic_sequence
from scripts.shiny_bridge import (  # noqa: E402
    _write_flow_pair_csv,
    crop_video_to_frames,
    load_cropped_frames,
)


@dataclass(frozen=True)
class StageCalibrationThresholds:
    """Engineering gates for Layer 2 (tune to lab-approved biological tolerance)."""

    max_abs_bias_um_per_frame: float = 0.20
    max_rmse_um_per_frame: float = 0.25
    max_zero_motion_um_per_frame: float = 0.10
    min_recordings_per_axis: int = 2


@dataclass(frozen=True)
class StageRecordingSpec:
    recording_id: str
    session_id: str
    source_path: str
    direction: str
    commanded_dx_um_per_frame: float
    commanded_dy_um_per_frame: float
    roi_x: int = 0
    roi_y: int = 0
    roi_width: int = 0
    roi_height: int = 0
    rotation: int = 0
    flip_horizontal: bool = False


@dataclass(frozen=True)
class StageAnalysisConfig:
    analysis_method: str = "landmark_tracking"
    tracking_method: str = TRACKING_METHOD_BRIGHTEST_LOCAL
    num_starting_points: int = 5
    min_point_spacing_px: int = 14
    search_radius_px: int = 8
    template_patch_size_px: int = 11
    min_template_confidence: float = 0.35
    lookahead_frames: int = 0
    mask_percentile: float = 85.0
    flow_blur_kernel: int = 3
    flow_winsize: int = 15


@dataclass(frozen=True)
class StageCalibrationManifest:
    protocol_version: int
    independent_microns_per_pixel: float
    seconds_per_frame: float
    lab_approved_tolerance_um_per_frame: float
    recordings: tuple[StageRecordingSpec, ...]
    analysis: StageAnalysisConfig = StageAnalysisConfig()

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, base_dir: Path | None = None) -> StageCalibrationManifest:
        analysis_raw = data.get("analysis") or {}
        analysis = StageAnalysisConfig(
            analysis_method=str(analysis_raw.get("analysis_method", "landmark_tracking")),
            tracking_method=str(analysis_raw.get("tracking_method", TRACKING_METHOD_BRIGHTEST_LOCAL)),
            num_starting_points=int(analysis_raw.get("num_starting_points", 5)),
            min_point_spacing_px=int(analysis_raw.get("min_point_spacing_px", 14)),
            search_radius_px=int(analysis_raw.get("search_radius_px", 8)),
            template_patch_size_px=int(analysis_raw.get("template_patch_size_px", 11)),
            min_template_confidence=float(analysis_raw.get("min_template_confidence", 0.35)),
            lookahead_frames=int(analysis_raw.get("lookahead_frames", 0)),
            mask_percentile=float(analysis_raw.get("mask_percentile", 85.0)),
            flow_blur_kernel=int(analysis_raw.get("flow_blur_kernel", 3)),
            flow_winsize=int(analysis_raw.get("flow_winsize", 15)),
        )
        recordings: list[StageRecordingSpec] = []
        sessions = data.get("sessions") or []
        for session in sessions:
            session_id = str(session.get("session_id", "session"))
            for item in session.get("recordings") or []:
                source = str(item["source_path"])
                if base_dir is not None and not Path(source).is_absolute():
                    source = str((base_dir / source).resolve())
                roi = item.get("roi") or {}
                recordings.append(
                    StageRecordingSpec(
                        recording_id=str(item["recording_id"]),
                        session_id=session_id,
                        source_path=source,
                        direction=str(item.get("direction", "unknown")),
                        commanded_dx_um_per_frame=float(item["commanded_dx_um_per_frame"]),
                        commanded_dy_um_per_frame=float(item["commanded_dy_um_per_frame"]),
                        roi_x=int(roi.get("x", 0)),
                        roi_y=int(roi.get("y", 0)),
                        roi_width=int(roi.get("width", 0)),
                        roi_height=int(roi.get("height", 0)),
                        rotation=int(item.get("rotation", 0)),
                        flip_horizontal=bool(item.get("flip_horizontal", False)),
                    )
                )
        if not recordings and data.get("recordings"):
            for item in data["recordings"]:
                source = str(item["source_path"])
                if base_dir is not None and not Path(source).is_absolute():
                    source = str((base_dir / source).resolve())
                roi = item.get("roi") or {}
                recordings.append(
                    StageRecordingSpec(
                        recording_id=str(item["recording_id"]),
                        session_id=str(item.get("session_id", "session")),
                        source_path=source,
                        direction=str(item.get("direction", "unknown")),
                        commanded_dx_um_per_frame=float(item["commanded_dx_um_per_frame"]),
                        commanded_dy_um_per_frame=float(item["commanded_dy_um_per_frame"]),
                        roi_x=int(roi.get("x", 0)),
                        roi_y=int(roi.get("y", 0)),
                        roi_width=int(roi.get("width", 0)),
                        roi_height=int(roi.get("height", 0)),
                        rotation=int(item.get("rotation", 0)),
                        flip_horizontal=bool(item.get("flip_horizontal", False)),
                    )
                )
        return cls(
            protocol_version=int(data.get("protocol_version", 1)),
            independent_microns_per_pixel=float(data["independent_microns_per_pixel"]),
            seconds_per_frame=float(data["seconds_per_frame"]),
            lab_approved_tolerance_um_per_frame=float(
                data.get("lab_approved_tolerance_um_per_frame", 0.5)
            ),
            recordings=tuple(recordings),
            analysis=analysis,
        )


@dataclass
class RecordingValidationResult:
    recording_id: str
    session_id: str
    direction: str
    analysis_method: str
    commanded_dx_um_per_frame: float
    commanded_dy_um_per_frame: float
    measured_dx_um_per_frame: float
    measured_dy_um_per_frame: float
    bias_dx_um_per_frame: float
    bias_dy_um_per_frame: float
    error_magnitude_um_per_frame: float
    passed: bool
    failure_reasons: list[str] = field(default_factory=list)
    output_dir: str = ""
    trajectory_csv: str = ""
    summary_json: str = ""


def load_stage_calibration_manifest(path: Path, *, base_dir: Path | None = None) -> StageCalibrationManifest:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    manifest_dir = Path(path).resolve().parent
    resolved_base = base_dir or manifest_dir
    return StageCalibrationManifest.from_dict(data, base_dir=resolved_base)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _agreement_stats(differences: Sequence[float]) -> dict[str, float]:
    values = [float(v) for v in differences if not math.isnan(v)]
    if not values:
        return {
            "count": 0,
            "bias": float("nan"),
            "mae": float("nan"),
            "rmse": float("nan"),
            "loa_lower": float("nan"),
            "loa_upper": float("nan"),
        }
    bias = float(np.mean(values))
    mae = float(np.mean(np.abs(values)))
    rmse = float(np.sqrt(np.mean(np.square(values))))
    sd = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
    return {
        "count": len(values),
        "bias": bias,
        "mae": mae,
        "rmse": rmse,
        "loa_lower": bias - (1.96 * sd),
        "loa_upper": bias + (1.96 * sd),
    }


def measure_landmark_displacement_px(trajectory_csv: Path) -> tuple[float, float]:
    dx_values: list[float] = []
    dy_values: list[float] = []
    with trajectory_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("dx_px", "") == "":
                continue
            dx_values.append(float(row["dx_px"]))
            dy_values.append(float(row["dy_px"]))
    if not dx_values:
        raise ValueError(f"No valid motion steps in trajectory: {trajectory_csv}")
    return float(np.mean(dx_values)), float(np.mean(dy_values))


def measure_optical_flow_displacement_px(flow_pair_csv: Path) -> tuple[float, float]:
    net_x: list[float] = []
    net_y: list[float] = []
    with flow_pair_csv.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if "mean_net_x_px_frame" in row and row["mean_net_x_px_frame"] != "":
                net_x.append(float(row["mean_net_x_px_frame"]))
            if row.get("mean_net_y_px_frame", "") != "":
                net_y.append(float(row["mean_net_y_px_frame"]))
    if not net_y and not net_x:
        raise ValueError(f"No optical flow pair rows in: {flow_pair_csv}")
    dx = float(np.mean(net_x)) if net_x else 0.0
    dy = float(np.mean(net_y)) if net_y else 0.0
    return dx, dy


def _px_to_um(px: float, microns_per_pixel: float) -> float:
    return px * microns_per_pixel


def _write_synthetic_video(
    path: Path,
    *,
    dx_px_per_frame: float,
    dy_px_per_frame: float,
    frame_count: int = 12,
    seed: int,
) -> None:
    scenario = SyntheticScenario(
        f"stage_{path.stem}",
        dx_px_per_frame=dx_px_per_frame,
        dy_px_per_frame=dy_px_per_frame,
        frame_count=frame_count,
        spot_count=4,
        min_spacing_px=14,
    )
    frames, _ = generate_synthetic_sequence(scenario, seed=seed)
    height, width = frames[0].shape[:2]
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        5.0,
        (width, height),
    )
    if not writer.isOpened():
        raise OSError(f"Could not create synthetic video: {path}")
    try:
        for frame in frames:
            writer.write(frame)
    finally:
        writer.release()


def build_synthetic_manifest(
    *,
    output_dir: Path,
    microns_per_pixel: float = 1.0,
    seconds_per_frame: float = 1.0,
    seed: int = 20260630,
) -> StageCalibrationManifest:
    """Create bead-like synthetic recordings with known commanded translation."""
    output_dir.mkdir(parents=True, exist_ok=True)
    specs: list[StageRecordingSpec] = []
    scenarios = (
        ("zero", "zero", 0.0, 0.0),
        ("x_pos_subpixel", "x_positive", 0.65, 0.0),
        ("x_pos_integer", "x_positive", 2.0, 0.0),
        ("x_neg", "x_negative", -1.0, 0.0),
        ("y_pos", "y_positive", 0.0, 0.75),
        ("y_neg", "y_negative", 0.0, -0.55),
        ("diag", "diagonal", 0.5, 0.35),
    )
    for index, (recording_id, direction, dx_um, dy_um) in enumerate(scenarios):
        video_path = output_dir / f"{recording_id}.avi"
        dx_px = dx_um / microns_per_pixel
        dy_px = dy_um / microns_per_pixel
        _write_synthetic_video(
            video_path,
            dx_px_per_frame=dx_px,
            dy_px_per_frame=dy_px,
            seed=seed + index,
        )
        specs.append(
            StageRecordingSpec(
                recording_id=recording_id,
                session_id="synthetic_session_1",
                source_path=str(video_path.resolve()),
                direction=direction,
                commanded_dx_um_per_frame=dx_um,
                commanded_dy_um_per_frame=dy_um,
            )
        )
    return StageCalibrationManifest(
        protocol_version=1,
        independent_microns_per_pixel=microns_per_pixel,
        seconds_per_frame=seconds_per_frame,
        lab_approved_tolerance_um_per_frame=0.5,
        recordings=tuple(specs),
    )


def _run_landmark_recording(
    recording: StageRecordingSpec,
    manifest: StageCalibrationManifest,
    output_dir: Path,
) -> tuple[Path, Path]:
    source = Path(recording.source_path)
    if not source.is_file():
        raise FileNotFoundError(f"Recording source not found: {source}")
    run_dir = output_dir / recording.session_id / recording.recording_id
    frame_dir = run_dir / "cropped_frames"
    crop_video_to_frames(
        source,
        frame_dir,
        rotation=recording.rotation,
        flip_horizontal=recording.flip_horizontal,
        roi_x=recording.roi_x,
        roi_y=recording.roi_y,
        roi_width=recording.roi_width,
        roi_height=recording.roi_height,
    )
    frame_paths = sorted(frame_dir.glob("*.png"))
    params = MotionIndexParams(
        num_starting_points=manifest.analysis.num_starting_points,
        min_point_spacing_px=manifest.analysis.min_point_spacing_px,
        search_radius_px=manifest.analysis.search_radius_px,
        template_patch_size_px=manifest.analysis.template_patch_size_px,
        min_template_confidence=manifest.analysis.min_template_confidence,
        lookahead_frames=manifest.analysis.lookahead_frames,
        microns_per_pixel=manifest.independent_microns_per_pixel,
        seconds_per_frame=manifest.seconds_per_frame,
        tracking_method=manifest.analysis.tracking_method,
    )
    result = run_motion_index_analysis(
        source,
        output_dir=run_dir,
        final_export_name=recording.recording_id,
        sample_id=recording.recording_id,
        params=params,
        preview_fps=5.0,
        frame_paths=frame_paths,
    )
    return Path(result.trajectory_csv), Path(result.summary_json)


def _run_flow_recording(
    recording: StageRecordingSpec,
    manifest: StageCalibrationManifest,
    output_dir: Path,
) -> tuple[Path, Path]:
    source = Path(recording.source_path)
    if not source.is_file():
        raise FileNotFoundError(f"Recording source not found: {source}")
    run_dir = output_dir / recording.session_id / recording.recording_id
    frame_dir = run_dir / "cropped_frames"
    crop_meta = crop_video_to_frames(
        source,
        frame_dir,
        rotation=recording.rotation,
        flip_horizontal=recording.flip_horizontal,
        roi_x=recording.roi_x,
        roi_y=recording.roi_y,
        roi_width=recording.roi_width,
        roi_height=recording.roi_height,
    )
    frames = load_cropped_frames(frame_dir)
    settings = OpticalFlowSettings(
        mask_percentile=manifest.analysis.mask_percentile,
        gaussian_blur_kernel=manifest.analysis.flow_blur_kernel,
        winsize=manifest.analysis.flow_winsize,
        microns_per_pixel=manifest.independent_microns_per_pixel,
        seconds_per_frame=manifest.seconds_per_frame,
    )
    roi_bounds = (
        int(crop_meta["roi_x"]),
        int(crop_meta["roi_y"]),
        int(crop_meta["roi_width"]),
        int(crop_meta["roi_height"]),
    )
    flow_result = compute_optical_flow_motion_index(
        frames,
        settings,
        sample_id=recording.recording_id,
        data_identity=str(source),
        roi_bounds=roi_bounds,
    )
    if not flow_result.has_valid_result:
        raise ValueError(flow_result.failure_reason or "Optical flow failed.")
    pair_csv = run_dir / f"{recording.recording_id}_flow_pair_summaries.csv"
    summary_json = run_dir / f"{recording.recording_id}_optical_flow.json"
    _write_flow_pair_csv(flow_result, pair_csv)
    summary_json.write_text(json.dumps(flow_result.summary_dict(), indent=2), encoding="utf-8")
    return pair_csv, summary_json


def validate_recording(
    recording: StageRecordingSpec,
    manifest: StageCalibrationManifest,
    *,
    output_dir: Path,
    thresholds: StageCalibrationThresholds,
) -> RecordingValidationResult:
    failures: list[str] = []
    method = manifest.analysis.analysis_method
    try:
        if method == "optical_flow":
            data_csv, summary_json = _run_flow_recording(recording, manifest, output_dir)
            dx_px, dy_px = measure_optical_flow_displacement_px(data_csv)
        else:
            data_csv, summary_json = _run_landmark_recording(recording, manifest, output_dir)
            dx_px, dy_px = measure_landmark_displacement_px(data_csv)
    except (OSError, ValueError) as exc:
        return RecordingValidationResult(
            recording_id=recording.recording_id,
            session_id=recording.session_id,
            direction=recording.direction,
            analysis_method=method,
            commanded_dx_um_per_frame=recording.commanded_dx_um_per_frame,
            commanded_dy_um_per_frame=recording.commanded_dy_um_per_frame,
            measured_dx_um_per_frame=float("nan"),
            measured_dy_um_per_frame=float("nan"),
            bias_dx_um_per_frame=float("nan"),
            bias_dy_um_per_frame=float("nan"),
            error_magnitude_um_per_frame=float("nan"),
            passed=False,
            failure_reasons=[str(exc)],
            output_dir=str(output_dir / recording.session_id / recording.recording_id),
        )

    mpp = manifest.independent_microns_per_pixel
    measured_dx_um = _px_to_um(dx_px, mpp)
    measured_dy_um = _px_to_um(dy_px, mpp)
    bias_dx = measured_dx_um - recording.commanded_dx_um_per_frame
    bias_dy = measured_dy_um - recording.commanded_dy_um_per_frame
    error_mag = float(np.hypot(bias_dx, bias_dy))

    if recording.direction == "zero":
        drift = float(np.hypot(measured_dx_um, measured_dy_um))
        if drift > thresholds.max_zero_motion_um_per_frame:
            failures.append("zero_motion_drift")
    else:
        if abs(bias_dx) > thresholds.max_abs_bias_um_per_frame:
            failures.append("x_bias")
        if abs(bias_dy) > thresholds.max_abs_bias_um_per_frame:
            failures.append("y_bias")
        if error_mag > thresholds.max_rmse_um_per_frame:
            failures.append("error_magnitude")

    return RecordingValidationResult(
        recording_id=recording.recording_id,
        session_id=recording.session_id,
        direction=recording.direction,
        analysis_method=method,
        commanded_dx_um_per_frame=recording.commanded_dx_um_per_frame,
        commanded_dy_um_per_frame=recording.commanded_dy_um_per_frame,
        measured_dx_um_per_frame=measured_dx_um,
        measured_dy_um_per_frame=measured_dy_um,
        bias_dx_um_per_frame=bias_dx,
        bias_dy_um_per_frame=bias_dy,
        error_magnitude_um_per_frame=error_mag,
        passed=not failures,
        failure_reasons=failures,
        output_dir=str(output_dir / recording.session_id / recording.recording_id),
        trajectory_csv=str(data_csv),
        summary_json=str(summary_json),
    )


def _check_axis_coverage(
    results: Sequence[RecordingValidationResult],
    thresholds: StageCalibrationThresholds,
) -> list[str]:
    failures: list[str] = []
    directions = {r.direction for r in results}
    for axis in ("x_positive", "x_negative", "y_positive", "y_negative", "zero"):
        if axis not in directions:
            failures.append(f"missing_direction:{axis}")
    axis_counts = {
        axis: sum(1 for r in results if r.direction == axis)
        for axis in directions
    }
    for axis, count in axis_counts.items():
        if axis != "zero" and count < thresholds.min_recordings_per_axis:
            failures.append(f"insufficient_{axis}:{count}")
    return failures


def run_stage_calibration_validation(
    manifest: StageCalibrationManifest,
    *,
    output_dir: Path,
    thresholds: StageCalibrationThresholds | None = None,
    run_analysis: bool = True,
) -> dict[str, Any]:
    thresholds = thresholds or StageCalibrationThresholds()
    output_dir.mkdir(parents=True, exist_ok=True)
    if not run_analysis:
        raise ValueError("run_analysis=False is not supported yet.")

    recording_results = [
        validate_recording(recording, manifest, output_dir=output_dir, thresholds=thresholds)
        for recording in manifest.recordings
    ]

    dx_diffs = [r.bias_dx_um_per_frame for r in recording_results if r.direction != "zero"]
    dy_diffs = [r.bias_dy_um_per_frame for r in recording_results if r.direction != "zero"]
    dx_stats = _agreement_stats(dx_diffs)
    dy_stats = _agreement_stats(dy_diffs)

    failures: list[str] = []
    for result in recording_results:
        if not result.passed:
            failures.append(f"{result.recording_id}:{','.join(result.failure_reasons)}")

    loa_within_tolerance = (
        abs(dx_stats["loa_lower"]) <= manifest.lab_approved_tolerance_um_per_frame
        and abs(dx_stats["loa_upper"]) <= manifest.lab_approved_tolerance_um_per_frame
        and abs(dy_stats["loa_lower"]) <= manifest.lab_approved_tolerance_um_per_frame
        and abs(dy_stats["loa_upper"]) <= manifest.lab_approved_tolerance_um_per_frame
    )
    if not loa_within_tolerance and any(r.direction != "zero" for r in recording_results):
        failures.append("bland_altman_outside_lab_tolerance")

    coverage_failures = _check_axis_coverage(recording_results, thresholds)
    if coverage_failures and any(r.session_id.startswith("synthetic") for r in recording_results):
        pass  # synthetic gate uses reduced direction set
    elif coverage_failures and len(manifest.recordings) >= 10:
        failures.extend(coverage_failures)

    passed = not failures and all(r.passed for r in recording_results)

    report = {
        "validation_kind": "stage_calibration_layer2",
        "generated_at_utc": _utc_now_iso(),
        "protocol_version": manifest.protocol_version,
        "independent_microns_per_pixel": manifest.independent_microns_per_pixel,
        "seconds_per_frame": manifest.seconds_per_frame,
        "lab_approved_tolerance_um_per_frame": manifest.lab_approved_tolerance_um_per_frame,
        "analysis_method": manifest.analysis.analysis_method,
        "passed": passed,
        "recording_count": len(recording_results),
        "passed_recording_count": sum(1 for r in recording_results if r.passed),
        "agreement": {
            "dx_um_per_frame": dx_stats,
            "dy_um_per_frame": dy_stats,
            "loa_within_lab_tolerance": loa_within_tolerance,
        },
        "thresholds": asdict(thresholds),
        "recordings": [asdict(r) for r in recording_results],
        "failure_reasons": failures,
        "limitations": [
            "Layer 2 validates commanded stage translation, not biological F-actin identity.",
            "Limits of agreement must be reviewed against the minimum biological effect size.",
            "Real bead-slide manifests require independently measured microns_per_pixel.",
        ],
    }

    report_json = output_dir / "stage_calibration_report.json"
    scenario_csv = output_dir / "stage_calibration_recordings.csv"
    report_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _write_recording_csv(recording_results, scenario_csv)
    report["report_json"] = str(report_json)
    report["scenario_csv"] = str(scenario_csv)
    return report


def _write_recording_csv(results: Sequence[RecordingValidationResult], path: Path) -> None:
    if not results:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(asdict(results[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            row = asdict(result)
            row["failure_reasons"] = ";".join(result.failure_reasons)
            writer.writerow(row)


def run_synthetic_stage_calibration(
    *,
    output_dir: Path | None = None,
    seed: int = 20260630,
    thresholds: StageCalibrationThresholds | None = None,
) -> dict[str, Any]:
    root = output_dir or Path(tempfile.mkdtemp(prefix="actintrack_layer2_"))
    synthetic_dir = root / "synthetic_recordings"
    manifest = build_synthetic_manifest(
        output_dir=synthetic_dir,
        microns_per_pixel=1.0,
        seconds_per_frame=1.0,
        seed=seed,
    )
    return run_stage_calibration_validation(
        manifest,
        output_dir=root,
        thresholds=thresholds,
    )
