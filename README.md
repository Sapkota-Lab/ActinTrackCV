# ActinTrackCV

Desktop app for **ROI-level / sample-level F-actin movement analysis** in 2D **Arabidopsis** fluorescence time-lapse **Data**. Organize Data by **Breed** and **Sample**, orient frames, draw a rectangular **ROI**, review motion metrics in **Metric Analysis View**, and aggregate saved results in **Analysis**.

**Active import formats:** AVI and MP4 only. Image sequences and 3D/raw microscopy formats are postponed.

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

## Terminology

| Term | Meaning |
|------|---------|
| **Breed** | Biological / experimental group (e.g. `1_WT_218`, `2_WT_550`, `3_Mutant_515`, `4_Mutant_175`) |
| **Sample** | One imported AVI/MP4 **Data** file plus derived project state (orientation, ROI, metrics, analysis, notes) |
| **Data** | User-facing term for an AVI/MP4 time-lapse file |
| **ROI** | Rectangular region of interest around the usable actin-rich area; **autosaves** as you work (no Save ROI button) |
| **Metric Analysis View** | Cropped ROI playback plus Template Tracking and Optical Flow metrics |
| **Template Tracking Motion Index** | Sparse bright-feature / template tracking on cropped ROI frames |
| **Optical Flow Motion Index** | Dense Farnebäck optical flow on cropped ROI frames |

## Workflow

1. **Open or create a workspace** — **File → New Workspace…** or **File → Open Workspace…**
2. **Add Sample** — **Sample → Add Sample…** (or right-click a Breed/Sample row) and select an AVI/MP4 file
3. **Select Data** — choose a Sample in the left panel to load its Data
4. **Orient and ROI** — rotate/flip the frame as needed, then draw a rectangle around the actin-rich region. The ROI **autosaves**; there is no Save ROI button and no Approve/Reject ROI workflow.
5. **Metric Analysis View** — open from the preview toolbar to enter cropped ROI playback and metric review. Playback loops continuously; use the frame slider to scrub manually. Playback speeds: **0.25×, 0.5×, 1×, 1.5×, 2×**. You can switch Samples while staying in Metric Analysis View.
6. **Metrics** — Template Tracking and Optical Flow Motion Index calculations are scheduled automatically after ROI autosave or settings changes (5 s debounce). Both run on **cropped ROI frames** using the current orientation and ROI.
7. **Analysis** — **Analysis → View Analysis…** for read-only aggregation by Breed and Sample from saved per-Sample results (does not re-run metrics).

### Metric Analysis View

Metric Analysis View replaces the older “preview cropped ROI only” workflow. It shows:

- Cropped ROI playback with optional **Optical Flow overlay** (sampled flow arrows; default **on**)
- **Template Tracking Motion Index** settings and results
- **Optical Flow Motion Index** settings, QC readout, and results

Switching Samples while in Metric Analysis View reloads that Sample’s cropped preview and clears stale in-memory metric state for the previous Sample.

### Template Tracking Motion Index

Sparse tracking of bright actin-associated features on cropped ROI frames:

- Selects locally bright starting points on the first frame
- Tracks small image templates frame-to-frame with template matching and optional lookahead recovery
- Produces **General Movement** and **Downward Motion** indices (µm/s)

Default tracking parameters (editable in Metric Analysis View): 5 starting points, 40 px minimum spacing, 11 px patch, 15 px search radius, 0.70 confidence, 3 lookahead frames, **0.2650 µm/pixel**, **0.2000 s/frame**.

### Optical Flow Motion Index

Dense **OpenCV Farnebäck** optical flow on consecutive cropped ROI frame pairs:

- Masks to bright F-actin-associated pixels using a **mask percentile** on the previous frame (default **90**)
- Optional Gaussian blur (default kernel **3**)
- Produces ROI-level metrics in µm/s and QC fractions:

