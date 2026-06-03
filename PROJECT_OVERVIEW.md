# ActinTrackCV Project Overview

## Executive Summary

ActinTrackCV is an early-stage research software project for quantifying F-actin organization, dynamics, and 3D structural features from confocal microscopy data. The project is currently in the data-understanding and preprocessing phase. The immediate work is not model training yet; it is building a clean foundation for image extraction, A/B region cropping, 2D filament coordinate tracking, velocity measurement, and an eventual R Shiny frontend.

The core scientific goal is to compare wild-type and mutant actin behavior. The local context and slide deck frame the biological questions around:

- F-actin cable folding differences.
- Actin velocity differences between A and B areas.
- Actin cable thickness.
- Whether a ring-like actin structure is moving.
- 3D actin structure from confocal Z-stacks.

The current data are a mixture of lossy `.avi`/`.mp4` exports and a small number of higher-value `.tif` stacks. Raw microscope files are still pending. Until those arrive, the practical plan is:

1. Establish the **2D velocity-tracking pipeline first** using the currently available `.avi`, `.mp4`, and usable 2D views/projections from `.tif` files.
2. Focus that 2D pipeline exclusively on regions/panels **A** and **B** from the `Picture1.jpg` layout. Region/panel C is the merged overlay and should be excluded from the primary tracking workflow.
3. Keep thickness, depth profiles, and other 3D metrics decoupled as a future module based on the `.tif` stacks.
4. Build the frontend shell for an R Shiny app with a multi-tab design: Tab 1 for 2D Tracking, Tab 2 for 3D Analysis as a future milestone.

The project should be thought of as two linked tracks:

- **Track A: 2D Tracking and Velocity** from `.avi`/`.mp4` frames plus usable 2D `.tif` slices/projections, focused on A/B regions, filament coordinates, and velocity over time. This is the main focus.
- **Track B: 3D Analysis** from 16-bit `.tif` Z-stacks, focused on filament thickness and depth profiles. This is a future milestone and should remain separate from the 2D tracking code path.

## Current Repository Layout

At the time of inspection, the repository contains these main components:

```text
.
├── README.md
├── extract_2d_frames.py
├── frames_index.csv
├── PROJECT_OVERVIEW.md
├── frames/
├── local_context/
├── raw_source/
├── .venv/
└── .gitignore
```

### Root-Level Files

`README.md` is a short project stub:

```text
#ActinTrackCV

AI-assisted computer vision for quantifying actin filament dynamics and 3D structural features from confocal microscopy images
```

`extract_2d_frames.py` is the current production preprocessing script for video exports. It:

- Reads `.avi` and `.mp4` files from `raw_source/`.
- Skips `.tif` stacks and derived `.jpg` montage files.
- Extracts 10 evenly sampled frames per movie.
- Saves lossless `.png` files under `frames/<batch_name>/`.
- Writes `frames_index.csv` as a manifest for Roboflow upload and downstream data tracking.

`frames_index.csv` currently contains 150 rows across 15 movie batches. Every source movie reports 15 frames, and the script extracted frame numbers:

```text
0, 2, 3, 5, 6, 8, 9, 11, 12, 14
```

`.gitignore` is configured to ignore local environments, model outputs, image/video/raw microscopy file types, and `local_context/`. Note that some ignored assets may already be tracked in git if they were committed before `.gitignore` was updated. Repository hygiene should be checked before any serious commit or publication-facing cleanup.

`.venv/` is a local Python virtual environment. It contains `opencv-python`, `numpy`, `pandas`, and `tqdm`, which are enough for `extract_2d_frames.py`. It does not currently contain `tifffile` or `Pillow`, even though system Python had those available during inspection. A future `requirements.txt` should make this reproducible.

### `local_context/`

`local_context/Claude Transcript ActinTrack.md` is the main project history and rationale. It documents the earlier decisions around Roboflow, annotation classes, frame extraction, dataset organization, and the current uncertainty around actin cable annotation.

`local_context/Picture1.jpg` is the key reference image for the A/B/C crop discussion. It shows three horizontal panels:

- **A:** cyan actin channel / F-actin signal.
- **B:** magenta channel / cell or nuclear-context signal.
- **C:** merged overlay of A and B.

