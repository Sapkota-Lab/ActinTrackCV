# ActinTrackCV

Desktop app for **Arabidopsis** reproductive-cell fluorescence microscopy: 2D time-lapse movies of elongated ovule / embryo-sac cells expressing **Lifeact** (F-actin) and **H2B** (nucleus) reporters. Organize **Data** by **Breed** and **Sample**, orient frames, draw a rectangular **ROI**, review motion metrics in **Metric Analysis View** (template tracking and optical flow), and aggregate saved results in **Analysis**. The **R Shiny** app (`shiny_app/`) provides the lab-facing review workflow; Python remains the analysis backend.

**Experimental design (current dataset):** WT lines **218** and **550** (`FWApro::Lifeact-Venus` with H2B reporters) versus mutants **515** (`scar2` on #218) and **175** (`xig` on #218).

Current analysis direction: refine a traditional computer-vision tracker before using AI model training. The working method tracks the brightest actin points or small bright regions from the first frame, searches locally for corresponding bright points in each next frame, and converts calibrated frame-to-frame displacement into velocity.

Numerical tracker validation is documented in [`docs/TRACKER_VALIDATION_PROTOCOL.md`](docs/TRACKER_VALIDATION_PROTOCOL.md). Run the automated synthetic ground-truth gates locally with `scripts/run_validation_gates.sh`, or rely on the GitHub Actions workflow in [`.github/workflows/validation.yml`](.github/workflows/validation.yml) on push/PR to `main`. For **Layer 2** bead-slide validation, use [`examples/layer2_stage_calibration.manifest.example.json`](examples/layer2_stage_calibration.manifest.example.json) with `scripts/validate_stage_calibration.py`.

The current Python desktop app is a research prototype/workbench. The final user-facing application target is **R Shiny**, with the Python/OpenCV analysis code producing stable CSV/JSON/QC outputs for Shiny to display.

For a plain-language record of the project direction changes, see [`PROJECT_CHANGES_NATURAL_LANGUAGE.md`](PROJECT_CHANGES_NATURAL_LANGUAGE.md).

**Active Python workbench import formats:** AVI and MP4 only. Image sequences and 3D/raw microscopy analysis are postponed.

## Current dataset (`raw/`)

Local workspace data under `raw/` (gitignored) currently holds **21 media files** in four breed folders:

| Folder | Files | Formats |
|--------|------:|---------|
| `1_WT_218` | 7 | 2× TIFF, 1× AVI, 1× JPG montage, 3× OIR |
| `2_WT_550` | 5 | 5× AVI |
| `3_Mutant_515` | 5 | 1× AVI, 4× MP4 |
| `4_Mutant_175` | 4 | 4× AVI |

**Naming:** `{WT\|MUT}{id}_{0001..}.{ext}` inside `{ordinal}_{WT\|Mutant}_{id}/` (e.g. `2_WT_550/WT550_0003.avi`).

**Time-lapse exports:** 15 videos, each **15 frames** at **6.0 fps playback** (export timing — lab notes say **30 sec/frame** for biological interval).

**Higher-fidelity microscopy (`1_WT_218` only):** 16-bit ImageJ TIFF hyperstacks and Olympus **FV3000** OIR Z-stacks (60× water objective, EYFP/Lifeact channel).

Legacy manifests such as `frames_index.csv` and the `raw_source/` archive use older filenames (`01.avi`, `03.avi`, etc.) that refer to the same movies.

## Download for macOS

Most users do not need Python or the source code — download the prebuilt app from the [**Releases**](https://github.com/Sapkota-Lab/ActinTrackCV/releases) page.

1. Download `ActinTrackCV-0.2.0-macos-arm64.zip` from the [`v0.2.0` release](https://github.com/Sapkota-Lab/ActinTrackCV/releases/tag/v0.2.0) (the latest macOS build; Windows is on the newer `v0.2.1` release).
2. Unzip it (double-click in Finder).
3. Open `ActinTrackCV.app`.
4. Because this build is **unsigned**, macOS may block the first launch. If so, open
   **System Settings → Privacy & Security**, scroll to the message that *"ActinTrackCV" was blocked*,
   and click **Open Anyway**. After the first approval, it opens normally.

Notes for this build:

- **Unsigned macOS (Apple Silicon) pre-release / internal test build** — not signed, notarized, or a polished installer. Apple Silicon only (no Intel/universal build yet), and no `.dmg` yet.
- **AVI/MP4 loading still needs validation on clean Macs with real microscopy videos** — please report any playback issues.
- ROI auto-suggestion can occasionally fail — press **Suggest** again or draw the ROI manually.
- Project/workspace data defaults to **`~/Documents/ActinTrackCV`** (created on first launch).
- Your external AVI/MP4 **Data** files stay outside the app — they are never bundled or deleted.

## Download for Windows

A **Windows 10/11 x64 pre-release** is available as a one-folder zip (not an installer wizard yet).

1. Download `ActinTrackCV-0.2.1-windows-x64-onefolder.zip` from the [**Releases**](https://github.com/Sapkota-Lab/ActinTrackCV/releases) page.
2. Unzip it.
3. Open the `ActinTrackCV` folder.
4. Double-click `ActinTrackCV.exe`.
5. **Keep the whole folder together** — do not move `ActinTrackCV.exe` out on its own (it needs the `_internal` folder next to it).

Notes for this build:

- This is an **unsigned Windows pre-release / internal test build**. Windows SmartScreen may warn on first launch — click **More info → Run anyway**.
- Project/workspace data defaults to **`Documents\ActinTrackCV`** under your user profile (created on first launch), not inside the app folder.
- Your external AVI/MP4 **Data** files stay outside the app — they are never bundled or deleted.
- A signed setup wizard is future work.

Developers who want to run from source or build the app: see [Install dependencies](#install-dependencies) and [Build from source](#build-from-source) below.

## Install dependencies

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Requirements: Python 3.10+, OpenCV, NumPy, pandas, PyQt6, tifffile.

## Run the app

Run `python run_app.py` from the project root with the virtual environment activated.

On macOS/Linux:

```bash
chmod +x run_app.sh    # once
./run_app.sh
```

On Windows:

```bat
run_app.bat
```

The main entry point is `actintrack_app.main` → `actintrack_app.gui.run_app()`. Equivalent:

```bash
python run_app.py
python -m actintrack_app.main
```

The launchers activate `.venv` or `venv` automatically when present.

## Run the R Shiny app

Install the R interface packages once, then run the application from the project root:

```r
install.packages(c(
  "shiny", "bslib", "ggplot2", "jsonlite", "png",
  "base64enc", "htmltools", "fontawesome"
))
shiny::runApp("shiny_app")
```

The Shiny app discovers source videos, supports interactive ROI selection, runs the traditional CV tracker, reviews QC outputs, compares completed runs, and inventories local z-stack files. See [`shiny_app/README.md`](shiny_app/README.md) for details.

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
6. **Metrics** — Template Tracking and Optical Flow Motion Index calculations are scheduled automatically after ROI autosave or settings changes (2.5 s debounce). Both run on **cropped ROI frames** using the current orientation and ROI.
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

The app creates these folders inside your workspace as you work:

```text
ActinTrackCV/                    ← project root (workspace)
  raw/                           ← source media and optional internal import copies
    <breed>/                     e.g. 2_WT_550/
      <PREFIX>_<NNNN>.<ext>      e.g. WT550_0003.avi
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

See [`ActinTrackCV_User_Documentation_Refined.md`](ActinTrackCV_User_Documentation_Refined.md) for the full user guide.

## Build from source

The frozen app never writes into its own bundle:

- The default workspace is `~/Documents/ActinTrackCV`, created on first launch. Manually chosen workspaces still load.
- External AVI/MP4 files and project folders (`raw/`, `processed/`, `previews/`, `metadata/`, `raw_source/`, `frames/`) are never bundled or deleted.

**Build the macOS `.app` bundle** (debuggable build; not a signed/notarized installer):

```bash
python -m pip install -r requirements-build.txt
bash packaging/macos/build_macos.sh
```

Output: `dist/ActinTrackCV.app`. It is **unsigned** — Gatekeeper warns on first launch, so right-click → Open.

Package the bundle into a release zip with `ditto` (preferred over plain `zip`, which can corrupt the `.app` bundle's symlinks/metadata):

```bash
ditto -c -k --keepParent dist/ActinTrackCV.app ActinTrackCV-0.2.0-macos-arm64.zip
```

`.dmg`, code signing, and notarization are future work. See [`packaging/macos/README.md`](packaging/macos/README.md) and [`packaging/RESOURCES.md`](packaging/RESOURCES.md).

**Build the Windows one-folder app** (must run on Windows 10/11 x64 — PyInstaller does not cross-compile):

```powershell
python -m pip install -r requirements-build.txt
powershell -ExecutionPolicy Bypass -File packaging\windows\build_windows.ps1
```

Output: `dist\ActinTrackCV\ActinTrackCV.exe` (one-folder, windowed). Package the **whole** folder into a release zip:

```powershell
Compress-Archive -Path dist\ActinTrackCV -DestinationPath ActinTrackCV-0.2.1-windows-x64-onefolder.zip -Force
```

The build is **unsigned** (SmartScreen warns; More info → Run anyway). An installer wizard and code signing are future work. See [`packaging/windows/README.md`](packaging/windows/README.md).

## Not implemented

- Image sequence import
- 3D / raw microscopy format import (`.oib`, `.oir`, multi-page TIFF stacks, etc.)

## Other scripts

- `extract_2d_frames.py` — extract PNG frames from videos (legacy pipeline)
- `preprocess_ab_regions.py` — CLI crop using actin-signal ROI detection
- `python -m actintrack_app.main` — same GUI as `run_app.py`

See `PROJECT_OVERVIEW.md` for broader project context.

## Related: SeedThermal (separate project)

FLIR ONE Edge seed thermal phenotyping lives in **[`SeedThermal/`](SeedThermal/README.md)** — independent install, scripts, and outputs. It is not part of the ActinTrackCV microscopy or F-actin tracking pipeline.
