"""Reproducible synthetic ground-truth validation for the 2D motion tracker."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np

from actintrack_app.motion_index import (
    TRACKING_METHOD_BRIGHTEST_LOCAL,
    MotionIndexParams,
    compute_velocity_summary,
    select_starting_points,
    track_points,
)


@dataclass(frozen=True)
class SyntheticScenario:
    name: str
    dx_px_per_frame: float
    dy_px_per_frame: float
    spot_count: int = 4
    frame_count: int = 12
    spot_sigma_px: float = 1.25
    peak_intensity: float = 210.0
    background: float = 12.0
    read_noise_sd: float = 0.0
    poisson_noise: bool = False
    bleaching_per_frame: float = 0.0
    min_spacing_px: int = 14


@dataclass(frozen=True)
class ValidationThresholds:
    max_position_rmse_px: float = 0.75
    max_speed_relative_error: float = 0.10
    max_vertical_absolute_error_px_per_frame: float = 0.15
    min_point_recall: float = 0.95


@dataclass(frozen=True)
class ScenarioValidationResult:
    scenario: str
    passed: bool
    expected_speed_px_per_frame: float
    measured_speed_px_per_frame: float
    speed_bias_px_per_frame: float
    speed_relative_error: float
    expected_signed_vertical_px_per_frame: float
    measured_signed_vertical_px_per_frame: float
    signed_vertical_bias_px_per_frame: float
    expected_downward_contribution_px_per_frame: float
    measured_downward_contribution_px_per_frame: float
    downward_contribution_bias_px_per_frame: float
    position_bias_x_px: float
    position_bias_y_px: float
    position_rmse_px: float
    point_recall: float
    expected_point_count: int
    measured_point_count: int
    started_track_count: int
    failure_reasons: tuple[str, ...]


DEFAULT_SCENARIOS = (
    SyntheticScenario("clean_integer_down", 2.0, 1.0),
    SyntheticScenario(
        "subpixel_down",
        0.65,
        0.35,
        read_noise_sd=1.0,
        poisson_noise=True,
    ),
    SyntheticScenario(
        "noisy_upward_bleaching",
        -0.40,
        -0.55,
        read_noise_sd=3.0,
        poisson_noise=True,
        bleaching_per_frame=0.035,
    ),
    SyntheticScenario(
        "dense_noisy_down",
        -0.50,
        0.60,
        spot_count=6,
        read_noise_sd=2.5,
        poisson_noise=True,
        bleaching_per_frame=0.02,
        min_spacing_px=10,
    ),
)


def _initial_positions(spot_count: int, min_spacing_px: int) -> np.ndarray:
    positions: list[tuple[float, float]] = []
    spacing = max(12, min_spacing_px + 3)
    for row in range(2):
        for col in range(3):
            positions.append((24.0 + (col * spacing), 27.0 + (row * spacing)))
            if len(positions) == spot_count:
                return np.asarray(positions, dtype=np.float64)
    raise ValueError("Synthetic validation supports at most six spots.")


def generate_synthetic_sequence(
    scenario: SyntheticScenario,
    *,
    seed: int = 20260622,
    shape: tuple[int, int] = (96, 112),
) -> tuple[list[np.ndarray], np.ndarray]:
    """Return uint8 microscopy-like frames and exact positions [frame, spot, xy]."""
    rng = np.random.default_rng(seed)
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    initial = _initial_positions(scenario.spot_count, scenario.min_spacing_px)
    positions = np.empty((scenario.frame_count, scenario.spot_count, 2), dtype=float)
    frames: list[np.ndarray] = []

    for frame_index in range(scenario.frame_count):
        shift = np.asarray(
            [scenario.dx_px_per_frame, scenario.dy_px_per_frame], dtype=float
        ) * frame_index
        positions[frame_index] = initial + shift
        image = np.full((h, w), scenario.background, dtype=np.float64)
        image += np.linspace(0.0, 3.0, w, dtype=np.float64)[None, :]
        bleach = max(0.15, 1.0 - (scenario.bleaching_per_frame * frame_index))

        for spot_index, (x, y) in enumerate(positions[frame_index]):
            amplitude = (scenario.peak_intensity - (spot_index * 7.0)) * bleach
            radius_sq = ((xx - x) ** 2) + ((yy - y) ** 2)
            image += amplitude * np.exp(
                -radius_sq / (2.0 * scenario.spot_sigma_px**2)
            )

        if scenario.poisson_noise:
            image = rng.poisson(np.clip(image, 0.0, 255.0)).astype(np.float64)
        if scenario.read_noise_sd > 0:
            image += rng.normal(0.0, scenario.read_noise_sd, image.shape)
        frame = np.clip(np.rint(image), 0, 255).astype(np.uint8)
        frames.append(cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR))

    return frames, positions


def _match_starts_to_truth(starts: Sequence[tuple[float, float]], truth: np.ndarray) -> dict[int, int]:
    available = set(range(len(truth)))
    mapping: dict[int, int] = {}
    for track_index, start in enumerate(starts):
        if not available:
            break
        truth_index = min(
            available,
            key=lambda i: float(np.hypot(start[0] - truth[i, 0], start[1] - truth[i, 1])),
        )
        if float(np.hypot(start[0] - truth[truth_index, 0], start[1] - truth[truth_index, 1])) <= 3.0:
            mapping[track_index] = truth_index
            available.remove(truth_index)
    return mapping


def validate_scenario(
    scenario: SyntheticScenario,
    *,
    thresholds: ValidationThresholds = ValidationThresholds(),
    tracking_method: str = TRACKING_METHOD_BRIGHTEST_LOCAL,
    seed: int = 20260622,
) -> ScenarioValidationResult:
    frames, truth = generate_synthetic_sequence(scenario, seed=seed)
    params = MotionIndexParams(
        num_starting_points=scenario.spot_count,
        min_point_spacing_px=scenario.min_spacing_px,
        search_radius_px=5,
        template_patch_size_px=9,
        min_template_confidence=0.20,
        microns_per_pixel=1.0,
        seconds_per_frame=1.0,
        tracking_method=tracking_method,
    )
    starts = select_starting_points(frames[0], params)
    tracks = track_points(frames, starts, params)
    start_mapping = _match_starts_to_truth(starts, truth[0])

    x_errors: list[float] = []
    y_errors: list[float] = []
    for track in tracks:
        truth_index = start_mapping.get(track.track_id)
        if truth_index is None:
            continue
        for point in track.points:
            expected = truth[point.frame_index, truth_index]
            x_errors.append(point.x - float(expected[0]))
            y_errors.append(point.y - float(expected[1]))

    measured = compute_velocity_summary(tracks, params)
    expected_speed = float(
        np.hypot(scenario.dx_px_per_frame, scenario.dy_px_per_frame)
    )
    expected_vertical = scenario.dy_px_per_frame
    expected_downward = max(scenario.dy_px_per_frame, 0.0)
    speed_bias = measured.time_weighted_mean_speed_um_per_s - expected_speed
    speed_relative_error = abs(speed_bias) / max(expected_speed, 1e-12)
    vertical_bias = measured.signed_vertical_velocity_um_per_s - expected_vertical
    downward_bias = (
        measured.downward_velocity_contribution_um_per_s - expected_downward
    )
    squared_errors = [
        (dx * dx) + (dy * dy) for dx, dy in zip(x_errors, y_errors, strict=True)
    ]
    position_rmse = float(np.sqrt(np.mean(squared_errors))) if squared_errors else float("inf")
    expected_points = scenario.spot_count * scenario.frame_count
    measured_points = len(x_errors)
    point_recall = measured_points / expected_points

    failures: list[str] = []
    if position_rmse > thresholds.max_position_rmse_px:
        failures.append("position_rmse")
    if speed_relative_error > thresholds.max_speed_relative_error:
        failures.append("speed_relative_error")
    if abs(vertical_bias) > thresholds.max_vertical_absolute_error_px_per_frame:
        failures.append("signed_vertical_error")
    if abs(downward_bias) > thresholds.max_vertical_absolute_error_px_per_frame:
        failures.append("downward_contribution_error")
    if point_recall < thresholds.min_point_recall:
        failures.append("point_recall")

    return ScenarioValidationResult(
        scenario=scenario.name,
        passed=not failures,
        expected_speed_px_per_frame=expected_speed,
        measured_speed_px_per_frame=measured.time_weighted_mean_speed_um_per_s,
        speed_bias_px_per_frame=speed_bias,
        speed_relative_error=speed_relative_error,
        expected_signed_vertical_px_per_frame=expected_vertical,
        measured_signed_vertical_px_per_frame=measured.signed_vertical_velocity_um_per_s,
        signed_vertical_bias_px_per_frame=vertical_bias,
        expected_downward_contribution_px_per_frame=expected_downward,
        measured_downward_contribution_px_per_frame=(
            measured.downward_velocity_contribution_um_per_s
        ),
        downward_contribution_bias_px_per_frame=downward_bias,
        position_bias_x_px=float(np.mean(x_errors)) if x_errors else float("nan"),
        position_bias_y_px=float(np.mean(y_errors)) if y_errors else float("nan"),
        position_rmse_px=position_rmse,
        point_recall=point_recall,
        expected_point_count=expected_points,
        measured_point_count=measured_points,
        started_track_count=len(tracks),
        failure_reasons=tuple(failures),
    )


def run_synthetic_validation(
    *,
    output_dir: str | Path | None = None,
    scenarios: Sequence[SyntheticScenario] = DEFAULT_SCENARIOS,
    thresholds: ValidationThresholds = ValidationThresholds(),
    tracking_method: str = TRACKING_METHOD_BRIGHTEST_LOCAL,
    seed: int = 20260622,
) -> dict[str, object]:
    results = [
        validate_scenario(
            scenario,
            thresholds=thresholds,
            tracking_method=tracking_method,
            seed=seed + index,
        )
        for index, scenario in enumerate(scenarios)
    ]
    payload: dict[str, object] = {
        "validation_kind": "synthetic_ground_truth",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "tracking_method": tracking_method,
        "random_seed": seed,
        "thresholds": asdict(thresholds),
        "passed": all(result.passed for result in results),
        "scenario_count": len(results),
        "passed_scenario_count": sum(result.passed for result in results),
        "results": [asdict(result) for result in results],
        "limitations": [
            "Synthetic validation does not verify microscope pixel calibration or acquisition timing.",
            "Engineering thresholds must be approved against the biological effect size of interest.",
        ],
    }

    if output_dir is not None:
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        safe_method = tracking_method.replace("/", "_").replace(" ", "_")
        json_path = directory / f"tracker_validation_{safe_method}_report.json"
        csv_path = directory / f"tracker_validation_{safe_method}_scenarios.csv"
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            rows = [asdict(result) for result in results]
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        payload["report_json"] = str(json_path.resolve())
        payload["scenario_csv"] = str(csv_path.resolve())

    return payload
