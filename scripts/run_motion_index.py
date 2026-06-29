#!/usr/bin/env python3
"""Run F-actin motion-index analysis on one processed ROI video or image sequence."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from actintrack_app.motion_index import (
    MotionIndexParams,
    TRACKING_METHOD_BRIGHTEST_LOCAL,
    TRACKING_METHOD_TEMPLATE,
    run_motion_index_test,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run template-matching motion-index analysis on one processed cropped "
            "ROI video or image-sequence directory."
        )
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Path to processed ROI .mp4/.avi, TIFF stack, or image-sequence folder",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: parent folder of the source video)",
    )
    parser.add_argument(
        "--export-name",
        type=str,
        default=None,
        help="Final export name stem for output files (default: source file stem)",
    )
    parser.add_argument("--num-points", type=int, default=10)
    parser.add_argument("--min-spacing", type=int, default=20)
    parser.add_argument("--search-radius", type=int, default=8)
    parser.add_argument("--patch-size", type=int, default=11)
    parser.add_argument("--min-confidence", type=float, default=0.55)
    parser.add_argument("--lookahead-frames", type=int, default=0)
    parser.add_argument("--microns-per-pixel", type=float, default=0.265)
    parser.add_argument("--seconds-per-frame", type=float, default=30.0)
    parser.add_argument(
        "--tracking-method",
        choices=[TRACKING_METHOD_BRIGHTEST_LOCAL, TRACKING_METHOD_TEMPLATE],
        default=TRACKING_METHOD_BRIGHTEST_LOCAL,
        help="Local matching method used to follow each starting point.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    params = MotionIndexParams(
        num_starting_points=args.num_points,
        min_point_spacing_px=args.min_spacing,
        search_radius_px=args.search_radius,
        template_patch_size_px=args.patch_size,
        min_template_confidence=args.min_confidence,
        lookahead_frames=args.lookahead_frames,
        microns_per_pixel=args.microns_per_pixel,
        seconds_per_frame=args.seconds_per_frame,
        tracking_method=args.tracking_method,
    )
    source = args.source.resolve()
    out_dir = args.output_dir or (source.parent if source.is_file() else source)
    export_name = args.export_name or (source.stem if source.is_file() else source.name)
    run_motion_index_test(
        source,
        output_dir=out_dir,
        final_export_name=export_name,
        params=params,
    )


if __name__ == "__main__":
    main()
