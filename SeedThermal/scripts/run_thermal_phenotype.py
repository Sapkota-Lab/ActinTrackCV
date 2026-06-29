#!/usr/bin/env python3
"""Batch-process radiometric FLIR Ignite JPGs into thermal time-series CSV and previews."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seedthermal.phenotype import (  # noqa: E402
    load_roi_config,
    parse_roi_spec,
    run_thermal_batch,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Process a folder of radiometric FLIR JPGs (Ignite downloads) into "
            "per-ROI temperature CSV rows and clean preview images."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Folder containing radiometric JPG files",
    )
    parser.add_argument(
        "--plate-id",
        type=str,
        default="thermal_plate",
        help="Plate or experiment identifier for output folder naming",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "processed" / "runs",
        help="Root directory for run outputs (default: SeedThermal/processed/runs)",
    )
    parser.add_argument(
        "--roi-config",
        type=Path,
        help="JSON file with 'rois' and optional 'reference_roi'",
    )
    parser.add_argument(
        "--roi",
        action="append",
        default=[],
        metavar="SPEC",
        help="ROI as id:x,y,w,h on the thermal array (repeatable). Default: full frame.",
    )
    parser.add_argument(
        "--reference-roi",
        type=str,
        help="Paper/background reference ROI as x,y,w,h for relative_mean_c",
    )
    parser.add_argument(
        "--no-previews",
        action="store_true",
        help="Skip writing optical and false-color preview images",
    )
    args = parser.parse_args()

    rois = None
    reference_roi = None
    if args.roi_config:
        rois, reference_roi = load_roi_config(args.roi_config)
    if args.roi:
        rois = [parse_roi_spec(spec) for spec in args.roi]
    if args.reference_roi:
        reference_roi = parse_roi_spec(f"reference:{args.reference_roi}")

    try:
        result = run_thermal_batch(
            args.input,
            args.output_root,
            args.plate_id,
            rois=rois,
            reference_roi=reference_roi,
            save_previews=not args.no_previews,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    summary = {
        "ok": result.captures_failed == 0,
        "plate_id": result.plate_id,
        "run_dir": str(result.run_dir),
        "captures_processed": result.captures_processed,
        "captures_failed": result.captures_failed,
        "rows_written": len(result.rows),
        "timeseries_csv": str(result.run_dir / "plate_temperature_timeseries.csv"),
        "errors": result.errors,
    }
    print(json.dumps(summary, indent=2))
    return 0 if result.captures_failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
