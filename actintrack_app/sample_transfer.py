"""Move a Sample (batch) between Condition Groups with on-disk folder moves."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from actintrack_app.batch_manager import (
    _batch_id,
    _next_batch_number,
    _normalize_batch_record,
    get_batch_by_name,
    refresh_batch_stats,
    sanitize_batch_name,
)
from actintrack_app.schema_compat import load_sample_registry_as_v1, save_sample_registry
from actintrack_app.condition_group_manager import (
    get_condition_group_name,
    resolve_condition_group_id,
    row_condition_group_id,
    sync_data_file_group_bridge,
)
from actintrack_app.metadata import load_samples_csv, save_samples_csv
from actintrack_app.project_manager import get_processed_batch_dir, get_raw_batch_dir
from actintrack_app.purge_manager import collect_processed_artifacts_for_sample
from actintrack_app.utils import METADATA_DIR, PREVIEWS_DIR, RAW_DIR, SAMPLES_CSV


class SampleMoveError(ValueError):
    """Raised when a cross-group Sample move cannot be completed safely."""


@dataclass(frozen=True)
class MoveSampleResult:
    sample_id: str
    source_condition_group_id: str
    target_condition_group_id: str
    batch_name: str
    moved: bool


def _row_dict_by_sample_id(root: Path, sample_id: str) -> dict[str, str]:
    df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)
    sub = df[df["sample_id"].astype(str) == str(sample_id)]
    if sub.empty:
        raise SampleMoveError(f"Sample not found: {sample_id}")
    return {str(k): str(v) for k, v in sub.iloc[0].items()}


def _preview_paths_for_row(root: Path, row: dict[str, str]) -> list[Path]:
    previews: list[Path] = []
    for path in collect_processed_artifacts_for_sample(root, row):
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if rel.parts[0] == PREVIEWS_DIR:
            previews.append(path)
    return previews


def _rename_path(src: Path, dest: Path, *, moves: list[tuple[Path, Path]]) -> None:
    if not src.exists():
        return
    if dest.exists():
        raise SampleMoveError(
            f"Cannot move Sample: destination already exists ({dest})."
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dest)
    moves.append((dest, src))


def _rollback_renames(moves: list[tuple[Path, Path]]) -> None:
    for dest, src in reversed(moves):
        try:
            if dest.exists() and not src.exists():
                src.parent.mkdir(parents=True, exist_ok=True)
                dest.rename(src)
        except OSError:
            pass


def _resolve_target_batch_number(
    registry: dict[str, list[dict[str, Any]]],
    target_gid: str,
    preferred: int,
) -> int:
    used = {
        int(entry.get("batch_number", 0) or 0)
        for entry in registry.get(target_gid, [])
        if str(entry.get("batch_number", "")).strip()
    }
    if preferred not in used:
        return preferred
    return _next_batch_number(registry, target_gid)


def move_sample_to_condition_group(
    root: Path,
    sample_id: str,
    target_condition_group_id: str,
) -> MoveSampleResult:
    """Physically move one Sample's batch folders to another Condition Group.

    ``sample_id`` is preserved. Returns ``moved=False`` when source and target
    are the same group (no-op). Raises ``SampleMoveError`` on validation or
  I/O failure (attempts to roll back folder renames).
    """
    root = Path(root).resolve()
    sid = str(sample_id).strip()
    if not sid:
        raise SampleMoveError("Sample ID is required.")

    target_gid = resolve_condition_group_id(root, target_condition_group_id)
    if not target_gid:
        raise SampleMoveError(f"Condition Group not found: {target_condition_group_id}")

    row = _row_dict_by_sample_id(root, sid)
    source_gid = row_condition_group_id(row)
    if not source_gid:
        raise SampleMoveError(f"Sample has no Condition Group: {sid}")

    batch_name = str(row.get("batch_name", "")).strip()
    if not batch_name:
        raise SampleMoveError(f"Sample has no batch name: {sid}")
    safe_batch = sanitize_batch_name(batch_name)

    if source_gid == target_gid:
        return MoveSampleResult(
            sample_id=sid,
            source_condition_group_id=source_gid,
            target_condition_group_id=target_gid,
            batch_name=safe_batch,
            moved=False,
        )

    if get_batch_by_name(root, target_gid, safe_batch):
        target_name = get_condition_group_name(root, target_gid)
        raise SampleMoveError(
            f"Cannot move Sample: Condition Group “{target_name}” already has "
            f"a Sample named “{safe_batch}”. Rename one of the Samples first."
        )

    registry = load_sample_registry_as_v1(root)
    source_entries = list(registry.get(source_gid, []))
    batch_entry: dict[str, Any] | None = None
    for entry in source_entries:
        if sanitize_batch_name(str(entry.get("batch_name", ""))) == safe_batch:
            if batch_entry is not None:
                raise SampleMoveError(
                    f"Duplicate registry entries for Sample “{safe_batch}” in "
                    f"{source_gid}."
                )
            batch_entry = dict(entry)

    if batch_entry is None:
        existing = get_batch_by_name(root, source_gid, safe_batch)
        if existing is None:
            raise SampleMoveError(
                f"Sample registry entry not found for “{safe_batch}” in {source_gid}."
            )
        batch_entry = dict(existing)

    remaining_source = [
        entry
        for entry in source_entries
        if sanitize_batch_name(str(entry.get("batch_name", ""))) != safe_batch
    ]

    try:
        source_batch_number = int(batch_entry.get("batch_number", row.get("batch_number", 1)))
    except (TypeError, ValueError):
        source_batch_number = 1

    target_batch_number = _resolve_target_batch_number(
        registry, target_gid, source_batch_number
    )
    target_display = get_condition_group_name(root, target_gid)

    old_raw = get_raw_batch_dir(root, source_gid, safe_batch)
    new_raw = get_raw_batch_dir(root, target_gid, safe_batch)
    old_proc = get_processed_batch_dir(root, source_gid, safe_batch)
    new_proc = get_processed_batch_dir(root, target_gid, safe_batch)

    preview_sources = _preview_paths_for_row(root, row)
    preview_moves: list[tuple[Path, Path]] = []
    folder_moves: list[tuple[Path, Path]] = []

    new_raw.parent.mkdir(parents=True, exist_ok=True)
    new_proc.parent.mkdir(parents=True, exist_ok=True)

    try:
        _rename_path(old_raw, new_raw, moves=folder_moves)
        if old_proc.exists():
            _rename_path(old_proc, new_proc, moves=folder_moves)

        target_preview_dir = root / PREVIEWS_DIR / target_gid
        target_preview_dir.mkdir(parents=True, exist_ok=True)
        for src_preview in preview_sources:
            dest_preview = target_preview_dir / src_preview.name
            _rename_path(src_preview, dest_preview, moves=preview_moves)

        registry[source_gid] = remaining_source
        updated_entry = _normalize_batch_record(batch_entry, target_gid)
        updated_entry["group"] = target_gid
        updated_entry["condition_group_id"] = target_gid
        updated_entry["breed"] = target_display
        updated_entry["batch_number"] = target_batch_number
        updated_entry["batch_id"] = _batch_id(target_gid, target_batch_number)
        target_entries = list(registry.get(target_gid, []))
        target_entries.append(updated_entry)
        registry[target_gid] = target_entries
        save_sample_registry(root, registry)

        df = load_samples_csv(root / METADATA_DIR / SAMPLES_CSV)
        mask = (df["group"].astype(str) == source_gid) & (
            df["batch_name"].astype(str).apply(sanitize_batch_name) == safe_batch
        )
        if not mask.any():
            raise SampleMoveError(f"No metadata rows found for Sample “{safe_batch}”.")

        old_raw_part = f"{RAW_DIR}/{source_gid}/{safe_batch}/"
        new_raw_part = f"{RAW_DIR}/{target_gid}/{safe_batch}/"

        for idx in df.index[mask]:
            row_dict = {str(k): str(v) for k, v in df.loc[idx].to_dict().items()}
            stored = str(df.at[idx, "stored_path"])
            if old_raw_part in stored:
                stored = stored.replace(old_raw_part, new_raw_part, 1)
            elif stored.startswith(f"{RAW_DIR}/{source_gid}/"):
                stored = stored.replace(
                    f"{RAW_DIR}/{source_gid}/",
                    f"{RAW_DIR}/{target_gid}/",
                    1,
                )
            row_dict["stored_path"] = stored
            row_dict["batch_number"] = str(target_batch_number)
            row_dict["batch_id"] = _batch_id(target_gid, target_batch_number)
            row_dict = sync_data_file_group_bridge(
                row_dict,
                group_id=target_gid,
                display_name=target_display,
            )
            for key, value in row_dict.items():
                if key in df.columns:
                    df.at[idx, key] = value

        save_samples_csv(root, df)
        refresh_batch_stats(root, target_gid, safe_batch)

    except Exception:
        _rollback_renames(preview_moves)
        _rollback_renames(folder_moves)
        raise

    return MoveSampleResult(
        sample_id=sid,
        source_condition_group_id=source_gid,
        target_condition_group_id=target_gid,
        batch_name=safe_batch,
        moved=True,
    )