| Metric | Meaning |
|--------|---------|
| **General Movement** | Mean flow speed (magnitude) over valid bright pixels |
| **Downward Motion** | Mean downward-only vertical flow component |
| **Net Y Velocity** | Mean signed vertical flow (up and down combined) |
| **Directionality Ratio** | Downward component ÷ total magnitude |
| **Valid Pixel Fraction** | Fraction of ROI pixels used per frame pair |
| **Saturated Pixel Fraction** | Fraction of valid pixels near saturation (QC) |

Default Farnebäck settings: `pyr_scale=0.5`, `levels=3`, `winsize=15`, `iterations=3`, `poly_n=5`, `poly_sigma=1.2`. Scale/time conversion uses the same **microns_per_pixel** and **seconds_per_frame** as Template Tracking.

The on-screen overlay shows **sampled flow vectors for visualization**, not individual filament trajectories.

Template Tracking and Optical Flow are **complementary**: sparse feature tracking vs. dense field motion. They answer related questions but should not be expected to match numerically.

### Analysis

**Analysis → View Analysis…** loads saved per-Sample metrics and groups them by **Breed** and **Sample**:

- Template Tracking and Optical Flow metrics are averaged **separately** at the Breed level
- Samples without valid results are excluded from the corresponding averages
- Missing values display as **—**
- Opening Analysis does **not** recompute metrics

### Scientific caveat

All motion metrics are **draft ROI-level movement / index estimates**. They summarize apparent motion within the drawn ROI. They are **not** definitive individual filament tracking and should not be over-interpreted biologically without consistent ROI placement, imaging settings, and scale/time calibration.

### Sample management

Right-click a Sample or Data row in the left panel:

| Action | Effect |
|--------|--------|
| **Rename Sample…** | Change the Sample display name |
| **Replace Data…** | Select a new AVI/MP4 file; clears derived ROI, tracking, and analysis state |
| **Delete Sample…** | Removes project state and derived results from the workspace; does **not** delete the original external Data file unless you opt to remove the project's internal copy |

## Project layout

Workspace folders are created locally when you use the app and are **not** committed to git:

```text
ActinTrackCV/                    ← project root (workspace)
  raw/                           ← optional internal copies of imported Data
    <breed>/
      <sample_id>.avi
  processed/                     ← cropped exports and motion-index outputs
  metadata/                      ← runtime registry and annotations
    data_files.csv
    sample_registry.json
    crop_metadata.json
    draft_tracking/              ← per-Sample Template Tracking draft results
    draft_optical_flow/            ← per-Sample Optical Flow draft results
```

Opening an older workspace automatically migrates legacy v1 metadata (`samples.csv`, `batches.json`) to the current v2 schema.

## Application menu

| Menu | Actions |
|------|---------|
| **File** | New/Open workspace, recent workspaces, exit |
| **Workspace** | Refresh workspace, open folder, remove missing files, purge/cleanup |
| **Sample** | Add Sample, Rename Sample |
| **Analysis** | View Analysis |
| **Help** | How to Run App, About |

Context menu (right-click Sample or Data row): Rename Sample, Replace Data, Delete Sample.

## Tests

```bash
python -m unittest discover -s tests -v
```

## User documentation

See [`ActinTrackCV_User_Documentation_Refined.docx`](ActinTrackCV_User_Documentation_Refined.docx) for the full user guide.

Regenerate the DOCX from Markdown (if pandoc is installed):

```bash
bash scripts/build_refined_user_documentation.sh
```

## Not implemented

- Image sequence import
- 3D / raw microscopy format import (`.oib`, `.oir`, multi-page TIFF stacks, etc.)

## Other scripts

- `extract_2d_frames.py` — extract PNG frames from videos (legacy pipeline)
- `preprocess_ab_regions.py` — CLI crop using actin-signal ROI detection
- `python -m actintrack_app.main` — same GUI as `run_app.py`

See `PROJECT_OVERVIEW.md` for broader project context.
