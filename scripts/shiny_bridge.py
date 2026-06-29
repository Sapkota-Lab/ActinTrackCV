#!/usr/bin/env python3
"""CLI bridge used by the R Shiny app for media preview and tracking runs."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from actintrack_app.motion_index import (  # noqa: E402
    MotionIndexParams,
    TRACKING_METHOD_BRIGHTEST_LOCAL,
    TRACKING_METHOD_TEMPLATE,
    run_motion_index_analysis,
    transcode_preview_to_webm,
)
from actintrack_app.optical_flow_motion_index import (  # noqa: E402
    OpticalFlowSettings,
    build_optical_flow_fingerprint,
    compute_optical_flow_motion_index,
)
from actintrack_app.optical_flow_overlay import (  # noqa: E402
    OpticalFlowVisualizationSettings,
    build_flow_cache,
    get_flow_arrows_for_frame,
    render_optical_flow_overlay,
)

ANALYSIS_LANDMARK_TRACKING = "landmark_tracking"
ANALYSIS_OPTICAL_FLOW = "optical_flow"
ANALYSIS_METHODS = {ANALYSIS_LANDMARK_TRACKING, ANALYSIS_OPTICAL_FLOW}


def _json_print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":")))


def _open_video(source: Path) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        cap.release()
        raise ValueError(f"Cannot open video: {source}")
    return cap


def probe_media(source: Path) -> dict[str, Any]:
    source = Path(source).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Source does not exist: {source}")
    cap = _open_video(source)
    try:
        frame_count = max(0, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
        width = max(0, int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)))
        height = max(0, int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        playback_fps = float(cap.get(cv2.CAP_PROP_FPS))
        if playback_fps <= 0:
            playback_fps = 0.0
    finally:
        cap.release()
    return {
        "source_path": str(source),
        "file_name": source.name,
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "playback_fps": round(playback_fps, 6),
        "size_bytes": source.stat().st_size,
    }


def orient_frame(frame: Any, rotation: int, flip_horizontal: bool) -> Any:
    rotation = int(rotation) % 360
    if rotation == 90:
        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    elif rotation == 180:
        frame = cv2.rotate(frame, cv2.ROTATE_180)
    elif rotation == 270:
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    elif rotation != 0:
        raise ValueError("rotation must be one of 0, 90, 180, or 270")
    if flip_horizontal:
        frame = cv2.flip(frame, 1)
    return frame


def read_oriented_frame(
    source: Path,
    frame_index: int,
    *,
    rotation: int = 0,
    flip_horizontal: bool = False,
) -> tuple[Any, dict[str, Any]]:
    source = Path(source).resolve()
    cap = _open_video(source)
    try:
        frame_count = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
        frame_index = max(0, min(int(frame_index), frame_count - 1))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok or frame is None:
            raise ValueError(f"Could not read frame {frame_index} from {source.name}")
    finally:
        cap.release()
    frame = orient_frame(frame, rotation, flip_horizontal)
    height, width = frame.shape[:2]
    return frame, {
        "source_path": str(source),
        "frame_index": frame_index,
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "rotation": int(rotation),
        "flip_horizontal": bool(flip_horizontal),
    }


def extract_preview_frame(
    source: Path,
    output_path: Path,
    frame_index: int,
    *,
    rotation: int = 0,
    flip_horizontal: bool = False,
) -> dict[str, Any]:
    frame, metadata = read_oriented_frame(
        source,
        frame_index,
        rotation=rotation,
        flip_horizontal=flip_horizontal,
    )
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), frame):
        raise OSError(f"Could not write preview frame: {output_path}")
    metadata["output_path"] = str(output_path)
    return metadata


def _sanitize_name(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
    return clean.strip("._") or "tracking_run"


def crop_video_to_frames(
    source: Path,
    frame_dir: Path,
    *,
    rotation: int,
    flip_horizontal: bool,
    roi_x: int,
    roi_y: int,
    roi_width: int,
    roi_height: int,
) -> dict[str, Any]:
    source = Path(source).resolve()
    frame_dir = Path(frame_dir).resolve()
    frame_dir.mkdir(parents=True, exist_ok=True)
    cap = _open_video(source)
    count = 0
    crop_bounds: tuple[int, int, int, int] | None = None
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            frame = orient_frame(frame, rotation, flip_horizontal)
            height, width = frame.shape[:2]
            x0 = max(0, min(int(roi_x), width - 1))
            y0 = max(0, min(int(roi_y), height - 1))
            requested_width = int(roi_width) if int(roi_width) > 0 else width
            requested_height = int(roi_height) if int(roi_height) > 0 else height
            x1 = max(x0 + 1, min(width, x0 + requested_width))
            y1 = max(y0 + 1, min(height, y0 + requested_height))
            crop = frame[y0:y1, x0:x1]
            if crop.size == 0:
                raise ValueError("The selected ROI produced an empty crop.")
            if crop_bounds is None:
                crop_bounds = (x0, y0, x1 - x0, y1 - y0)
            output = frame_dir / f"frame_{count:06d}.png"
            if not cv2.imwrite(str(output), crop):
                raise OSError(f"Could not write cropped frame: {output}")
            count += 1
    finally:
        cap.release()

    if count < 2 or crop_bounds is None:
        raise ValueError("Tracking requires at least two readable video frames.")
    return {
        "frame_count": count,
        "roi_x": crop_bounds[0],
        "roi_y": crop_bounds[1],
        "roi_width": crop_bounds[2],
        "roi_height": crop_bounds[3],
        "frame_dir": str(frame_dir),
    }


def load_cropped_frames(frame_dir: Path) -> list[Any]:
    paths = sorted(Path(frame_dir).glob("*.png"))
    frames: list[Any] = []
    for path in paths:
        frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if frame is not None:
            frames.append(frame)
    return frames


def run_optical_flow(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.source).resolve()
    output_dir = Path(args.output_dir).resolve()
    export_name = _sanitize_name(args.export_name or source.stem)
    output_dir.mkdir(parents=True, exist_ok=True)
    frame_dir = output_dir / "cropped_frames"

    crop_meta = crop_video_to_frames(
        source,
        frame_dir,
        rotation=args.rotation,
        flip_horizontal=args.flip_horizontal,
        roi_x=args.roi_x,
        roi_y=args.roi_y,
        roi_width=args.roi_width,
        roi_height=args.roi_height,
    )
    frames = load_cropped_frames(frame_dir)
    if len(frames) < 2:
        raise ValueError("Optical flow requires at least two cropped frames.")

    roi_bounds = (
        int(crop_meta["roi_x"]),
        int(crop_meta["roi_y"]),
        int(crop_meta["roi_width"]),
        int(crop_meta["roi_height"]),
    )
    settings = OpticalFlowSettings(
        mask_percentile=args.mask_percentile,
        gaussian_blur_kernel=args.flow_blur_kernel,
        winsize=args.flow_winsize,
        microns_per_pixel=args.microns_per_pixel,
        seconds_per_frame=args.seconds_per_frame,
    )
    fingerprint = build_optical_flow_fingerprint(
        sample_id=export_name,
        roi_bounds=roi_bounds,
        settings=settings,
        data_identity=str(source),
        frame_count=len(frames),
    )
    result = compute_optical_flow_motion_index(
        frames,
        settings,
        sample_id=export_name,
        data_identity=str(source),
        roi_bounds=roi_bounds,
        fingerprint=fingerprint,
    )
    if not result.has_valid_result:
        raise ValueError(result.failure_reason or "Optical flow analysis failed.")

    overlay_path = output_dir / f"{export_name}_flow_overlay.png"
    cache = build_flow_cache(
        frames,
        settings,
        sample_id=export_name,
        fingerprint=fingerprint,
    )
    arrows = get_flow_arrows_for_frame(
        cache,
        0,
        len(frames),
        OpticalFlowVisualizationSettings(
            arrow_spacing_px=args.flow_arrow_spacing,
            arrow_scale=args.flow_arrow_scale,
        ),
    )
    overlay = render_optical_flow_overlay(frames[0], arrows)
    if not cv2.imwrite(str(overlay_path), overlay):
        raise OSError(f"Could not write flow overlay: {overlay_path}")

    summary_path = output_dir / f"{export_name}_optical_flow.json"
    pair_csv_path = output_dir / f"{export_name}_flow_pair_summaries.csv"
    _write_flow_pair_csv(result, pair_csv_path)

    payload = result.summary_dict()
    payload["analysis_method"] = ANALYSIS_OPTICAL_FLOW
    payload["primary_velocity_metric"] = "optical_flow_general_movement_um_s"
    payload["absolute_velocity_index_um_per_s"] = result.optical_flow_general_movement_um_s
    payload["downward_velocity_index_um_per_s"] = result.optical_flow_downward_motion_um_s
    payload["general_movement_index_um_per_s"] = result.optical_flow_general_movement_um_s
    payload["output_dir"] = str(output_dir)
    payload["outputs"] = {
        "summary_json": str(summary_path),
        "flow_overlay_png": str(overlay_path),
        "flow_pair_csv": str(pair_csv_path),
    }
    payload["run_context"] = {
        "source_path": str(source),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "rotation": args.rotation,
        "flip_horizontal": args.flip_horizontal,
        "analysis_method": ANALYSIS_OPTICAL_FLOW,
        **crop_meta,
    }
    summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    manifest = output_dir / "shiny_run_manifest.json"
    manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    payload["run_manifest"] = str(manifest)
    return payload


def _write_flow_pair_csv(result: Any, path: Path) -> None:
    import csv

    fieldnames = [
        "frame_a",
        "frame_b",
        "valid_pixel_count",
        "valid_pixel_fraction",
        "saturated_pixel_fraction",
        "mean_magnitude_px_frame",
        "mean_downward_px_frame",
        "mean_net_x_px_frame",
        "mean_net_y_px_frame",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for summary in result.frame_pair_summaries:
            writer.writerow(
                {
                    "frame_a": summary.frame_a,
                    "frame_b": summary.frame_b,
                    "valid_pixel_count": summary.valid_pixel_count,
                    "valid_pixel_fraction": summary.valid_pixel_fraction,
                    "saturated_pixel_fraction": summary.saturated_pixel_fraction,
                    "mean_magnitude_px_frame": summary.mean_magnitude_px_frame,
                    "mean_downward_px_frame": summary.mean_downward_px_frame,
                    "mean_net_x_px_frame": summary.mean_net_x_px_frame,
                    "mean_net_y_px_frame": summary.mean_net_y_px_frame,
                }
            )


def run_tracking(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.source).resolve()
    output_dir = Path(args.output_dir).resolve()
    export_name = _sanitize_name(args.export_name or source.stem)
    output_dir.mkdir(parents=True, exist_ok=True)
    frame_dir = output_dir / "cropped_frames"

    crop_meta = crop_video_to_frames(
        source,
        frame_dir,
        rotation=args.rotation,
        flip_horizontal=args.flip_horizontal,
        roi_x=args.roi_x,
        roi_y=args.roi_y,
        roi_width=args.roi_width,
        roi_height=args.roi_height,
    )
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
    result = run_motion_index_analysis(
        frame_dir,
        output_dir=output_dir,
        final_export_name=export_name,
        sample_id=export_name,
        params=params,
        preview_fps=args.preview_fps,
    )
    payload = result.summary_dict()
    payload["analysis_method"] = ANALYSIS_LANDMARK_TRACKING
    payload["run_context"] = {
        "analysis_method": ANALYSIS_LANDMARK_TRACKING,
        "source_path": str(source),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "rotation": args.rotation,
        "flip_horizontal": args.flip_horizontal,
        **crop_meta,
    }
    Path(result.summary_json).write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    manifest = output_dir / "shiny_run_manifest.json"
    manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    payload["run_manifest"] = str(manifest)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("probe", help="Read video metadata")
    probe.add_argument("source", type=Path)

    frame = subparsers.add_parser("frame", help="Extract one oriented preview frame")
    frame.add_argument("source", type=Path)
    frame.add_argument("output", type=Path)
    frame.add_argument("--frame-index", type=int, default=0)
    frame.add_argument("--rotation", type=int, choices=[0, 90, 180, 270], default=0)
    frame.add_argument("--flip-horizontal", action="store_true")

    browser_preview = subparsers.add_parser(
        "browser-preview",
        help="Convert a legacy tracking preview to browser-compatible WebM",
    )
    browser_preview.add_argument("source", type=Path)
    browser_preview.add_argument("output", type=Path)

    run = subparsers.add_parser("run", help="Crop a video ROI and run analysis")
    run.add_argument("source", type=Path)
    run.add_argument("output_dir", type=Path)
    run.add_argument("--export-name", default="")
    run.add_argument(
        "--analysis-method",
        choices=sorted(ANALYSIS_METHODS),
        default=ANALYSIS_LANDMARK_TRACKING,
    )
    run.add_argument("--rotation", type=int, choices=[0, 90, 180, 270], default=0)
    run.add_argument("--flip-horizontal", action="store_true")
    run.add_argument("--roi-x", type=int, default=0)
    run.add_argument("--roi-y", type=int, default=0)
    run.add_argument("--roi-width", type=int, default=0)
    run.add_argument("--roi-height", type=int, default=0)
    run.add_argument("--mask-percentile", type=float, default=90.0)
    run.add_argument("--flow-blur-kernel", type=int, choices=[0, 3, 5], default=3)
    run.add_argument("--flow-winsize", type=int, default=15)
    run.add_argument("--flow-arrow-spacing", type=int, default=8)
    run.add_argument("--flow-arrow-scale", type=float, default=0.8)
    run.add_argument("--num-points", type=int, default=10)
    run.add_argument("--min-spacing", type=int, default=20)
    run.add_argument("--search-radius", type=int, default=8)
    run.add_argument("--patch-size", type=int, default=11)
    run.add_argument("--min-confidence", type=float, default=0.55)
    run.add_argument("--lookahead-frames", type=int, default=0)
    run.add_argument("--microns-per-pixel", type=float, default=0.265)
    run.add_argument("--seconds-per-frame", type=float, default=30.0)
    run.add_argument("--preview-fps", type=float, default=5.0)
    run.add_argument(
        "--tracking-method",
        choices=[TRACKING_METHOD_BRIGHTEST_LOCAL, TRACKING_METHOD_TEMPLATE],
        default=TRACKING_METHOD_BRIGHTEST_LOCAL,
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        if args.command == "probe":
            payload = probe_media(args.source)
        elif args.command == "frame":
            payload = extract_preview_frame(
                args.source,
                args.output,
                args.frame_index,
                rotation=args.rotation,
                flip_horizontal=args.flip_horizontal,
            )
        elif args.command == "browser-preview":
            payload = transcode_preview_to_webm(args.source, args.output)
        elif args.command == "run":
            if args.analysis_method == ANALYSIS_OPTICAL_FLOW:
                payload = run_optical_flow(args)
            else:
                payload = run_tracking(args)
        else:
            raise ValueError(f"Unsupported command: {args.command}")
    except Exception as exc:
        _json_print({"ok": False, "error": str(exc)})
        raise SystemExit(1) from exc
    payload["ok"] = True
    _json_print(payload)


if __name__ == "__main__":
    main()
