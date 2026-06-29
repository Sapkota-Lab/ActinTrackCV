"""Output path helpers for SeedThermal analysis runs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def thermal_run_dir(
    output_root: Path,
    plate_id: str,
    run_timestamp: datetime | None = None,
) -> Path:
    """Return ``processed/runs/<plate_id>/<timestamp>/``."""
    stamp = run_timestamp or datetime.now(timezone.utc)
    folder = stamp.strftime("%Y%m%dT%H%M%SZ")
    safe_plate = plate_id.strip().replace("/", "_") or "plate"
    return Path(output_root) / safe_plate / folder


def thermal_manifest_path(run_dir: Path) -> Path:
    return run_dir / "thermal_run_manifest.json"


def thermal_timeseries_csv_path(run_dir: Path) -> Path:
    return run_dir / "plate_temperature_timeseries.csv"


def thermal_preview_dir(run_dir: Path) -> Path:
    return run_dir / "previews"
