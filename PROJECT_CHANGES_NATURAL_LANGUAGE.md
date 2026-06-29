# ActinTrackCV Natural-Language Change Record

Last updated: 2026-06-22

This document explains the main project changes in plain language. It is meant
to help a lab member, PI, or future developer understand why the project changed
direction and what should happen next.

## Biological Material

ActinTrackCV analyzes **Arabidopsis** reproductive cells — elongated ovule /
embryo-sac cells expressing **Lifeact** (F-actin) and **H2B** (nucleus)
reporters. The current dataset is **not** whole-seed imaging. WT lines **218**
and **550** use `FWApro` drivers; mutants **515** and **175** are `scar2` and
`xig` on the #218 background. See `local_context/F-actin imaging.pptx` and
`PROJECT_OVERVIEW.md` for construct and acquisition details.

## Current Direction

ActinTrackCV is no longer Roboflow-first and no longer AI-training-first.

The current direction is to refine and test a traditional computer-vision
tracking method recommended by Dr. Ju:

1. In the first usable frame, find the 10 brightest actin points or small bright
   grouped regions.
2. In the next frame, search near those previous points for the corresponding
   brightest nearby points.
3. Repeat this frame by frame to build short tracks.
4. Convert the absolute frame-to-frame movement into calibrated velocity using
   pixel size and the true acquisition interval.

The reason for this direction is practical: a simple traditional CV method is
easier to explain, easier to validate, and easier for others to trust than a
large AI model. AI can still be explored later, but it is not the first
deliverable.

## What Changed From the Earlier Roboflow Plan

The earlier plan was to annotate microscopy frames in Roboflow and train an
instance-segmentation model. That path is now historical context only.

The Roboflow work taught us something important: the actin signal often appears
as dense interconnected meshwork rather than clean individual cables. That made
one-polygon-per-cable annotation difficult and biologically ambiguous. Because
of that, the project moved away from manual annotation and toward tracking
bright actin landmarks directly.

Roboflow decisions, class names, and annotation SOP notes should stay in the
project history, but they should not drive the active implementation.

## Current Python App Status

The current Python/PyQt app is a research prototype and development workbench.
It is useful for:

- importing AVI/MP4 time-lapse files;
- organizing data by breed and sample;
- drawing or reviewing a rectangular ROI;
- previewing cropped ROI frames;
- running a draft brightest-nearby-point motion index, with template matching
  retained as an optional comparison method;
- generating quick tracking overlays and summary metrics.

The Python app should not be treated as the final user-facing application.
It should be used to test algorithms quickly and define the outputs that the
final app needs.

## Final App Direction: R Shiny

The final user-facing app should be built in R Shiny, not Python. A new app has
now been started from scratch under `shiny_app/`.

The likely division of responsibilities is:

- Python/OpenCV code: algorithm prototyping, image preprocessing, tracking,
  QC output generation, and CSV/JSON result export.
- R Shiny app: final interactive user interface, data review, plots, tables,
  comparisons between WT and mutant samples, and presentation-ready summaries.

The R Shiny app should consume stable outputs from the analysis pipeline:

- point coordinate CSV files;
- track CSV files;
- velocity summary CSV files;
- QC overlay images or videos;
- metadata describing pixel size, seconds per frame, sample group, and source
  file provenance.

This keeps the final app understandable: Shiny presents the results, while the
underlying tracking method remains a clear and testable analysis step.

The R Shiny application now:

- discovers AVI and MP4 files directly under the active project's `raw/` and
  `processed/` folders, even when the older metadata registry is empty;
- reads real video metadata and displays a selected microscopy frame;
- supports frame rotation and horizontal mirroring;
- lets the user draw an ROI directly over the preview or enter pixel bounds;
- exposes the bright-point tracker and calibration parameters;
- runs the Python/OpenCV tracker through a narrow JSON command-line bridge;
- stores lossless cropped frames and complete run outputs under
  `processed/shiny_runs/`;
- summarizes absolute and downward velocity, track counts, and valid steps;
- plots trajectory paths and per-frame absolute velocity for every track;
- displays starting-point images, track overlays, and QC preview videos;
- downloads trajectory CSV and summary JSON outputs;
- summarizes completed runs by biological group;
- inventories local `.oir`, `.oib`, `.tif`, and `.tiff` files;
- keeps z-stack processing clearly marked as incomplete rather than implying
  that raw Olympus files are already analyzed;