The current crop requirement is to remove the C panel and retain only A and B.

`local_context/F-actin imaging.pptx` is a slide deck with sample and experimental context. Extracted slide text indicates:

- Samples include `WT_218`, `WT_550`, `Mutant_515`, and `Mutant_175`.
- WT constructs include `FWApro::Lifeact-Venus` and `FWApro::H2B-mRuby2/mRuby3`.
- Mutant labels include `scar2 on #218` and `xig on #218`.
- The deck says the time-lapse videos are `30 sec/frame, 15 frames`.
- It mentions "Top to middle around 4-6 slices."
- It lists the F-actin dynamic questions noted above.

This slide deck is important because the exported video metadata reports playback at 6 fps, but the slide deck likely describes the actual biological acquisition interval. For analysis, use acquisition metadata or confirmed lab notes, not video playback FPS.

### `raw_source/`

`raw_source/` contains the current source media. It should be treated as read-only input data.

```text
raw_source/
├── 1_WT_218/
├── 2_WT_550/
├── 3_Mutant_515/
└── 4_Mutant_175/
```

#### `1_WT_218/`

Files:

- `01.tif`
- `02.tif`
- `03.avi`
- `Montage of MAX_01.jpg`

Observed metadata:

| File | Type | Shape / dimensions | Notes |
|---|---:|---:|---|
| `01.tif` | TIFF | `(15, 2, 800, 412) uint16` | 15-plane, 2-channel stack. Channel 0 is actin. Channel 1 is nucleus. User visually confirmed the first axis is different depths, so this is a Z-stack rather than a time movie. |
| `02.tif` | TIFF | `(28, 360, 196) uint16` | Appears to be a single-channel stack or differently stored Z-stack. Needs visual inspection before use. |
| `03.avi` | AVI | 15 frames, 290 x 624, Motion JPEG | Exported video, likely actin-channel-only or actin-dominant. |
| `Montage of MAX_01.jpg` | JPEG | 1236 x 800 | Derived display montage with A/B/C panels. Not raw data. Useful for crop reference. |

`Montage of MAX_01.jpg` matches `Picture1.jpg` structurally: A, B, and C are side-by-side. Since it is exactly 1236 px wide, equal thirds are 412 px each. Keeping A and B means cropping `x = 0..824` and dropping the rightmost 412 px.

#### `2_WT_550/`

Files:

- `01.avi`
- `02.avi`
- `03.avi`
- `04.avi`
- `05.avi`

Observed video metadata:

| File | Frames | Export FPS | Dimensions |
|---|---:|---:|---:|
| `01.avi` | 15 | 6.0 | 302 x 604 |
| `02.avi` | 15 | 6.0 | 394 x 808 |
| `03.avi` | 15 | 6.0 | 310 x 624 |
| `04.avi` | 15 | 6.0 | 316 x 692 |
| `05.avi` | 15 | 6.0 | 338 x 752 |

These are lossy Motion JPEG exports. They are usable for prototype segmentation and annotation, but they should not be treated as fully calibrated raw microscopy data.

#### `3_Mutant_515/`

Files:

- `01_676-8-2.avi`
- `02_676-6-2.mp4`
- `03_676-6-3.mp4`
- `04_676-6-3.mp4`
- `05_676-8-3.mp4`

Observed video metadata:

| File | Frames | Export FPS | Dimensions |
|---|---:|---:|---:|
| `01_676-8-2.avi` | 15 | 6.0 | 444 x 704 |
| `02_676-6-2.mp4` | 15 | 6.0 | 326 x 741 |
| `03_676-6-3.mp4` | 15 | 6.0 | 308 x 663 |
| `04_676-6-3.mp4` | 15 | 6.0 | 320 x 718 |
| `05_676-8-3.mp4` | 15 | 6.0 | 335 x 676 |

The duplicate `676-6-3` suffix on files `03` and `04` should be clarified with the data provider. It may represent two acquisitions from the same biological replicate, or it may be a naming error.

#### `4_Mutant_175/`

Files:

- `01.avi`
- `02.avi`
- `03.avi`
- `04.avi`

Observed video metadata:

