#!/usr/bin/env python3
"""Run the reproducible synthetic ground-truth tracker benchmark."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from actintrack_app.motion_index import TRACKING_METHODS
from actintrack_app.tracker_validation import run_synthetic_validation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "outputs" / "tracker_validation",
    )
    parser.add_argument("--tracking-method", choices=sorted(TRACKING_METHODS), default="brightest_local")
    parser.add_argument("--seed", type=int, default=20260622)
    args = parser.parse_args()

    report = run_synthetic_validation(
        output_dir=args.output_dir,
        tracking_method=args.tracking_method,
        seed=args.seed,
    )
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
