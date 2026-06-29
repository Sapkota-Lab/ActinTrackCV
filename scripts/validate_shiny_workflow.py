#!/usr/bin/env python3
"""End-to-end output validation for the Shiny + Python analysis workflow."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from actintrack_app.optical_flow_validation import run_optical_flow_validation  # noqa: E402
from actintrack_app.tracker_validation import (  # noqa: E402
    SyntheticScenario,
    generate_synthetic_sequence,
)
from scripts.shiny_bridge import (  # noqa: E402
    ANALYSIS_LANDMARK_TRACKING,
    ANALYSIS_OPTICAL_FLOW,
    run_optical_flow,
    run_tracking,
)


@dataclass
class Finding:
    severity: str  # pass | warn | fail | info
    category: str
    message: str


@dataclass
class ValidationReport:
    findings: list[Finding] = field(default_factory=list)

    def add(self, severity: str, category: str, message: str) -> None:
        self.findings.append(Finding(severity, category, message))

    @property
    def passed(self) -> bool:
        return not any(f.severity == "fail" for f in self.findings)

    def summary(self) -> dict[str, Any]:
        counts = {key: 0 for key in ("pass", "warn", "fail", "info")}
        for item in self.findings:
            counts[item.severity] = counts.get(item.severity, 0) + 1
        return {
            "passed": self.passed,
            "counts": counts,
            "findings": [item.__dict__ for item in self.findings],
        }


def _write_synthetic_video(path: Path, frame_count: int = 12) -> None:
    scenario = SyntheticScenario(
        "workflow_gate",
        dx_px_per_frame=2.0,
        dy_px_per_frame=1.0,
        spot_count=4,
        frame_count=frame_count,
        min_spacing_px=14,
    )
    frames, _ = generate_synthetic_sequence(scenario, seed=20260629)
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


def _namespace(**kwargs: Any) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _required_keys(payload: dict[str, Any], keys: list[str]) -> list[str]:
    return [key for key in keys if key not in payload]


def _validate_landmark_outputs(report: ValidationReport, output_dir: Path, payload: dict[str, Any]) -> None:
    outputs = payload.get("outputs") or {}
    required_files = {
        "trajectory_csv": outputs.get("trajectory_csv"),
        "summary_json": outputs.get("summary_json") or payload.get("summary_json"),
        "starting_points_png": outputs.get("starting_points_png"),
        "track_overlay_png": outputs.get("track_overlay_png"),
    }
    for label, path_value in required_files.items():
        path = Path(path_value) if path_value else None
        if path is None or not path.is_file():
            report.add("fail", "landmark_artifacts", f"Missing {label}: {path_value}")
        else:
            report.add("pass", "landmark_artifacts", f"Present {label}")

    mp4_path = Path(outputs.get("track_preview_mp4") or "") if outputs.get("track_preview_mp4") else None
    webm_path = Path(outputs.get("track_preview_webm") or "") if outputs.get("track_preview_webm") else None
    if mp4_path and mp4_path.is_file():
        report.add("pass", "landmark_artifacts", "Present track_preview_mp4")
    elif webm_path and webm_path.is_file():
        report.add(
            "warn",
            "landmark_artifacts",
            "MP4 preview unavailable; WebM preview present (acceptable on headless CI)",
        )
    else:
        preview_error = payload.get("track_preview_error") or ""
        report.add(
            "fail",
            "landmark_artifacts",
            f"Missing track preview video (mp4/webm). {preview_error}".strip(),
        )

    summary_path = Path(required_files["summary_json"]) if required_files["summary_json"] else None
    if summary_path and summary_path.is_file():
        missing = _required_keys(
            _load_json(summary_path),
            [
                "absolute_velocity_index_um_per_s",
                "downward_velocity_index_um_per_s",
                "time_weighted_mean_speed_um_per_s",
                "num_tracks_started",
                "num_tracks_with_valid_steps",
                "total_valid_steps",
                "parameters",
            ],
        )
        if missing:
            report.add("fail", "landmark_json", f"Summary JSON missing keys: {missing}")
        else:
            report.add("pass", "landmark_json", "Summary JSON contains required scalar fields")

    traj_path = Path(required_files["trajectory_csv"]) if required_files["trajectory_csv"] else None
    if traj_path and traj_path.is_file():
        with traj_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        required_cols = {
            "track_id",
            "frame_index",
            "x_px",
            "y_px",
            "absolute_velocity_um_per_s",
            "downward_velocity_um_per_s",
            "motion_angle_deg",
            "turning_angle_deg",
        }
        if not rows:
            report.add("fail", "landmark_csv", "Trajectory CSV is empty")
        elif not required_cols.issubset(rows[0].keys()):
            report.add(
                "fail",
                "landmark_csv",
                f"Trajectory CSV missing columns: {sorted(required_cols - set(rows[0]))}",
            )
        else:
            report.add("pass", "landmark_csv", f"Trajectory CSV has {len(rows)} rows and required columns")

    active_flags = [item.get("active_to_end") for item in payload.get("track_summaries") or []]
    if active_flags and not any(active_flags):
        report.add(
            "warn",
            "landmark_metadata",
            "track_summaries.active_to_end is always false — survival metadata is not trustworthy",
        )

    abs_idx = payload.get("absolute_velocity_index_um_per_s")
    gen_idx = payload.get("general_movement_index_um_per_s")
    tw = payload.get("time_weighted_mean_speed_um_per_s")
    if abs_idx is not None and gen_idx is not None and abs_idx != gen_idx:
        report.add("warn", "landmark_metrics", "absolute and general movement indices differ unexpectedly")
    if tw is not None and abs_idx is not None and tw != abs_idx:
        report.add(
            "info",
            "landmark_metrics",
            "time_weighted_mean_speed differs from absolute_velocity_index (expected when frame gaps exist)",
        )


def _validate_flow_outputs(report: ValidationReport, payload: dict[str, Any]) -> None:
    outputs = payload.get("outputs") or {}
    required_files = {
        "summary_json": outputs.get("summary_json"),
        "flow_overlay_png": outputs.get("flow_overlay_png"),
        "flow_pair_csv": outputs.get("flow_pair_csv"),
    }
    for label, path_value in required_files.items():
        path = Path(path_value) if path_value else None
        if path is None or not path.is_file():
            report.add("fail", "flow_artifacts", f"Missing {label}: {path_value}")
        else:
            report.add("pass", "flow_artifacts", f"Present {label}")

    summary_path = Path(required_files["summary_json"]) if required_files["summary_json"] else None
    if summary_path and summary_path.is_file():
        summary = _load_json(summary_path)
        missing = _required_keys(
            summary,
            [
                "optical_flow_general_movement_um_s",
                "optical_flow_downward_motion_um_s",
                "optical_flow_net_y_velocity_um_s",
                "optical_flow_valid_pixel_fraction",
                "frame_pair_count",
                "settings",
            ],
        )
        if missing:
            report.add("fail", "flow_json", f"Flow summary JSON missing keys: {missing}")
        else:
            report.add("pass", "flow_json", "Flow summary JSON contains required scalar fields")

        if "optical_flow_net_y_velocity_um_per_s" in summary:
            report.add(
                "warn",
                "flow_json",
                "Python summary uses optical_flow_net_y_velocity_um_s (R helper expects _um_per_s suffix)",
            )

    pair_path = Path(required_files["flow_pair_csv"]) if required_files["flow_pair_csv"] else None
    if pair_path and pair_path.is_file():
        with pair_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        required_cols = {
            "frame_a",
            "frame_b",
            "mean_magnitude_px_frame",
            "mean_downward_px_frame",
            "valid_pixel_fraction",
        }
        if not rows:
            report.add("fail", "flow_csv", "Flow pair CSV is empty")
        elif not required_cols.issubset(rows[0].keys()):
            report.add(
                "fail",
                "flow_csv",
                f"Flow pair CSV missing columns: {sorted(required_cols - set(rows[0]))}",
            )
        else:
            report.add("pass", "flow_csv", f"Flow pair CSV has {len(rows)} pairs")


def _validate_r_json_reader(report: ValidationReport, summary_path: Path, project_dir: Path) -> None:
    r_script = ROOT / "shiny_app" / "R" / "helpers.R"
    code = f"""
