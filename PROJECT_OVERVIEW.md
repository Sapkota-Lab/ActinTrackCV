# ActinTrackCV Project Overview

## Executive Summary

ActinTrackCV is an early-stage research software project for quantifying F-actin organization, dynamics, and 3D structural features from **Arabidopsis** confocal microscopy data. The biological material is **single reproductive cells** (elongated ovule / embryo-sac cells) imaged with **Lifeact** (F-actin) and **H2B** (nucleus) reporters — not whole seeds or bulk tissue. The project is currently focused on a traditional computer-vision tracking workflow rather than Roboflow annotation or AI model training. The immediate work is refining, testing, and calibrating a bright-point tracking method for 2D actin velocity measurement.

The core scientific goal is to compare wild-type and mutant actin behavior across four genetic backgrounds: **WT_218**, **WT_550**, **Mutant_515** (`scar2` on #218), and **Mutant_175** (`xig` on #218). The local context and slide deck frame the biological questions around:

- F-actin cable folding differences.
- Actin velocity differences between A and B areas.
- Actin cable thickness.
- Whether a ring-like actin structure is moving.
- 3D actin structure from confocal Z-stacks.

Meeting update, 2026-06-11:

- Roboflow is no longer the active path.
- The near-term direction is to try traditional computer-vision methods before model training.
- The Dr. Ju tracking method is: in frame 0, find the 10 brightest actin points or small grouped bright regions; in each next frame, find the corresponding bright points in the local vicinity of the prior points; repeat through the sequence; convert absolute displacement/change into calibrated velocity using pixel size and acquisition interval.
- DINOv3 from MetaAI was mentioned as a possible all-around AI model to investigate, but AI models are secondary for now because they can make the project harder to explain and harder for others to trust or adopt.

For a plain-language record of direction changes, see `PROJECT_CHANGES_NATURAL_LANGUAGE.md`.

The current data are a mixture of lossy `.avi`/`.mp4` exports, a small number of higher-value `.tif` stacks, and newly received Olympus `.oir` z-stack files. Until the tracking method is validated and calibration metadata are confirmed, the practical plan is:

1. Establish the **2D velocity-tracking pipeline first** using the currently available `.avi`, `.mp4`, and usable 2D views/projections from `.tif` files.
2. Focus that 2D pipeline on the upper/central actin-rich tracking ROI shown by the A/B labels in `Picture1.jpg`; exclude the lower perinuclear/nucleus-adjacent C region from the primary tracking workflow.
3. Implement and validate the bright-point tracker before adding learned segmentation or foundation-model workflows.
4. Keep thickness, depth profiles, and other 3D metrics decoupled as a future module based on the `.tif` and `.oir` z-stacks.
5. Treat the current Python desktop app as a prototype/workbench and build the final user-facing interface in R Shiny around validated CSV/JSON/QC outputs.

The project should be thought of as two linked tracks:

- **Track A: 2D Tracking and Velocity** from `.avi`/`.mp4` frames plus usable 2D `.tif` slices/projections, focused on the actin-rich biological tracking ROI, bright-point coordinates, local frame-to-frame matching, and calibrated velocity over time. This is the main focus.
- **Track B: 3D Analysis** from 16-bit `.tif` and `.oir` Z-stacks, focused on filament thickness and depth profiles. This is a future milestone and should remain separate from the 2D tracking code path.

## Current Repository Layout

At the time of inspection, the repository contains these main components:

```text
.
├── README.md
├── PROJECT_OVERVIEW.md
├── requirements.txt
├── actintrack_app/          ← PyQt workbench (algorithm development)
├── shiny_app/               ← R Shiny UI (target end-user app)
├── scripts/                 ← shiny_bridge, validate_tracker, motion index CLI
├── tests/
├── docs/
├── extract_2d_frames.py     ← legacy frame extraction CLI
├── frames_index.csv         ← legacy manifest (older source filenames)
├── frames/                  ← extracted PNG frames (legacy pipeline)
├── local_context/           ← lab deck, reference images (gitignored)
├── raw/                     ← current flat source-media tree (gitignored)
├── raw_source/              ← older nested workspace archive (gitignored)
└── .venv/
```

Workspace data (`raw/`, `processed/`, `metadata/`) are created locally and are not committed to git.

### Root-Level Files

`README.md` describes the desktop app workflow and now states the active traditional computer-vision tracking direction.

`extract_2d_frames.py` is a legacy preprocessing script for video exports. It:

- Reads `.avi` and `.mp4` files from `raw_source/` (or an equivalent flat `raw/` tree if paths are updated).
- Skips `.tif` stacks and derived `.jpg` montage files.
- Extracts 10 evenly sampled frames per movie.
- Saves lossless `.png` files under `frames/<batch_name>/`.
- Writes `frames_index.csv` as a manifest for downstream tracking, QC, and data provenance.

`frames_index.csv` currently contains 150 rows across 15 movie batches. Every source movie reports 15 frames, and the script extracted frame numbers:

```text
0, 2, 3, 5, 6, 8, 9, 11, 12, 14
```

`.gitignore` is configured to ignore local environments, model outputs, image/video/raw microscopy file types, and `local_context/`. Note that some ignored assets may already be tracked in git if they were committed before `.gitignore` was updated. Repository hygiene should be checked before any serious commit or publication-facing cleanup.

`requirements.txt` lists the Python dependencies for the desktop app, tracking modules, and tests (`opencv-python`, `numpy`, `pandas`, `PyQt6`, `tifffile`, `tqdm`).

### `local_context/`

`local_context/Claude Transcript ActinTrack.md` is historical project context. It documents the earlier Roboflow annotation path, which is no longer active, plus frame extraction, dataset organization, and the uncertainty around actin cable annotation.

`local_context/Picture1.jpg` is the key reference image for the biological crop discussion. Its yellow labels mark regions within the cell. A/B correspond to the upper and central actin-rich tracking regions; C marks the lower perinuclear/nucleus-adjacent region that is excluded for the current 2D tracking milestone.

`local_context/F-actin imaging.pptx` is a slide deck with sample and experimental context. Extracted slide text indicates:

- Samples include `WT_218`, `WT_550`, `Mutant_515`, and `Mutant_175`.
- WT constructs include `FWApro::Lifeact-Venus` and `FWApro::H2B-mRuby2/mRuby3`.
- Mutant labels include `scar2 on #218` and `xig on #218`.
- The deck says the time-lapse videos are `30 sec/frame, 15 frames`.
- It mentions "Top to middle around 4-6 slices."
- It lists the F-actin dynamic questions noted above.

This slide deck is important because the exported video metadata reports playback at 6 fps, but the slide deck likely describes the actual biological acquisition interval. For analysis, use acquisition metadata or confirmed lab notes, not video playback FPS.

### `raw/` (current source media)

`raw/` is the flat source-media tree used by the active workspace. It should be treated as read-only input data. Files sit directly inside breed folders (no nested sample subfolders).

```text
raw/
├── 1_WT_218/     (7 files: TIFF, AVI, JPG, OIR)
├── 2_WT_550/     (5× AVI)
├── 3_Mutant_515/ (1× AVI, 4× MP4)
└── 4_Mutant_175/ (4× AVI)
```

**Naming convention:** `{WT|MUT}{id}_{NNNN}.{ext}` inside `{ordinal}_{WT|Mutant}_{id}/` (e.g. `WT550_0003.avi` in `2_WT_550/`).

**21 files total:** 11× AVI, 4× MP4, 3× OIR, 2× TIFF, 1× JPG montage.

#### `1_WT_218/`

| File | Type | Notes |
|---|---|---|
| `WT218_0001.tif` | TIFF | 30-page ImageJ hyperstack, 800×412 `uint16`; 2 channels × 15 slices; `unit=micron` |
| `WT218_0002.tif` | TIFF | 28-slice Z-stack, 360×196 `uint16`; `spacing=0.83` micron |
| `WT218_0003.avi` | AVI | 15 frames, 290×624, Motion JPEG |
| `WT218_0004.jpg` | JPEG | 1236×800 three-panel actin / nucleus / overlay montage |
| `WT218_0005–0007.oir` | OIR | Olympus FV3000 confocal Z-stacks; 334×629, 12-bit, 60× water objective, EYFP |

#### `2_WT_550/`

Five AVI exports, 15 frames each at 6.0 fps playback:

| File | Dimensions |
|---|---:|
| `WT550_0001.avi` | 302×604 |
| `WT550_0002.avi` | 394×808 |
| `WT550_0003.avi` | 310×624 |
| `WT550_0004.avi` | 316×692 |
| `WT550_0005.avi` | 338×752 |

#### `3_Mutant_515/`

| File | Type | Dimensions |
|---|---|---:|
| `MUT515_0001.avi` | AVI | 444×704 |
| `MUT515_0002.mp4` | MP4 (H.264) | 326×741 |
| `MUT515_0003.mp4` | MP4 | 308×663 |
| `MUT515_0004.mp4` | MP4 | 320×718 |
| `MUT515_0005.mp4` | MP4 | 335×676 |

All 15 frames, 6.0 fps playback.

#### `4_Mutant_175/`

Four AVI exports, 15 frames each at 6.0 fps playback:

| File | Dimensions |
|---|---:|
| `MUT175_0001.avi` | 420×384 |
| `MUT175_0002.avi` | 260×472 |
| `MUT175_0003.avi` | 364×406 |
| `MUT175_0004.avi` | 312×436 |

These are lossy video exports. They are usable for prototype tracking and QC, but they should not be treated as fully calibrated raw microscopy data. Lab slide notes say **30 sec/frame** for biological timing; video playback reports **6 fps**.

### `raw_source/` (legacy archive)

`raw_source/` is an older nested workspace snapshot, not a mirror of the current `raw/` tree. It uses the previous import layout (`raw/<breed>/<sample_name>/<file>`) and earlier filenames such as `01.avi` and `03.avi`. The committed `frames_index.csv` manifest references those legacy paths. Treat `raw/` as the authoritative on-disk inventory for the current dataset.

Additional OIR Z-stacks for line 218 also exist under `20260608_WT_Z stacks/` (gitignored).

### `frames/`

`frames/` contains extracted PNG frames from video exports via the legacy `extract_2d_frames.py` pipeline. There are 15 batch folders and 150 PNG frames total. The manifest `frames_index.csv` references **older source paths** (e.g. `2_WT_550/01.avi`) that correspond to the same movies now named `WT550_0001.avi` under `raw/`.

Each folder maps to one source movie:

```text
frames/
├── WT_218_03/
├── WT_550_01/
├── WT_550_02/
├── WT_550_03/
├── WT_550_04/
├── WT_550_05/
├── Mutant_515_01_676-8-2/
├── Mutant_515_02_676-6-2/
├── Mutant_515_03_676-6-3/
├── Mutant_515_04_676-6-3/
├── Mutant_515_05_676-8-3/
├── Mutant_175_01/
├── Mutant_175_02/
├── Mutant_175_03/
└── Mutant_175_04/
```

The current manifest distribution is:

| Condition | Sample | Movies | Extracted frames |
|---|---:|---:|---:|
| WT | 218 | 1 | 10 |
| WT | 550 | 5 | 50 |
| Mutant | 515 | 5 | 50 |
| Mutant | 175 | 4 | 40 |
| Total | - | 15 | 150 |

`frames/inspect_tiff.py` is a scratch inspection helper that reads `1_WT_218/WT218_0001.tif` (or the legacy `01.tif` name), extracts the middle slice for channels 0 and 1, normalizes each to 8-bit, and saves `middle_ch0.png` / `middle_ch1.png`. Treat it as exploratory code, not production.

## Current Data Interpretation

The current data are useful but limited.

The `.tif` stacks are the highest-value data because they are 16-bit and preserve real microscopy structure. `01.tif` has two channels and a likely Z axis:

- Channel 0: actin / LifeAct-Venus / F-actin signal.
- Channel 1: nucleus / H2B-mRuby signal.
- First axis: visually confirmed to represent different depths.

The `.avi` and `.mp4` files are exported videos. They are lossy, playback-oriented encodings and probably do not preserve full acquisition metadata, channel metadata, microscope calibration, or bit depth. They are still useful for:

- Roboflow annotation practice.
- 2D cell/nucleus segmentation prototypes.
- Actin signal browsing.
- Initial R Shiny frontend development.
- Early A/B crop, coordinate-tracking, and velocity-workflow design.

The videos report 15 frames each. OpenCV reports 6 fps, but the PowerPoint says 30 sec/frame. For biological measurements such as velocity, the 30 sec/frame slide note or raw acquisition metadata should be used. The video FPS likely reflects export playback speed, not experiment timing.

## Architecture and Workflow

### Track A: 2D Tracking and Velocity Workflow

The current 2D workflow is:

```text
raw/*.avi, *.mp4, and usable 2D views from *.tif
    -> extract_2d_frames.py
    -> detect upper/central actin tracking ROI
    -> frames/<movie_batch>/*.png or equivalent ROI frame products
    -> frames_index.csv
    -> detect the top N bright points or grouped bright regions in frame 0
    -> search locally around each prior point in the next frame
    -> link matched bright points through time
    -> velocity-over-time calculation
    -> QC overlays and result tables
```

This is the main computational path. The first deliverable should be a working 2D tracking pipeline that can ingest the current video-derived frames and available `.tif`-derived 2D views, isolate the A/B regions, track bright actin landmarks, and calculate velocity over time.

The current first-pass algorithm should stay simple and explainable:

1. In the first usable frame, detect the 10 brightest actin points or connected bright-pixel groups within the tracking ROI.
2. In the next frame, search near each prior point for the brightest local candidate.
3. Link candidates over time into short tracks.
4. Use absolute displacement/change across frames to calculate calibrated velocity.
5. Save overlays that show exactly which points were tracked so the lab can reject bad tracks visually.

The method needs explicit parameters that can be tested and surfaced in the app:

- number of points or regions to track, initially 10;
- bright-point grouping radius or connected-component threshold;
- local search radius in pixels;
- minimum intensity / prominence threshold;
- maximum allowed jump between frames;
- pixel size in microns;
- acquisition interval, likely 30 sec/frame from lab notes unless raw metadata says otherwise.

Roboflow annotations and AI model training are not active milestones. They can remain historical context and possible future work if traditional CV is insufficient.

### Track B: 3D Analysis Workflow

The 3D workflow is a future milestone and should remain separate from the 2D tracking path:

```text
raw/*.tif, *.oir
    -> inspect stack shape/channel order
    -> preserve 16-bit intensity
    -> annotate or segment in 3D-aware tooling
    -> quantify filament thickness and depth profiles
    -> export metrics for R Shiny visualization
```

Roboflow is fundamentally 2D and is not the right primary tool for true 3D annotation. Better candidates for 3D work include:

- napari
- napari-cellpose
- Cellpose 3D
- StarDist 3D
- nnU-Net / 3D U-Net
- ITK-SNAP, depending on annotation needs

The 3D metrics should eventually include filament thickness, depth profiles, cable or mesh volume, projected area, skeleton length, branch/junction counts, radial/perinuclear distribution, and Z-localization. These metrics should not be mixed into the initial 2D velocity-tracking code path.

## Historical Roboflow Context

Roboflow is no longer the active workflow. The transcript still documents several useful historical decisions:

- The original project was accidentally an Object Detection project. That would have caused polygon annotations to export as bounding boxes, which would destroy geometry for F-actin work.
- The project was duplicated into an Instance Segmentation project.
- Classes were renamed to script-friendly names:
  - `entire_cell`
  - `f_actin_cable`
  - `nucleus`
- Earlier annotations were considered methodologically unsafe because they treated the actin network as one large object rather than individual structures.
- Images were deleted from Roboflow and re-uploaded from the freshly extracted PNG frames.
- Upload organization used one Roboflow batch per movie.
- Tags used the convention:
  - `condition:WT` or `condition:Mutant`
  - `sample:<id>`
  - `movie:<batch_name>`

The transcript includes an annotation SOP draft, but no `ANNOTATION_SOP_v0.1.md` file was found in this repository during inspection. If the SOP was saved elsewhere, it should be copied into the repo once the lab is comfortable tracking it here.

Former near-term annotation policy, now superseded by the traditional CV direction:

- Do not randomly split frames across train/validation/test. Split by movie batch.
- Annotate only a small number of frames per movie at first, because frames within the same 15-frame sequence are correlated.
- Use `f0000` and `f0014` as a reasonable first pass if only two frames per movie are needed.
- Tag images where the nucleus is inferred from actin signal rather than directly visible: `no_nucleus_channel`.
- Tag images with unresolved actin meshwork: `dense_meshwork_visible`.
- Do not commit to per-cable labels until the lab decides whether the data actually resolves individual cables.

The relevant lesson from this branch is that dense actin meshwork is difficult to express as clean per-cable instance annotations. The current bright-point tracker avoids that annotation burden and is easier to explain: it measures motion of high-signal actin landmarks instead of requiring a trained segmentation model.

## Biological Tracking ROI Requirement

`Picture1.jpg` is the reference for the biological regions, not a directive to
crop equal-width display panels. The yellow A/B/C labels mark regions within the
cell:

- **A/B:** upper and central actin-rich filament regions where 2D tracking and velocity should be measured.
- **C:** lower perinuclear / nucleus-adjacent transition region that should be excluded for the current 2D tracking milestone.

The app now treats the crop as a biological signal problem. It detects the
actin-dominant foreground, computes row-wise signal mass and cell-width profiles,
and finds the sustained gradient where the upper/central filament shaft enters
the brighter lower perinuclear region. This avoids fixed pixel fractions and
avoids assuming that A/B/C are side-by-side panels.

For `.avi`, `.mp4`, and previewable `.tif` frames, the practical crop is:

- keep the upper/central filament tracking ROI above the detected cutoff;
- exclude the lower perinuclear/nucleus-adjacent region below the cutoff;
- allow manual cutoff adjustment when the detector is uncertain.

For raw `.tif` stacks, preserve channels and Z/T axes. Use the actin channel for
2D tracking ROI detection, and keep 3D thickness/depth analysis decoupled.

## 2D Tracking and A/B Metrics Direction

The primary script direction is now a traditional CV 2D tracking and velocity pipeline. Ratio-style A/B metrics can still be useful, but they are secondary to coordinate tracking and should be implemented only after the A/B input definition is clear. The phrase "A and B" is currently overloaded:

- In `Picture1.jpg`, A and B refer to biological tracking regions within the actin-rich cell body.
- In the PowerPoint, "Actin velocity differences between A and B areas" likewise appears to mean biological areas or regions of the cell.

Before implementing ratio or A/B comparison metrics, define the target explicitly. Likely candidates:

1. **Region ratio:** compare actin intensity, cable density, velocity, or thickness between two manually or automatically defined cell regions A and B.
2. **Channel ratio:** compare actin signal to the cell/nucleus context channel only when a raw multi-channel stack is available.
3. **Structure ratio:** compare actin cable signal to cell or nucleus signal.
4. **Motion ratio:** compare velocity or displacement metrics between two areas over time.

A robust first version of the 2D tracking script should:

- Accept an input image/video/stack path.
- Know whether the file is a raw stack, single frame, or rendered montage.
- Detect the upper/central filament tracking ROI using actin foreground, signal mass, and the gradient into the lower perinuclear region.
- If raw `.tif`: preserve 16-bit data and separate channel arrays.
- Detect the top N bright points or bright connected components in the first usable frame.
- In each subsequent frame, search within a local neighborhood around each previous point and select the strongest nearby candidate.
- Link candidate positions over time into tracks, with clear handling for missed detections and ambiguous matches.
- Calculate velocity over time using the confirmed acquisition interval, not video playback FPS.
- Write a CSV table of per-frame/per-track measurements.
- Save preview images or videos with tracked points, IDs, local search windows, and rejected candidates so users can verify exactly what was measured.

The first review pass for this method should answer:

- Are the detected points biologically meaningful actin landmarks, or just saturated/noisy pixels?
- Are multiple points collapsing onto the same bright region?
- Does the local search radius keep tracks stable without preventing real movement?
- Are tracks lost when intensity flickers or when the cell rotates/deforms?
- Does the velocity output use calibrated units, not raw pixels/frame, once pixel size and acquisition interval are available?

Optional A/B comparison outputs can then be added:

- mean intensity in A and B
- total signal in A and B
- thresholded foreground area in A and B
- `A / B` ratio with safe handling for zero or near-zero B
- velocity differences between A and B regions, once the regions are defined

Future versions can add skeletonization, optical-flow-assisted tracking, feature descriptors, or learned models once the bright-point baseline is understood. Cable thickness should remain part of the future 3D analysis module unless the lab defines a 2D proxy for it.

## R Shiny Frontend Direction

The final user-facing app should be R Shiny, not the current Python/PyQt prototype. The Python app and Python/OpenCV modules are useful as an algorithm-development workbench: they should produce stable CSV, JSON, and QC overlay outputs that the Shiny app can load and present.

Implementation status: `shiny_app/` now provides source discovery, real-frame preview, interactive ROI selection, tracking configuration/execution through `scripts/shiny_bridge.py`, QC image/video review, trajectory and velocity plots, group summaries, downloads, and z-stack inventory. Python remains the analysis backend, not the final user interface.

The Shiny app should use a multi-tab design that keeps distinct computational tasks separated.

The interface should not present 2D velocity tracking and 3D thickness/depth analysis as one combined workflow. They use different data assumptions, different algorithms, and different validation requirements.

### Tab 1: 2D Tracking

This is the main tab and the primary development focus.

Purpose:

- Review bright actin landmark coordinates over time.
- Display calibrated velocity over time.
- Restrict the current workflow to the upper/central actin-rich tracking ROI from the `Picture1.jpg` biological-region interpretation.
- Exclude the lower perinuclear/nucleus-adjacent region from computational tracking.
- Support `.avi`, `.mp4`, and available `.tif`-derived 2D views/projections when appropriate.

Core controls:

- condition selector: WT / Mutant
- sample selector: 218 / 550 / 515 / 175
- movie/file selector
- frame/timepoint selector
- signal ROI detector with manual cutoff review
- tracking method selector, initially focused on bright-point / bright-region tracking
- acquisition interval input, defaulting to lab-confirmed metadata rather than video playback FPS

Core displays:

- original frame or montage
- detected tracking ROI preview
- cutoff/foreground diagnostic view
- coordinate overlay
- track overlay
- velocity-over-time plot
- per-track results table

Expected outputs:

- cropped ROI images or frame products
- bright-point coordinate CSV
- track CSV
- velocity CSV
- preview overlays for QC

### Tab 2: 3D Analysis

This is a future milestone and should remain decoupled from Tab 1.

Purpose:

- Analyze `.tif` stacks.
- Preserve 16-bit intensity and stack structure.
- Measure filament thickness.
- Measure depth profiles.
- Support future 3D segmentation or skeletonization workflows.

Core controls:

- TIF stack selector
- channel selector
- slice/Z selector
- projection selector
- threshold/segmentation placeholder controls
- thickness/depth measurement placeholder controls

Core displays:

- slice viewer
- channel viewer
- Z-profile plot
- projected view
- future thickness overlay
- future depth-profile table

Expected outputs:

- thickness metrics
- depth-profile metrics
- 3D annotation or segmentation QC artifacts
- exported tables for later comparison with 2D results

### Shared Frontend Components

Both tabs can share:

- a project dashboard summary
- file and metadata browser
- warnings about data limitations
- export buttons
- QC image previews

The dashboard should show:

- number of conditions, samples, movies, extracted frames, and TIF stacks
- raw-file status
- tracking validation status
- warning that video export FPS is not acquisition timing
- reminder that Tab 1 is the active milestone and Tab 2 is future work

The Shiny frontend can start from `frames_index.csv` for source-frame metadata, but its main data products should come from the validated tracking pipeline: point coordinates, tracks, velocity summaries, parameters, and QC overlays.

## Key Technical Risks

1. **Raw files are still pending.** The exported videos have lost microscopy metadata. Raw `.nd2`, `.czi`, `.lif`, or full `.tif` stacks are needed for calibration, channel identity, true time interval, pixel size, Z-step, and defensible quantitative claims.

2. **Video FPS is misleading.** OpenCV reads 6 fps from the exports, but the PowerPoint says 30 sec/frame. Use acquisition metadata for scientific timing.

3. **The current dataset has only 15 source movies.** Even though there are 150 extracted PNG frames, these are highly correlated within movie. Effective independent sample count is closer to the number of source movies/cells than the number of extracted frames.

4. **AI annotation/training is not the current path.** Dense meshwork made per-cable annotation difficult, and the lab direction is now to refine an explainable traditional CV tracker first.

5. **Tracking ROI logic must be signal-driven.** A blind display-panel crop would destroy valid data. The current crop should follow actin foreground and the transition into the lower perinuclear region.

6. **TIF workflows must preserve bit depth.** Converting 16-bit TIF stacks to 8-bit PNG is fine for display and some annotation workflows, but quantitative analysis should preserve original 16-bit intensities.

7. **2D and 3D modules must stay decoupled.** The first milestone is 2D bright-point coordinate tracking and calibrated velocity. Thickness and depth-profile metrics are future 3D work and should not complicate the first tracking pipeline.

8. **Repository hygiene needs cleanup.** The repo contains local environment files, data, frames, and Mac `.DS_Store` files. `.gitignore` now excludes many of these categories, but tracked state should be checked before sharing or committing.

9. **Bright-point tracking needs validation.** The method is simple and explainable, but it can fail on saturation, flicker, dense regions, duplicate points, or local maxima that do not represent persistent actin landmarks.

## Immediate Next Steps

1. **Review the pushed traditional CV implementation.**
   - Confirm where the bright-point tracker lives in the app.
   - Check that it tracks the top 10 points or grouped bright regions from the first frame.
   - Check that each next-frame search is local to the previous positions.
   - Check that velocity uses absolute displacement/change and can be calibrated.

2. **Build a small validation set.**
   - Run the tracker on representative WT and mutant movies.
   - Save overlays for every frame showing point IDs, matched positions, and local search neighborhoods.
   - Manually inspect failures before changing parameters.

3. **Add focused tests and fixtures.**
   - Synthetic movie with known point displacement.
   - Synthetic movie with two nearby bright points to test duplicate/merge behavior.
   - Movie with a missing/flickering point to test track loss handling.
   - Calibration test converting pixels/frame to microns/sec or microns/min.

4. **Confirm raw data and calibration status.**
   - Ask for raw microscope files for all movie exports.
   - Ask for pixel size, Z-step, and true acquisition interval.
   - Ask whether `3_Mutant_515/03_676-6-3.mp4` and `04_676-6-3.mp4` are intentional duplicate replicate IDs.

5. **Write/refine the biological tracking-ROI crop script.**
   - Start with `.avi`, `.mp4`, and previewable `.tif` support.
   - Detect the upper/central actin tracking ROI from signal gradients.
   - Exclude the lower perinuclear/nucleus-adjacent region.

6. **Produce coordinate, track, and velocity outputs.**
   - Point coordinate CSV.
   - Track CSV.
   - Velocity summary CSV.
   - QC overlay image/video outputs.

7. **Continue validating and extending the R Shiny app.**
   - Test ROI selection and tracking on representative files from every group.
   - Add run acceptance/rejection and batch execution after single-run behavior is validated.
   - Keep the Python/OpenCV code behind the narrow Shiny bridge rather than exposing the PyQt prototype as the final deliverable.

8. **Keep AI models as optional future comparisons.**
   - DINOv3 can be investigated later as a possible general-purpose model.
   - Do not make DINOv3 or any learned model part of the active pipeline until the traditional CV baseline has been tested.

9. **Add reproducibility files.**
   - Create `requirements.txt` or `environment.yml`.
   - Add a small script or notebook for TIF inspection.
   - Document how to run preprocessing from a clean checkout.

## Current Mental Model

ActinTrackCV should not be built as a single monolithic "segment actin" script. It is better understood as a pipeline with four layers:

1. **Data ingestion and normalization**
   - raw videos, TIF stacks, montage images
   - metadata manifest
   - crop/channel handling

2. **Traditional CV tracking and validation**
   - bright-point or bright-region detection
   - local frame-to-frame matching
   - QC overlays for every track
   - synthetic and real-data tests

3. **Quantification**
   - bright-point coordinates
   - tracks
   - velocity over time
   - A/B comparisons
   - area and density
   - future 3D thickness and depth profiles

4. **User-facing exploration**
   - R Shiny app with Tab 1 for 2D tracking and Tab 2 for future 3D analysis

The most important engineering principle is to keep raw data immutable and keep every derived artifact traceable back to `raw_source`, `frames_index.csv`, and future metadata files. That traceability will matter once the lab moves from exploration to publishable quantitative claims.
