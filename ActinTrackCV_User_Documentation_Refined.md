# ActinTrackCV

## User Documentation

ActinTrackCV is a desktop application for organizing and analyzing 2D Arabidopsis F-actin fluorescence microscopy time-lapse data. The current workflow supports AVI and MP4 time-lapse data. It helps researchers select an actin-rich region of interest, preview the cropped region, run draft motion tracking, and compare results across biological groups.

This guide is written for biological researchers. It avoids software implementation details unless they help explain how to use the app safely.

Current workflow:

```text
Breed -> Add Sample / Select Data -> Orient and ROI -> Preview Cropped ROI -> Draft tracking/index -> Analysis
```

Current supported data type: 2D AVI/MP4 time-lapse data.

Image sequences, 3D image stacks, and raw microscopy formats are postponed and should not be treated as active import workflows.

---

## 1. Quick Start

Use this short path when starting a new analysis session.

1. Open ActinTrackCV and open or create a workspace.
2. Select a Breed in the left panel.
3. Choose Sample -> Add Sample, then select one AVI or MP4 data file.
4. Orient the image and draw a rectangular ROI around the actin-rich region.
5. Click Preview Cropped ROI to inspect the crop and run draft tracking.
6. Review the Tracking Result panel.
7. Open Analysis to compare Samples and Breeds.

Run command from the project folder:

```bash
python run_app.py
```

On macOS or Linux, `./run_app.sh` is also available. On Windows, use `run_app.bat`.

---

## 2. Core Concepts / Glossary

| Term | Meaning |
|------|---------|
| Breed | A biological or experimental group, such as `1_WT_218` or `3_Mutant_515`. In the current app these Breeds are selected from a fixed list. |
| Sample | One imported AVI/MP4 data file plus its project state: ROI, orientation, notes, tracking result, and analysis status. |
| Data | The AVI/MP4 file selected by the user for a Sample. The app stores a project-managed internal copy so the workspace can be reopened later. |
| ROI | Region of interest. A rectangle drawn around the actin-rich area to analyze. |
| Cropped ROI Preview | A looping preview of only the ROI area, with draft tracking overlay. |
| Tracking Result | Draft measurements from the current Sample's cropped ROI preview, including downward velocity and general movement. |
| Motion Index | A draft comparison metric based on tracked motion in the ROI. It should be interpreted alongside visual inspection. |
| Analysis | Read-only tables that summarize tracking/index results by Sample and Breed. |
| Workspace/project files | The folders and metadata files ActinTrackCV uses to remember Samples, ROIs, tracking results, and outputs. |

---

## 3. Recommended Workflow

The recommended workflow is Sample-driven. A Sample represents one AVI/MP4 data file and its derived project state.

```text
Select Breed
  -> Add Sample by choosing AVI/MP4 Data
  -> Orient frame
  -> Draw ROI
  -> Preview Cropped ROI
  -> Review Tracking Result
  -> Open Analysis
```

| Step | What you do | What the app stores or updates |
|------|-------------|--------------------------------|
| Select Breed | Choose the biological group in the left panel. | The Sample list filters to that Breed. |
| Add Sample | Select one AVI or MP4 file. | A Sample record, project-managed internal data copy, and metadata row. |
| Orient and ROI | Rotate/flip as needed and draw the rectangle around the intended actin-rich region. | ROI and orientation metadata. ROI changes autosave. |
| Preview Cropped ROI | Start the cropped ROI/tracking preview. | Draft tracking/index result for the current Sample. |
| Review Tracking Result | Compare the displayed values with visual motion in the preview. | No extra action is needed for the draft result to appear in Analysis. |
| Analysis | Open the Analysis tab/menu item. | Analysis reads saved results and aggregates by Breed and Sample. |

### Breed selection

The current app uses these fixed Breeds:

| Breed | Biological meaning |
|-------|--------------------|
| `1_WT_218` | Wild Type 218 |
| `2_WT_550` | Wild Type 550 |
| `3_Mutant_515` | Mutant 515 |
| `4_Mutant_175` | Mutant 175 |

### Adding a Sample

Use Sample -> Add Sample, or right-click the empty area in the Sample list and choose Add Sample. Select one AVI or MP4 data file. If the file cannot be read, no Sample is created.

### Replacing Data

Use Replace Data when a Sample should point to a different AVI/MP4 file. Replacing Data can clear ROI, tracking, processed outputs, and analysis state for that Sample because those results may no longer match the new file.

### Deleting a Sample

Deleting a Sample removes the Sample from the project, including ROI, tracking results, notes, and analysis data. The original data file on your computer is not deleted. If the app offers the checkbox "Also remove the project's internal data copy", that checkbox only refers to the project-managed copy inside the workspace.

---

## 4. App Interface Guide