source("{r_script.as_posix()}")
row <- read_analysis_json("{summary_path.as_posix()}", "{project_dir.as_posix()}")
if (is.null(row)) stop("read_analysis_json returned NULL")
cat(jsonlite::toJSON(as.list(row), auto_unbox=TRUE, dataframe="rows"))
"""
    try:
        proc = subprocess.run(
            ["Rscript", "-e", code],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        report.add("fail", "r_bridge", f"R read_analysis_json failed: {exc.stderr.strip()}")
        return

    row = json.loads(proc.stdout.strip())
    if row.get("analysis_method") == "optical_flow":
        if row.get("absolute_velocity") in (None, "", "NA"):
            report.add("fail", "r_bridge", "R failed to parse optical flow absolute velocity")
        else:
            report.add("pass", "r_bridge", "R parsed optical flow absolute velocity")
        if row.get("net_y_velocity") in (None, "", "NA") or (
            isinstance(row.get("net_y_velocity"), float) and np.isnan(row["net_y_velocity"])
        ):
            report.add(
                "warn",
                "r_bridge",
                "R net_y_velocity is NA for optical flow (field-name mismatch with Python)",
            )
    else:
        if row.get("absolute_velocity") in (None, "", "NA"):
            report.add("fail", "r_bridge", "R failed to parse landmark absolute velocity")
        else:
            report.add("pass", "r_bridge", "R parsed landmark absolute velocity")
        if not row.get("trajectory_csv"):
            report.add("warn", "r_bridge", "R did not resolve trajectory_csv path")


def run_validation(output_root: Path | None = None) -> ValidationReport:
    report = ValidationReport()
    tmp = tempfile.TemporaryDirectory()
    root = output_root or Path(tmp.name)
    root.mkdir(parents=True, exist_ok=True)
    video = root / "synthetic_source.avi"
    _write_synthetic_video(video)

    mpp = 0.265
    spf = 30.0

    landmark_dir = root / "landmark_run"
    landmark_dir.mkdir(parents=True, exist_ok=True)
    landmark_args = _namespace(
        source=video,
        output_dir=landmark_dir,
        export_name="validation_landmark",
        rotation=0,
        flip_horizontal=False,
        roi_x=0,
        roi_y=0,
        roi_width=0,
        roi_height=0,
        num_points=4,
        min_spacing=10,
        search_radius=12,
        patch_size=11,
        min_confidence=0.2,
        lookahead_frames=0,
        microns_per_pixel=mpp,
        seconds_per_frame=spf,
        preview_fps=5.0,
        tracking_method="brightest_local",
    )
    landmark_payload = run_tracking(landmark_args)
    if landmark_payload.get("analysis_method") != ANALYSIS_LANDMARK_TRACKING:
        report.add("fail", "landmark_run", "Bridge did not tag landmark analysis_method")
    else:
        report.add("pass", "landmark_run", "Landmark bridge run completed")
    _validate_landmark_outputs(report, landmark_dir, landmark_payload)

    flow_dir = root / "flow_run"
    flow_dir.mkdir(parents=True, exist_ok=True)
    flow_args = _namespace(
        source=video,
        output_dir=flow_dir,
        export_name="validation_flow",
        rotation=0,
        flip_horizontal=False,
        roi_x=0,
        roi_y=0,
        roi_width=0,
        roi_height=0,
        mask_percentile=85.0,
        flow_blur_kernel=3,
        flow_winsize=15,
        flow_arrow_spacing=8,
        flow_arrow_scale=0.8,
        microns_per_pixel=mpp,
        seconds_per_frame=spf,
    )
    flow_payload = run_optical_flow(flow_args)
    if flow_payload.get("analysis_method") != ANALYSIS_OPTICAL_FLOW:
        report.add("fail", "flow_run", "Bridge did not tag optical flow analysis_method")
    else:
        report.add("pass", "flow_run", "Optical flow bridge run completed")
    _validate_flow_outputs(report, flow_payload)

    landmark_summary = landmark_payload.get("outputs", {}).get("summary_json") or landmark_payload.get("summary_json")
    flow_summary = flow_payload.get("outputs", {}).get("summary_json")
    if landmark_summary:
        _validate_r_json_reader(report, Path(landmark_summary), root)
    if flow_summary:
        _validate_r_json_reader(report, Path(flow_summary), root)

    # Cross-method sanity on the same synthetic clip.
    landmark_speed = float(landmark_payload.get("absolute_velocity_index_um_per_s") or 0.0)
    flow_speed = float(flow_payload.get("optical_flow_general_movement_um_s") or 0.0)
    if landmark_speed > 0 and flow_speed > 0:
        ratio = max(landmark_speed, flow_speed) / max(min(landmark_speed, flow_speed), 1e-9)
        report.add(
            "info",
            "cross_method",
            f"Landmark absolute index {landmark_speed:.6f} µm/s vs flow general movement {flow_speed:.6f} µm/s (ratio {ratio:.2f}x) — methods are not expected to match",
        )

    if not (landmark_dir / "cropped_frames").is_dir():
        report.add("fail", "cropped_frames", "Landmark run did not persist cropped_frames")
    if not (flow_dir / "cropped_frames").is_dir():
        report.add("fail", "cropped_frames", "Flow run did not persist cropped_frames")

    of_val = run_optical_flow_validation(output_dir=None, seed=20260629)
    if of_val.get("passed"):
        report.add(
            "pass",
            "optical_flow_validation",
            f"Synthetic optical-flow ground truth passed ({of_val.get('passed_scenario_count')}/{of_val.get('scenario_count')} scenarios)",
        )
    else:
        report.add(
            "fail",
            "optical_flow_validation",
            f"Synthetic optical-flow ground truth failed ({of_val.get('passed_scenario_count')}/{of_val.get('scenario_count')} scenarios)",
        )

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "outputs" / "shiny_workflow_validation.json",
    )
    args = parser.parse_args()
    report = run_validation()
    payload = report.summary()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
