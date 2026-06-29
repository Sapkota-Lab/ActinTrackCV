# ActinTrackCV Shiny App

This folder contains the R Shiny user interface for the ActinTrackCV traditional computer-vision workflow on **Arabidopsis reproductive-cell** F-actin time-lapse data.

R owns the interface, plots, tables, project navigation, and result review. The tested Python/OpenCV modules remain the analysis backend and are called through `scripts/shiny_bridge.py` for video probing, frame extraction, ROI cropping, and tracking.

## Workflow

The sidebar follows a task-oriented flow:

1. **Project** — open a workspace folder, choose one video from that workspace only, and confirm the live preview in Source studio.
2. **Track** — set ROI on the active video and run the Python tracker.
3. **Review** — pick one completed run, then use **Overview**, **Motion**, and **Angles** sub-tabs for QC and plots.
4. **Compare** — aggregate velocity metrics across biological groups.
5. **Z-stacks** — reference inventory for microscopy files (not part of the 2D pipeline).

Workspace paths are applied explicitly with **Open workspace** so file lists always match the folder you intended. The sidebar shows the current workspace and active video at a glance.

Old deep links such as `?section=results` or `?section=angles` still open **Review**.

## Run

From the project root:

```r
shiny::runApp("shiny_app")
```

The local application is normally available at the URL printed by Shiny.

## R Packages

```r
install.packages(c(
  "shiny",
  "bslib",
  "ggplot2",
  "jsonlite",
  "png",
  "base64enc",
  "htmltools",
  "fontawesome"
))
```

The Python virtual environment must contain the packages from the main project requirements, including OpenCV and NumPy.

## Current Functionality

- Automatically discovers AVI and MP4 files under `raw/` and `processed/`.
- Displays video dimensions, frame count, playback FPS, and file provenance.
- Extracts and displays real preview frames from the selected source.
- Supports 0/90/180/270-degree rotation and horizontal mirroring.
- Defines the tracking ROI by brushing directly over the preview or entering pixel bounds.
- Configures starting points, spacing, search radius, confidence, calibration, and matching method.
- Runs brightest-nearby-point or template tracking from Shiny through the Python bridge.
- Stores lossless cropped frames and tracking outputs under `processed/shiny_runs/`.
- Displays absolute velocity, downward velocity, track counts, and valid-step counts.
- **Review** step combines QC imagery, motion plots, and full-sequence angle dynamics in one place with sub-tabs.
- Angle review includes instantaneous motion angle, wrapped turning angle, tracked X/Y position over time,
  directional stability, reversal counts, tracking video and trajectory-overlay previews, and a downloadable per-step CSV.
- Tracking previews use VP9/VP8 WebM with explicit browser MIME metadata, with
  H.264 MP4 as a secondary source for new runs. Legacy `mp4v` previews are
  converted to WebM on demand; the static trajectory overlay remains available
  if video encoding is unavailable.
- Plots trajectories and per-frame absolute velocity by track.
- Displays starting-point and track-overlay QC images.
- Streams the generated tracking-preview MP4.
- Downloads trajectory CSV and summary JSON files.
- Aggregates completed runs by biological group.
- Inventories OIR, OIB, TIF, and TIFF z-stack files.
- Uses a responsive task-oriented workflow with numbered sidebar steps and collapsible mobile navigation.

## Output Layout

```text
processed/shiny_runs/
  <group>/
    <source_name>/
      <timestamp>/
        cropped_frames/
        *_point_tracks.csv
        *_motion_index.json
        *_starting_points.png
        *_track_overlay.png
        *_track_preview.mp4
        shiny_run_manifest.json
```

## Not Implemented Yet

- Direct OIR metadata extraction, projection, or 3D quantification.
- Automatic biological ROI detection inside Shiny.
- Batch execution across multiple selected videos.
- Manual acceptance/rejection status for individual tracks.
- Publication-ready report export.
