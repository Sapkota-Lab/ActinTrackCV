"""
extract_2d_frames.py
Extract evenly-sampled PNG frames from all AVI/MP4 movies in the ActinTrackCV
raw dataset, write them into an organized folder tree, and produce a
frames_index.csv manifest for downstream tagging in Roboflow.

Requirements:
    pip install opencv-python pandas tqdm
"""

from pathlib import Path
import cv2
import pandas as pd
from tqdm import tqdm

# ---- CONFIG ----------------------------------------------------------------
RAW_ROOT   = Path("raw_source")          # folder containing the 4 condition dirs
OUT_ROOT   = Path("frames")              # output PNGs go here
INDEX_CSV  = Path("frames_index.csv")    # manifest
FRAMES_PER_MOVIE = 10                    # evenly sampled frames per movie
VIDEO_EXTS = {".avi", ".mp4"}
# Skip TIF stacks: those are the 3D track, handled separately.
# ---------------------------------------------------------------------------

def parse_condition(condition_dirname: str):
    """1_WT_218 -> ('WT', '218'); 3_Mutant_515 -> ('Mutant', '515')"""
    parts = condition_dirname.split("_", 2)
    # parts = ['1', 'WT', '218']  or  ['3', 'Mutant', '515']
    return parts[1], parts[2]

def evenly_spaced_indices(total: int, k: int):
    """Return k indices spread across [0, total-1], inclusive."""
    if total <= k:
        return list(range(total))
    # Avoid the very first/last few frames (often camera warmup or fade)
    return [int(round(i * (total - 1) / (k - 1))) for i in range(k)]

def process_video(path: Path, out_dir: Path, sample_k: int):
    cap = cv2.VideoCapture(str(path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total <= 0:
        cap.release()
        raise RuntimeError(f"Could not read frame count from {path}")
    want = set(evenly_spaced_indices(total, sample_k))
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i in want:
            # frame is BGR uint8. Keep as-is; PNG is lossless.
            saved.append((i, frame))
        i += 1
    cap.release()
    return total, saved

def main():
    records = []
    for cond_dir in sorted(RAW_ROOT.iterdir()):
        if not cond_dir.is_dir():
            continue
        try:
            condition, sample_id = parse_condition(cond_dir.name)
        except Exception:
            print(f"Skipping unparseable folder: {cond_dir.name}")
            continue

        for src in sorted(cond_dir.iterdir()):
            if src.suffix.lower() not in VIDEO_EXTS:
                continue  # skip .tif (3D track), .jpg (montage), ~$ temp files

            movie_id = src.stem  # e.g. "01" or "02_676-6-2"
            out_dir = OUT_ROOT / f"{condition}_{sample_id}_{movie_id}"
            print(f"-> {cond_dir.name}/{src.name}")
            total, frames = process_video(src, out_dir, FRAMES_PER_MOVIE)

            for frame_idx, img in frames:
                fname = f"{condition}_{sample_id}_{movie_id}_f{frame_idx:04d}.png"
                cv2.imwrite(str(out_dir / fname), img)
                records.append({
                    "filename": fname,
                    "condition": condition,
                    "sample_id": sample_id,
                    "movie_id": movie_id,
                    "source_file": str(src.relative_to(RAW_ROOT)),
                    "frame_num": frame_idx,
                    "total_frames": total,
                    "batch_name": f"{condition}_{sample_id}_{movie_id}",
                })

    df = pd.DataFrame(records).sort_values(
        ["condition", "sample_id", "movie_id", "frame_num"]
    )
    df.to_csv(INDEX_CSV, index=False)
    print(f"\nWrote {len(df)} frames across {df['batch_name'].nunique()} movies")
    print(f"Index: {INDEX_CSV.resolve()}")

if __name__ == "__main__":
    main()
