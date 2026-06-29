# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

ActinTrackCV quantifies **F-actin motion/velocity** from *Arabidopsis* reproductive-cell fluorescence microscopy (Lifeact + H2B reporters). The scientific goal is comparing actin dynamics across four genetic backgrounds: `1_WT_218`, `2_WT_550`, `3_Mutant_515` (scar2), `4_Mutant_175` (xig).

Two architectural facts shape almost everything:

1. **The current tracker is traditional computer vision, not AI.** It finds the brightest actin points/regions in frame 0, searches locally for matches in each subsequent frame, and converts calibrated displacement into velocity. Roboflow/DINOv3/learned models are historical context or deferred future work — do **not** introduce model-training dependencies into the tracking path. See `PROJECT_OVERVIEW.md` and `PROJECT_CHANGES_NATURAL_LANGUAGE.md`.
2. **PyQt is a workbench; R Shiny is the product.** `actintrack_app/` (PyQt6) is for algorithm development. `shiny_app/` (R) is the intended end-user app. They share the **same analysis core** (`actintrack_app.motion_index`) — Shiny reaches it through the `scripts/shiny_bridge.py` CLI. Keep the Python analysis producing stable CSV/JSON/QC outputs; don't make the PyQt GUI the deliverable.

Keep **2D tracking (Track A)** and **3D stack analysis (Track B)** decoupled. Track A (avi/mp4 velocity) is the active milestone; 3D thickness/depth from `.tif`/`.oir` stacks is future and must not complicate the 2D path. Active import formats are **AVI and MP4 only**.

## Commands

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # Python 3.10+, OpenCV, NumPy, pandas, PyQt6, tifffile

# Run the PyQt workbench (entry: actintrack_app.gui:run_app)
python run_app.py                         # or: python -m actintrack_app.main  /  ./run_app.sh

# Run the R Shiny app (target UI)
# In R: install shiny, bslib, ggplot2, jsonlite, png, base64enc, htmltools, fontawesome
Rscript -e 'shiny::runApp("shiny_app")'

# Python tests (unittest)
python -m unittest discover -s tests -v
python -m unittest tests.test_motion_index            # one module
python -m unittest tests.test_motion_index.ClassName.test_method   # one test

# R helper tests
Rscript tests/test_shiny_helpers.R

# Tracker validation gate (synthetic ground truth; exit 0 = pass)
.venv/bin/python scripts/validate_tracker.py

# Run tracking on one processed ROI video/sequence (CLI)
python scripts/run_motion_index.py <path-to-processed-roi.mp4>
```

## Architecture

### Analysis core — `actintrack_app/motion_index.py` (the heart of the project)

Single module, pure-function pipeline, no Qt dependency, reused by GUI / Shiny bridge / CLI / tests:

`load_frame_sequence` → `frame_to_signal` → `select_starting_points` (top-N bright points/regions in frame 0) → `track_points` (per-frame local search via `_brightest_point_in_window` or `_match_template_in_window`) → `compute_motion_indices` / `compute_velocity_summary` → `save_motion_index_outputs` (CSV + QC overlay video).

- Two tracking methods: `TRACKING_METHOD_BRIGHTEST_LOCAL` and `TRACKING_METHOD_TEMPLATE`, selected in `MotionIndexParams`.
- Calibration: `DEFAULT_MICRONS_PER_PIXEL = 0.265`, `DEFAULT_SECONDS_PER_FRAME = 30.0`. **Velocity must use the acquisition interval (~30 s/frame from lab notes), never video playback FPS** — OpenCV reports 6 fps which is export playback, not biological timing.
- `run_motion_index_analysis` is the top-level entry called by every frontend.

### Workspace & metadata layer

Workspaces are local on-disk folders (`raw/`, `processed/`, `metadata/`, `previews/`), **not committed to git**. Created/managed by `project_manager.py`.

- **Domain model** (`domain_models.py`): **Breed** (genetic group) → **Sample** (one imported AVI/MP4 + derived state) → **Data** (the file). UI/docs say "Breed/Sample/Data"; older code says "group/batch".
- **Schema v1 → v2 migration** is automatic on opening a workspace — `schema_compat.py` migrates legacy `samples.csv`/`batches.json` to `data_files.csv` + `sample_registry.json`. When touching metadata I/O, handle both schemas; fixtures live in `tests/fixtures/v1_workspace`.
- Persistence: `metadata.py` (CSV/JSON for samples + crop ROI), `sample_registry.py`, `crop_metadata.json`. Constants (folder names, status strings, group IDs) are centralized in `utils.py` — reuse them, don't hardcode.
- Sample lifecycle status strings (`STATUS_*` in `utils.py`) drive UI state: imported → roi_marked → processed → motion_index_generated.

### Service / workflow split (keep logic out of the GUI)

- `sample_service.py` — create/replace/clear samples; `sample_processor.py` — export oriented + ROI-cropped media to `processed/<group>/<batch>/`.
- `roi_workflow.py`, `preview_workflow.py`, `cropped_roi_preview.py` — ROI selection and the cropped-ROI live preview where draft tracking runs.
- `orientation.py` (rotate/flip + `RectROI` crop), `image_processing.py`, `video_processing.py` (media loading, `MediaLoadError`, TIFF pages), `import_classifier.py`, `file_importer.py`.
- `analysis_service.py` builds the read-only aggregation report; `analysis_view.py` renders it.
- `batch_manager.py` / `batch_annotation.py` / `purge_manager.py` — batch allocation, annotation propagation across a breed, and cleanup.

### GUI — `actintrack_app/gui.py` (~3.5k lines)

`MainWindow` is the orchestrator; `gui_canvas.py` (ROI drawing canvas), `gui_menus.py` (menu bar), `motion_index_gui.py` (advanced tracking settings UI in cropped-ROI preview). The GUI should call into the service modules above rather than embedding analysis logic.

### Shiny bridge — `scripts/shiny_bridge.py`

The **only** interface between the R app and Python. Subcommands: `probe` (video metadata), `frame` (oriented preview frame), `browser-preview` (webm), `run` (crop ROI + run tracking). Communicates via single-line JSON on stdout. `shiny_app/R/helpers.R::bridge_python()` locates the interpreter (`.venv/bin/python` → `venv/bin/python` → system `python3`) and calls the script with `system2`. When changing tracking inputs/outputs, update both sides of this contract.

## Conventions

- New analysis logic belongs in `motion_index.py` as testable pure functions (frames in, data out), with QC overlay outputs so the lab can visually reject bad tracks — verifiability is a project requirement, not a nicety.
- The synthetic validation gate (`scripts/validate_tracker.py` / `tracker_validation.py`) must still pass after tracker changes; it's the regression guard for the CV method.
- `raw/`, `processed/`, `metadata/`, model outputs, and microscopy file types are gitignored. Don't commit dataset files.
- `SeedThermal/` is an unrelated co-located project (FLIR seed thermal phenotyping) — not part of this pipeline.
