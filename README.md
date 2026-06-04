# ActinTrackCV

Desktop app for **Arabidopsis** fluorescence microscopy time-lapse data showing labeled F-actin cables near the egg apparatus / nucleus-adjacent region. Organize files by **condition group** and **biological batch**, run 2D preprocessing (orientation + rectangular ROI), and export cropped data for later analysis.

## Install dependencies

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Requirements: Python 3.10+, OpenCV, NumPy, pandas, PyQt6, tifffile.

## Run the app

**To run the app, use:** `python run_app.py` from the project root (with your virtual environment activated).

**If you are on macOS/Linux, run:**

```bash
chmod +x run_app.sh    # once
./run_app.sh
```

**If you are on Windows, run:**

```bat
run_app.bat
```

**The main entry point is:** `actintrack_app.main` → `actintrack_app.gui.run_app()`

Equivalent commands:

```bash
python run_app.py
python -m actintrack_app.main
```

Launchers activate `.venv` or `venv` automatically when present. If dependencies are missing, `run_app.py` prints install instructions.

## Project layout

```text
ActinTrackCV/                    ← project root (workspace)
  raw/
    <condition_group>/
      <biological_batch>/
        <sample_id>.avi
  processed/
    <condition_group>/
      Batch 1/
        4_Mutant_175--01.mp4
        4_Mutant_175--01_metadata.json
        4_Mutant_175--01_orientation_preview.png
        4_Mutant_175--01_roi_preview.png
  metadata/
    samples.csv
    batches.json
    crop_metadata.json
  raw_source/                    ← optional read-only source tree (not modified on import)
```

### Condition groups (examples)

- `1_WT_218`
- `2_WT_550`
- `3_Mutant_515`
- `4_Mutant_175`

### Biological batches

Within each condition group, a **biological batch** is one Arabidopsis sample (default names `Batch 1`, `Batch 2`, …; renamable while keeping `batch_number` in metadata). Videos usually get their own batch on import; multiple still images may share one batch.

Hierarchy:

```text
condition / group
  └── biological batch
        └── individual videos or images
```

Create and rename batches in the app under **Biological Batch**. Imports go into `raw/<group>/<batch_name>/`.

### Where raw files go

- **Import in the app:** copies into `raw/<condition>/<biological_batch>/` (original paths unchanged).
- **Optional source tree:** `raw_source/<condition>/` or `raw_source/<condition>/<batch>/` for bulk import.

### Where processed outputs are saved

After **Process Sample** or **Process Approved Samples in Biological Batch**:

`processed/<condition>/<biological_batch>/` using export names such as `4_Mutant_175--01.mp4` or `1_WT_218--07--00.png`.

## Application menu (macOS menu bar)

| Menu | Actions |
|------|---------|
| **File** | New/Open workspace, recent workspaces, **Import Data…**, exit |
| **Workspace** | Refresh workspace, open folder, purge & cleanup |
| **Batch** | Create/rename/delete empty batch |
| **Help** | How to run, about |

Purge options keep **raw** files unless you explicitly remove a workspace raw copy when deleting a single file.

### Import Data dialog (**File → Import Data…**)

1. **Select files** (images, one video, or raw formats).
2. Review **detected import type** (image sequence, video, or WIP raw/3D).
3. Choose **condition group** and **biological batch** (create/rename batch in the dialog).
4. Optional **notes**, then **Import**.

Rules: multiple images per batch; one `.avi`/`.mp4` at a time; no mixed image+video; raw `.oib`/`.oir`/multi-page TIFF stacks show a WIP message and are not imported.

## Workflow (GUI)

1. Open or create the workspace (**File → New/Open Workspace**).
2. Import data (**File → Import Data…**) — select files, then condition group and biological batch.
3. Filter the sample list by condition group and batch in the left panel.
4. Open a file → orient manually → draw a rectangle around the **usable actin-rich region**.
5. **Save Annotation** → optional **Apply Annotation to Batch** (defaults to the **same biological batch only**).
6. Review propagated files: **Approve ROI** / adjust / **Reject ROI**.
7. **Process Approved Samples in Biological Batch** to write cropped exports.

Velocity estimation is not implemented yet.

## Batch annotation propagation

**Apply Annotation to Batch** copies orientation + rectangle ROI from the current file to other targets. Scopes:

| Scope | Meaning |
|--------|---------|
| **Same biological batch** (default) | Other files in the same `batch_name` under the same condition |
| **Unprocessed files in batch** | Same batch, only `imported` / unmarked files |
| **All files in condition** | Entire condition group (explicit opt-in; crosses biological batches) |
| **Selected files** | Multi-select in the sample list |

Conservative rules:

- Propagated rows are marked `roi_propagated_needs_review` in `samples.csv`.
- Approved/processed annotations are not overwritten unless you enable overwrite (they are still skipped if already approved/processed).
- Propagation metadata records `source_batch`, `target_batch`, `roi_scaling_method`, and `review_status: pending`.
- Only **approved** samples are bulk-exported.

## Metadata

`samples.csv` includes batch/export fields: `batch_number`, `batch_name`, `auto_export_name`, `custom_export_name`, `final_export_name`, `is_video`, `frame_number`, `annotation_source`, `review_status`, etc. Opening a workspace runs **migration** to add missing columns without deleting existing rows.

`metadata/batches.json` stores per-batch registry (`batch_number`, `contains_video`, file counts, dates). `metadata/crop_metadata.json` holds per-sample orientation/ROI annotations.

### Export naming

- Video: `<condition>--<batch_2digit>` → `4_Mutant_175--01`
- Still image: `<condition>--<batch>--<frame_2digit>` → `1_WT_218--07--14`

Edit **Export / annotated output name** in the GUI to set a custom name (stored in metadata; `final_export_name` is used on disk).

## Other scripts

- `extract_2d_frames.py` — extract PNG frames from videos (Roboflow / legacy pipeline)
- `preprocess_ab_regions.py` — CLI crop using actin-signal ROI detection
- `python -m actintrack_app.main` — same GUI as `run_app.py`

See `PROJECT_OVERVIEW.md` for broader project context.