| File | Frames | Export FPS | Dimensions |
|---|---:|---:|---:|
| `01.avi` | 15 | 6.0 | 420 x 384 |
| `02.avi` | 15 | 6.0 | 260 x 472 |
| `03.avi` | 15 | 6.0 | 364 x 406 |
| `04.avi` | 15 | 6.0 | 312 x 436 |

### `frames/`

`frames/` contains extracted PNG frames from the current video exports. There are 15 batch folders and 150 PNG frames total.

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

`frames/inspect_tiff.py` is a scratch inspection helper that reads `1_WT_218/01.tif`, extracts the middle slice for channels 0 and 1, normalizes each to 8-bit, and saves `middle_ch0.png` / `middle_ch1.png`. As written, its relative path assumes it is run from a directory containing `1_WT_218/01.tif`; in this repository the correct path would usually be `raw_source/1_WT_218/01.tif`. Treat it as exploratory code, not production.

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
raw_source/*.avi, *.mp4, and usable 2D views from *.tif
    -> extract_2d_frames.py
    -> crop/prepare A and B regions only
    -> frames/<movie_batch>/*.png or equivalent A/B frame products
    -> frames_index.csv
    -> Roboflow instance-segmentation project
    -> manual annotations / future model training
    -> filament coordinate extraction
    -> frame-to-frame tracking
    -> velocity-over-time calculation
    -> R Shiny visualization
```

This is the main computational path. The first deliverable should be a working 2D tracking pipeline that can ingest the current video-derived frames and available `.tif`-derived 2D views, isolate the A/B regions, track filament coordinates, and calculate velocity over time.

The first model should probably focus on what the current video frames can support reliably:

- `entire_cell`
- `nucleus`, when visible or inferable
- Actin structural labels only after the lab decides how to handle dense meshwork

The current AVI/MP4 frames often show dense interconnected actin networks rather than cleanly separable cables. That makes a strict "one polygon per cable" rule difficult or impossible on some images. The immediate recommendation from the transcript was to pause cable annotation, keep cell/nucleus annotation moving, and ask the PI/lab which actin labeling strategy is biologically meaningful.

Possible actin annotation strategies:

1. **Split classes biologically:**
   - `f_actin_cable_discrete`
   - `f_actin_meshwork`
   - `f_actin_perinuclear`
2. **Keep one class but allow modes:**
   - discrete cable polygons where clear
   - dense meshwork polygon where individual cables are not resolvable
3. **Defer actin cable labels temporarily:**
   - train a baseline cell/nucleus model first
   - revisit actin labels once raw files or better imagery arrive

### Track B: 3D Analysis Workflow

The 3D workflow is a future milestone and should remain separate from the 2D tracking path:

```text
raw_source/*.tif
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

## Roboflow Context and Annotation State

The transcript documents several important Roboflow decisions:

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

Recommended near-term annotation policy:

- Do not randomly split frames across train/validation/test. Split by movie batch.
- Annotate only a small number of frames per movie at first, because frames within the same 15-frame sequence are correlated.
- Use `f0000` and `f0014` as a reasonable first pass if only two frames per movie are needed.
- Tag images where the nucleus is inferred from actin signal rather than directly visible: `no_nucleus_channel`.
- Tag images with unresolved actin meshwork: `dense_meshwork_visible`.
- Do not commit to per-cable labels until the lab decides whether the data actually resolves individual cables.

## A/B/C Crop Requirement

`Picture1.jpg` and `raw_source/1_WT_218/Montage of MAX_01.jpg` show the relevant A/B/C layout:

```text
[ A: cyan actin ][ B: magenta/context ][ C: merged overlay ]
```

The current requirement is to crop out C and keep only A and B.

For the initial 2D tracking milestone, A and B are the only regions/panels that should enter the tracking and velocity workflow. C is a merged visualization panel. It is useful for human inspection, but it should not be used as a computational input for coordinate tracking or velocity calculation unless the lab later defines a specific reason to use merged overlays.

For simple three-panel images with equal-width panels:

- Keep the left two-thirds of the image.
- Drop the right one-third.

Concrete examples:

- `raw_source/1_WT_218/Montage of MAX_01.jpg` is 1236 x 800. Each panel is 412 px wide. Keep `x = 0..824`.
- `local_context/Picture1.jpg` is 940 x 610. It is not evenly divisible by three, so an approximate crop is `x = 0..626` or `x = 0..627`. A production crop script should either use measured panel boundaries or detect the vertical separator, not blindly assume exact thirds in all cases.

Important caveat: not all source files are A/B/C panel images. The extracted AVI/MP4 frames in `frames/` are single-frame cell images, not three-panel montages. A crop script must not blindly remove the right third from every file. It should either:

- apply only to known A/B/C composite images, or
- support per-source crop metadata, or
- first detect whether a frame is a horizontal multi-panel layout.

For `.tif` files, the A/B concept may refer to channels or regions, not side-by-side panels. `01.tif` stores channels separately in a `(Z, C, Y, X)` array. Cropping a `.tif` by removing a rightmost display panel would be wrong unless the `.tif` itself is a rendered montage. For raw stacks, preserve the channel axis and operate on channel 0/1 directly.

## 2D Tracking and A/B Metrics Direction

The primary script direction is now a 2D tracking and velocity pipeline. Ratio-style A/B metrics can still be useful, but they are secondary to coordinate tracking and should be implemented only after the A/B input definition is clear. The phrase "A and B" is currently overloaded:

- In `Picture1.jpg`, A and B appear to be display panels or channels.
- In the PowerPoint, "Actin velocity differences between A and B areas" may mean biological areas or regions of the cell.

Before implementing ratio or A/B comparison metrics, define the target explicitly. Likely candidates:

1. **Panel/channel ratio:** compare intensity, area, or signal density between the A and B panels/channels.
2. **Region ratio:** compare actin intensity, cable density, velocity, or thickness between two manually defined cell regions A and B.
3. **Structure ratio:** compare actin cable signal to cell or nucleus signal.
4. **Motion ratio:** compare velocity or displacement metrics between two areas over time.

A robust first version of the 2D tracking script should:

- Accept an input image/video/stack path.
- Know whether the file is a raw stack, single frame, or A/B/C montage.
- If montage: crop to A and B and optionally save the A-only and B-only panels.
- If raw `.tif`: preserve 16-bit data and separate channel arrays.
- Extract filament coordinates in each usable timepoint/frame.
- Link coordinates over time into tracks.
- Calculate velocity over time using the confirmed acquisition interval, not video playback FPS.
- Write a CSV table of per-frame/per-track measurements.
- Save preview images so users can verify exactly what was measured.

Optional A/B comparison outputs can then be added:

- mean intensity in A and B
- total signal in A and B
- thresholded foreground area in A and B
- `A / B` ratio with safe handling for zero or near-zero B
- velocity differences between A and B regions, once the regions are defined

Future versions can add skeletonization, optical-flow-assisted tracking, and richer A/B comparison metrics once segmentation masks and acquisition timing are reliable. Cable thickness should remain part of the future 3D analysis module unless the lab defines a 2D proxy for it.

## R Shiny Frontend Direction

The current plan is to build only the frontend while waiting for raw files. The Shiny app should use a multi-tab design that keeps distinct computational tasks separated.

The interface should not present 2D velocity tracking and 3D thickness/depth analysis as one combined workflow. They use different data assumptions, different algorithms, and different validation requirements.

### Tab 1: 2D Tracking

This is the main tab and the primary development focus.

Purpose:

- Track filament coordinates over time.
- Calculate velocity over time.
- Restrict the current workflow to A and B regions/panels from the `Picture1.jpg` layout.
- Exclude C from computational tracking because it is a merged overlay.
- Support `.avi`, `.mp4`, and available `.tif`-derived 2D views/projections when appropriate.

Core controls:

- condition selector: WT / Mutant
- sample selector: 218 / 550 / 515 / 175
- movie/file selector
- frame/timepoint selector
- A/B crop mode selector
- tracking method selector, initially placeholder if the backend is not implemented
- acquisition interval input, defaulting to lab-confirmed metadata rather than video playback FPS

Core displays:

- original frame or montage
- A/B-only crop preview
- A panel / region view
- B panel / region view
- coordinate overlay
- track overlay
- velocity-over-time plot
- per-track results table

Expected outputs:

- cropped A/B images or frame products
- coordinate CSV
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
- annotation status
- warning that video export FPS is not acquisition timing
- reminder that Tab 1 is the active milestone and Tab 2 is future work

The Shiny frontend should start from `frames_index.csv` because it already provides a clean tabular bridge between files and metadata.

## Key Technical Risks

1. **Raw files are still pending.** The exported videos have lost microscopy metadata. Raw `.nd2`, `.czi`, `.lif`, or full `.tif` stacks are needed for calibration, channel identity, true time interval, pixel size, Z-step, and defensible quantitative claims.

2. **Video FPS is misleading.** OpenCV reads 6 fps from the exports, but the PowerPoint says 30 sec/frame. Use acquisition metadata for scientific timing.

3. **The current dataset has only 15 source movies.** Even though there are 150 extracted PNG frames, these are highly correlated within movie. Effective independent sample count is closer to the number of source movies/cells than the number of extracted frames.

4. **Actin cable annotation is unresolved.** Dense meshwork may not support one-polygon-per-cable annotation. The lab needs to decide whether to label discrete cables only, introduce meshwork/perinuclear classes, or defer cable segmentation until better raw data arrives.

5. **A/B/C crop logic must be conditional.** Some files are side-by-side montages, while others are raw stacks or single-panel frames. A blind crop would destroy valid data.

6. **TIF workflows must preserve bit depth.** Converting 16-bit TIF stacks to 8-bit PNG is fine for display and some annotation workflows, but quantitative analysis should preserve original 16-bit intensities.

7. **2D and 3D modules must stay decoupled.** The first milestone is 2D coordinate tracking and velocity. Thickness and depth-profile metrics are future 3D work and should not complicate the first tracking pipeline.

8. **Repository hygiene needs cleanup.** The repo contains local environment files, data, frames, and Mac `.DS_Store` files. `.gitignore` now excludes many of these categories, but tracked state should be checked before sharing or committing.

## Immediate Next Steps

1. **Confirm raw data status.**
   - Ask for raw microscope files for all movie exports.
   - Ask for pixel size, Z-step, and true acquisition interval.
   - Ask whether `3_Mutant_515/03_676-6-3.mp4` and `04_676-6-3.mp4` are intentional duplicate replicate IDs.

2. **Write a crop script for A/B/C composites.**
   - Start with montage JPEG support.
   - Keep A and B, drop C.
   - Add guardrails so single-panel frames are not cropped accidentally.

3. **Define and prototype the 2D tracking pipeline.**
   - Decide how filament coordinates will be detected in A and B.
   - Confirm the acquisition interval for velocity calculations.
   - Produce coordinate, track, and velocity CSV outputs.

4. **Create an R Shiny frontend scaffold.**
   - Use `frames_index.csv` as initial data source.
   - Build Tab 1 for 2D Tracking as the main interface.
   - Build Tab 2 for 3D Analysis as a future-milestone placeholder.
   - Keep backend computation minimal until the tracking method and A/B definitions are settled.

5. **Clarify annotation policy with the lab.**
   - Decide whether to annotate actin as discrete cables, meshwork, perinuclear structure, or defer actin labels.
   - Copy the annotation SOP into this repository if it should become part of the project record.

6. **Add reproducibility files.**
   - Create `requirements.txt` or `environment.yml`.
   - Add a small script or notebook for TIF inspection.
   - Document how to run preprocessing from a clean checkout.

## Current Mental Model

ActinTrackCV should not be built as a single monolithic "segment actin" script. It is better understood as a pipeline with four layers:

1. **Data ingestion and normalization**
   - raw videos, TIF stacks, montage images
   - metadata manifest
   - crop/channel handling

2. **Annotation and model training**
   - Roboflow for 2D masks
   - napari or 3D tooling for stacks
   - careful SOP-driven annotation

3. **Quantification**
   - filament coordinates
   - tracks
   - velocity over time
   - A/B comparisons
   - area and density
   - future 3D thickness and depth profiles

4. **User-facing exploration**
   - R Shiny app with Tab 1 for 2D tracking and Tab 2 for future 3D analysis

The most important engineering principle is to keep raw data immutable and keep every derived artifact traceable back to `raw_source`, `frames_index.csv`, and future metadata files. That traceability will matter once the lab moves from exploration to publishable quantitative claims.
