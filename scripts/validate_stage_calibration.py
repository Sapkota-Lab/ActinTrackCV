#!/usr/bin/env python3
"""Run Layer 2 stage-calibration validation against commanded translations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from actintrack_app.stage_calibration_validation import (
    StageCalibrationThresholds,
    load_stage_calibration_manifest,
    run_stage_calibration_validation,
    run_synthetic_stage_calibration,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        help="JSON manifest describing bead-slide recordings and commanded motion.",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Run the built-in synthetic bead-slide gate (for CI and smoke tests).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "outputs" / "stage_calibration_validation",
    )
    parser.add_argument("--seed", type=int, default=20260630)
    args = parser.parse_args()

    if args.synthetic:
        report = run_synthetic_stage_calibration(output_dir=args.output_dir, seed=args.seed)
    elif args.manifest is not None:
        manifest = load_stage_calibration_manifest(args.manifest)
        report = run_stage_calibration_validation(manifest, output_dir=args.output_dir)
    else:
        parser.error("Provide --manifest <path> or --synthetic.")

    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
