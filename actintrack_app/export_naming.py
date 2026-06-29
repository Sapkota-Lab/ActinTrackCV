"""Auto-generated and user-custom export naming conventions."""

from __future__ import annotations

from pathlib import Path

from actintrack_app.utils import VIDEO_EXTENSIONS


def format_padded_number(value: int, minimum_width: int = 2) -> str:
    n = max(0, int(value))
    if n < 10**minimum_width:
        return f"{n:0{minimum_width}d}"
    return str(n)


def auto_export_name_video(group: str, batch_number: int) -> str:
    """e.g. 4_Mutant_175--01"""
    return f"{group}--{format_padded_number(batch_number)}"


def auto_export_name_image(
    group: str, batch_number: int, frame_number: int
) -> str:
    """e.g. 1_WT_218--07--00"""
    return (
        f"{group}--{format_padded_number(batch_number)}"
        f"--{format_padded_number(frame_number)}"
    )


def auto_export_name_for_sample(
    *,
    group: str,
    batch_number: int,
    is_video: bool,
    frame_number: int = 0,
) -> str:
    if is_video:
        return auto_export_name_video(group, batch_number)
    return auto_export_name_image(group, batch_number, frame_number)


def resolve_final_export_name(
    auto_export_name: str,
    custom_export_name: str | None,
) -> str:
    custom = (custom_export_name or "").strip()
    if custom:
        return custom
    return str(auto_export_name).strip()


def is_video_path(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def processed_video_path(batch_dir: Path, final_name: str) -> Path:
    return batch_dir / f"{final_name}.mp4"


def processed_image_path(batch_dir: Path, final_name: str) -> Path:
    return batch_dir / f"{final_name}.png"


def processed_metadata_path(batch_dir: Path, base_name: str) -> Path:
    """Batch-level metadata JSON (group--NN_metadata.json)."""
    if base_name.endswith("_metadata"):
        return batch_dir / f"{base_name}.json"
    return batch_dir / f"{base_name}_metadata.json"


def roi_and_crop_preview_paths(batch_dir: Path, final_name: str) -> tuple[Path, Path]:
    return (
        batch_dir / f"{final_name}_roi_preview.png",
        batch_dir / f"{final_name}_crop_preview.png",
    )


def raw_debug_preview_path(batch_dir: Path, final_name: str) -> Path:
    return batch_dir / f"{final_name}_raw_debug_preview.png"


def preview_paths(batch_dir: Path, final_name: str) -> tuple[Path, Path]:
    """Backward-compatible alias for roi + crop preview paths."""
    return roi_and_crop_preview_paths(batch_dir, final_name)


def processed_sample_metadata_path(batch_dir: Path, final_name: str) -> Path:
    return batch_dir / f"{final_name}_metadata.json"


def batch_metadata_base_name(group: str, batch_number: int) -> str:
    return f"{group}--{format_padded_number(batch_number)}"


def motion_index_trajectory_csv_path(batch_dir: Path, final_name: str) -> Path:
    return batch_dir / f"{final_name}_point_tracks.csv"


def motion_index_summary_json_path(batch_dir: Path, final_name: str) -> Path:
    return batch_dir / f"{final_name}_motion_index.json"


def motion_index_starting_points_path(batch_dir: Path, final_name: str) -> Path:
    return batch_dir / f"{final_name}_starting_points.png"


def motion_index_track_overlay_path(batch_dir: Path, final_name: str) -> Path:
    return batch_dir / f"{final_name}_track_overlay.png"


def motion_index_track_preview_path(batch_dir: Path, final_name: str) -> Path:
    return batch_dir / f"{final_name}_track_preview.mp4"


def motion_index_track_preview_webm_path(batch_dir: Path, final_name: str) -> Path:
    return batch_dir / f"{final_name}_track_preview.webm"


def motion_index_output_paths(batch_dir: Path, final_name: str) -> dict[str, Path]:
    return {
        "trajectory_csv": motion_index_trajectory_csv_path(batch_dir, final_name),
        "summary_json": motion_index_summary_json_path(batch_dir, final_name),
        "starting_points": motion_index_starting_points_path(batch_dir, final_name),
        "track_overlay": motion_index_track_overlay_path(batch_dir, final_name),
        "track_preview": motion_index_track_preview_path(batch_dir, final_name),
        "track_preview_webm": motion_index_track_preview_webm_path(
            batch_dir, final_name
        ),
    }