| App area | What it is for | Notes |
|----------|----------------|-------|
| Breed/Sample list | Select the Breed and current Sample. | Right-click a Sample header or data row to rename, delete, or replace the Sample. |
| Add Sample flow | Choose one AVI/MP4 file to create a Sample. | Canceling the file picker creates nothing. |
| Orientation/ROI preview | View the full frame, rotate/flip if needed, and draw the ROI. | ROI autosaves; there is no Save ROI button. |
| Cropped ROI preview | Loop the cropped ROI and inspect draft tracking overlay. | Includes Play/Pause, frame slider, speed control, and Return to Full Preview. |
| Advanced Tracking Settings | Adjust draft tracking parameters. | Editable only during cropped ROI preview. |
| Tracking Result | Shows the current Sample's draft tracking/index result. | If settings changed, rerun Preview Cropped ROI to update. |
| Analysis | Read-only tables grouped by Breed and Sample. | Opening Analysis does not rerun tracking. |
| Purge/Cleanup | Advanced project cleanup tools. | Use carefully. These actions are for maintenance and troubleshooting. |
| Export ROI | Exports cropped ROI outputs to the `processed/` folder. | Useful when sharing processed data or keeping output files, but not required just to view draft Analysis. |

---

## 5. Workspace and File Structure Guide

An ActinTrackCV workspace is a project folder managed by the app. The app creates and updates the folders below.

```text
<workspace>/
  raw/
    <Breed>/
      <SampleName>/
        <sample_id>.avi or <sample_id>.mp4
  processed/
    <Breed>/
      <SampleName>/
        exported crops and motion-index outputs, if exported
  previews/
    <Breed>/
      optional preview files
  metadata/
    data_files.csv
    sample_registry.json
    crop_metadata.json
    draft_tracking/
      <sample_id>.json
    f_actin_motion_index_summary.csv
    workspace.json
    recent_workspaces.json
```

| File or folder | Purpose | User should edit manually? | Safe to delete manually? | Notes |
|----------------|---------|----------------------------|--------------------------|-------|
| `raw/` | Project-managed internal copies of imported AVI/MP4 data. | No. | Usually no. Use the app's delete options instead. | These copies let the project reopen even if the original file moves. |
| `processed/` | Exported cropped ROI videos/images and finalized output files. | No, unless you are intentionally copying results out. | Only if you understand they are generated outputs and no longer need them. | Deleting manually can make Analysis or previews appear incomplete. |
| `previews/` | Optional generated preview files. | No. | Usually safe if you only want to remove cached previews, but app cleanup tools are preferred. | The app may regenerate some previews. |
| `metadata/data_files.csv` | Main data index for Samples. | No. | No. | App-managed record of Sample data paths and statuses. |
| `metadata/sample_registry.json` | Sample registry grouped by Breed. | No. | No. | App-managed list of Samples. |
| `metadata/crop_metadata.json` | ROI and orientation metadata. | No. | No. | Deleting this removes ROI/orientation state. |
| `metadata/draft_tracking/` | Draft tracking/index JSON files for Samples. | No. | Only through app cleanup or if intentionally clearing draft results. | Analysis can read these results. |
| `metadata/f_actin_motion_index_summary.csv` | Workspace-level summary of finalized motion-index outputs, when present. | No. | Only if you understand it is generated summary data. | Draft Analysis can also read per-Sample draft tracking JSON. |
| `metadata/workspace.json` | Workspace schema/version information. | No. | No. | Needed for current workspace compatibility. |
| `metadata/recent_workspaces.json` | Recent workspace list. | No. | Low risk, but not necessary. | Cosmetic/user preference data. |
| `raw_source/` | Optional source tree outside the normal app workflow. | Only as normal file organization. | Depends on your lab data policy. | Treat original source data as read-only. |

Safety rule: if a file is inside `metadata/`, let the app manage it. If you need to clean a workspace, prefer Workspace -> Purge / Cleanup rather than manually deleting files.

---

## 6. Data Import and Sample Management

### Supported input

ActinTrackCV currently supports AVI and MP4 data files in the active 2D workflow.

| Data type | Current support |
|-----------|-----------------|
| `.avi` | Supported |
| `.mp4` | Supported |
| Image sequence | Postponed |
| TIFF stack | Postponed for active import |
| `.oib`, `.oif`, `.oir` raw microscopy files | Postponed |
| 3D microscopy formats | Postponed |

### Sample meaning

A Sample is one imported AVI/MP4 data file plus its project state. The project state can include:

- data path/reference
- ROI/orientation metadata
- cropped ROI preview state
- tracking/index results
- analysis metrics
- notes/status

### Rename, delete, and replace

Right-click the Sample header or the indented data row to access:

- Rename Sample
- Delete Sample
- Replace Data