- uses a responsive scientific-workspace design with collapsible mobile
  navigation rather than the earlier default Shiny layout.

The R interface owns the user experience and reporting. Python remains a small,
testable image-analysis backend instead of being the final application UI.

## New Z-Stack Files

New Olympus `.oir` z-stack files were added under:

```text
20260608_WT_Z stacks/
```

Copies were also registered under the WT218 raw data area as raw microscopy
inputs. These files are important, but they are not part of the immediate 2D
velocity-tracking workflow.

What needs to happen for z-stacks:

- inventory each `.oir` file;
- extract metadata such as dimensions, channel count, pixel size, z-step, and
  bit depth;
- convert to a more analysis-friendly format such as OME-TIFF if needed;
- generate QC previews such as max projections and middle z-slices;
- keep 3D depth/thickness metrics separate from 2D velocity tracking.

The app should not pretend that `.oir` support is complete until this inspection
and conversion workflow exists.

## Tracking Method Changes Implemented

The Python workbench tracker was updated to align more tightly with Dr. Ju's
instructions.

Implemented changes:

- the default number of starting points is now 10 instead of 5;
- the default interval is now 30 seconds per frame, while remaining editable;
- `brightest_local` is now the default tracking method;
- template matching remains available as an optional method for comparison;
- bright multi-pixel regions are represented by a weighted centroid rather
  than an arbitrary edge pixel;
- point assignments are one-to-one within each target frame so two tracks
  cannot claim the same nearby bright point;
- absolute Euclidean movement is the primary velocity metric;
- downward-only velocity remains available as a secondary directional metric;
- trajectory CSV files now include frame gap, dx, dy, displacement, elapsed
  time, micron conversion, absolute velocity, and downward velocity per step;
- summary CSV/JSON outputs now contain an explicit absolute-velocity field and
  identify it as the primary metric;
- the PyQt draft-tracking settings now include a tracking-method selector;
- synthetic tests cover known movement, calibrated velocity, non-collapsing
  assignments, default parameters, and trajectory CSV columns.

Still needed:

- QC overlays that visualize each search window and rejected candidates;
- testing on representative real videos and documenting failure cases;
- confirmation of calibration values from raw acquisition metadata.

## Calibration Requirements

Velocity is only meaningful when calibrated.

The project needs these values for each dataset:

- microns per pixel;
- seconds per frame;
- whether the video playback FPS is only an export setting;
- whether the raw microscope files contain better timing metadata.

The current exported videos report playback metadata that may not represent the
actual biological acquisition interval. Lab notes say 30 seconds per frame, so
that value should be used only after confirmation or raw metadata verification.

## Data Management Notes

Raw microscopy data should stay immutable. Derived outputs should be traceable
back to the original source files.

Important data rules:

- do not edit raw `.avi`, `.mp4`, `.tif`, or `.oir` files in place;
- keep raw z-stack files separate from app workspace metadata;
- avoid opening a raw data folder itself as an app workspace;
- keep generated tracking outputs in processed/metadata output folders;
- record parameter settings used for every tracking run.

There is currently a nested metadata folder inside `20260608_WT_Z stacks/`,
which appears to have been created by opening that raw data folder as a
workspace. It has not been deleted, but scoped `.gitignore` rules now keep that
runtime metadata out of source control.

## AI Models and DINOv3

DINOv3 was mentioned as a possible all-around model from MetaAI. It may be worth
investigating later, especially as a comparison or future feature extractor.

For now, DINOv3 and other AI models should remain optional future work. They
should not replace the traditional CV baseline until the bright-point tracking
method has been tested and its limitations are understood.

## Practical Next Steps

1. Confirm 30 seconds per frame and 0.265 microns per pixel from microscope
   metadata or acquisition notes.
2. Run the updated tracker on several representative WT videos and inspect the
   trajectory overlays manually.
3. Tune search radius, spacing, and brightness threshold from those results.
4. Add search-window and rejected-candidate QC overlays.
5. Extract `.oir` metadata and create safe max-projection/middle-slice previews.
6. Connect Shiny to real generated tracking summaries and add comparison plots.
7. Decide whether tracking execution remains an external pipeline step or is
   launched from Shiny through a controlled backend process.

## One-Sentence Project Summary

ActinTrackCV is now an explainable traditional computer-vision workflow for
tracking bright actin landmarks and calculating calibrated velocity, with an R
Shiny scaffold started as the final user-facing interface.