Replace Data should be used carefully. It can invalidate previous ROI and tracking/index results because those results were measured from the previous data file.

Delete Sample removes project state and derived results. It does not delete the original external file on your computer. If the project has an internal copy, the app may ask whether to remove that internal project copy.

---

## 7. ROI and Orientation

The ROI is the rectangular region that the app uses for tracking/index measurement. For this project, the ROI should enclose the intended actin-rich region near the egg apparatus / nucleus-adjacent region, while excluding irrelevant areas when possible.

### Why orientation matters

Orientation affects how the frame is displayed and how the ROI is applied. Rotate or flip the full preview until the region is visually consistent with the analysis goal. Downward motion is interpreted internally as increasing y-coordinate in the image; this direction is fixed and is not shown as a GUI control.

### ROI autosave

ROI changes autosave. There is no Save ROI button. When you draw, move, or resize the ROI, the app stores the current ROI and orientation in project metadata.

### How to verify the ROI

Before running Preview Cropped ROI:

- Confirm the data loaded correctly.
- Confirm the ROI encloses the intended actin-rich region.
- Avoid including too much background or unrelated structures.
- Avoid making the ROI so small that tracking points cannot move.
- Use the full preview to check orientation before relying on the crop.

The Suggest ROI from F-actin Signal button is a helper. It can suggest a region with strong F-actin signal, but the researcher should visually verify the result.

---

## 8. Cropped ROI Preview

Preview Cropped ROI switches from full-frame view into cropped ROI/tracking preview mode.

In this mode, the app:

- loads the current AVI/MP4 data
- applies the current orientation
- crops every frame to the ROI
- runs draft tracking/index analysis
- shows the cropped ROI preview
- saves a draft tracking result for the current Sample

### Controls

| Control | Purpose |
|---------|---------|
| Play | Start looping the cropped ROI preview. |
| Pause | Pause playback. |
| Frame slider | Manually scrub through cropped ROI frames. |
| Speed | Change playback speed. Supported options include 0.25x, 0.5x, 1x, 1.5x, and 2x. |
| Return to Full Preview | Exit cropped preview mode and return to the full Sample preview. |

Changing speed takes effect immediately when playback is active. Manual scrubbing remains available.

### Advanced Tracking Settings

Advanced Tracking Settings appear in the right panel only during cropped ROI preview. They are not editable outside cropped ROI preview. If you change settings while previewing, rerun Preview Cropped ROI to update the result when prompted.

---

## 9. Tracking / Motion Index

The tracking/index result is intended as an ROI-level and Sample-level motion estimate. It is not a claim that every individual filament has been tracked perfectly.

The current draft method uses bright-point/template tracking:

1. It selects bright F-actin signal points in the first cropped ROI frame.
2. It follows those local image patches across frames.
3. It calculates movement values from valid tracked steps.
4. It summarizes the result for the Sample.

### How to interpret the values

| Output | General meaning |
|--------|-----------------|
| Downward Velocity | Average positive movement in the internal downward direction, measured in microns per second. |
| General Movement | Average overall displacement speed, regardless of direction. |
| Motion Index | Current comparison metric; in the active Analysis code it is based on downward velocity. |
| Valid Tracks | Number of starting points that produced usable tracking steps. |
| Valid Steps | Total number of frame-to-frame movement steps used in the result. |
| Confidence | Template matching confidence threshold used by the tracking settings. |

Use these results as draft comparison metrics. They may not always match visual intuition, especially when contrast is low, cables overlap, the sample drifts, or structures move out of plane.

### Default tracking settings

| Setting | Default |
|---------|---------|
| Starting points | 5 |
| Minimum point spacing | 40 px |
| Search radius | 15 px |
| Patch size | 11 px |
| Minimum match confidence | 0.70 |
| Lookahead frames | 3 |
| Microns per pixel | 0.2650 |
| Seconds per frame | 0.2000 |
| Downward direction | `increasing_y` internally |

The `seconds per frame` value is especially important for velocity units. Confirm it against acquisition metadata or lab notes when possible.

---

## 10. Analysis Section

Analysis is read-only. It does not rerun tracking. It reads saved results and summarizes them by Breed and Sample.

The Analysis view includes:

| Table | What it shows |
|-------|---------------|
| Breed Summary | Number of Samples, Samples with results, average movement metrics, and standard deviations. |
| Sample Details | Per-Sample status, tracking/index metrics, valid tracks, valid steps, confidence, and update time. |
| Breed Comparison | Breed-level ranking/comparison using available Sample results. |

Example organization:

| Breed | Sample | Result status | Downward Velocity | General Movement |
|-------|--------|---------------|-------------------|------------------|
| `1_WT_218` | Sample 1 | Result available | numeric value | numeric value |
| `1_WT_218` | Sample 2 | Missing result | - | - |
| `3_Mutant_515` | Sample 1 | Result available | numeric value | numeric value |
| `3_Mutant_515` | Sample 2 | Result available | numeric value | numeric value |

Missing results should be treated as missing data, not as zero movement. Analysis helps compare trends, but it should not be interpreted as final biological proof by itself.

---

## 11. Suggested Quality Control Practices

Use visual inspection and metadata checks together.

- Confirm that the AVI/MP4 data loads correctly.
- Confirm the ROI encloses the intended actin-rich region.
- Confirm the cropped ROI preview visually matches the intended ROI.
- Watch the looping preview and compare it to the Tracking Result values.
- Check whether tracked movement aligns with visible F-actin movement.
- Watch for low contrast, photobleaching, sample drift, out-of-plane movement, tangled cables, and overlapping filaments.
- Compare multiple Samples per Breed.
- Avoid drawing conclusions from one Sample alone.
- Confirm time calibration before interpreting values as biological velocities.

---

## 12. Troubleshooting

| Problem | Likely cause | Suggested fix |
|---------|--------------|---------------|
| Data will not load | File is not AVI/MP4, the file is unreadable, or the path is missing. | Re-export as AVI/MP4 or choose a readable file. Confirm it opens outside the app. |
| Add Sample creates nothing | The file picker was canceled or validation failed. | Select one valid AVI/MP4 file. |
| ROI appears wrong | Orientation changed, ROI was drawn on the wrong area, or the crop is too large/small. | Return to full preview, adjust orientation, redraw ROI, and visually verify. |
| Cropped preview is blank | ROI may be outside the visible signal, too small, or on a low-signal region. | Redraw ROI around visible F-actin signal. |
| Tracking result looks unrealistic | Low contrast, overlapping filaments, sample drift, or unsuitable tracking settings. | Visually inspect the preview, adjust tracking settings, and rerun Preview Cropped ROI. |
| Analysis shows missing result | Preview Cropped ROI has not been run for that Sample, or the result was cleared. | Select the Sample and run Preview Cropped ROI. |
| Sample was replaced and old analysis disappeared | Replace Data cleared derived state because the old results no longer matched the new file. | Redraw/verify ROI and rerun Preview Cropped ROI. |
| Playback speed seems wrong | Speed selection may not match expectations or playback was paused. | Select the desired speed during cropped preview and press Play if paused. |
| Return to Full Preview does not show the expected frame | The app returned to full preview using the current Sample state. | Select the Sample again or adjust the full-frame slider. |

---

## 13. Limitations and Future Work

Current limitations:

- Active import supports AVI/MP4 only.
- Current analysis is 2D only.
- Image sequence import is postponed.
- 3D/raw microscopy formats are postponed.
- TIFF stacks and raw microscope formats should not be documented as active workflows.
- The current motion index is a draft/comparison metric.
- Metrics should be interpreted with visual inspection and experimental context.

Possible future work:

- Image-sequence workflow.
- 3D/raw microscopy support.
- Additional or alternative motion metrics, such as optical flow, if implemented later.
- More explicit calibration support for acquisition timing and microns-per-pixel.

---

## 14. Appendix

### Supported data types

| Type | Status |
|------|--------|
| AVI | Active |
| MP4 | Active |
| PNG/JPG image sequence | Postponed |
| TIFF image/stack | Postponed for active app import |
| OIB/OIF/OIR raw microscopy | Postponed |

### Legacy terminology note

Older project files and older documentation may use earlier names. The current user-facing terms are:

| Legacy term | Current term |
|-------------|--------------|
| condition group | Breed |
| biological batch / batch | Sample |
| video / import video | Data / Add Sample |
| samples.csv | `data_files.csv` in schema v2, with compatibility for older workspaces |
| batches.json | `sample_registry.json` in schema v2, with compatibility for older workspaces |

You may still see legacy names in internal filenames or code paths. That does not change the current app workflow.

### Minimal installation reminder

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run_app.py
```

On Windows, activate the environment with `.venv\Scripts\activate` and use `run_app.bat` if preferred.

### What to avoid

- Do not manually edit `metadata/` files unless you are doing advanced troubleshooting.
- Do not treat missing Analysis values as zero.
- Do not interpret a single Sample as proof of a Breed-level biological effect.
- Do not treat image sequences or 3D/raw microscopy files as active import types in the current workflow.

---

## 15. Short Safety Summary

ActinTrackCV is designed to preserve the user's original data files. Adding a Sample creates project records and a project-managed copy. Replacing Data or deleting a Sample may clear project state and derived results, but the original external AVI/MP4 file should remain untouched unless the app explicitly asks about a project internal copy and the user confirms that deletion.
