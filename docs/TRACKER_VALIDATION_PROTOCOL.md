# ActinTrackCV numerical validation protocol

## Scope

This protocol validates whether tracked coordinates and reported 2D motion metrics are numerically accurate. It does not establish that a bright landmark always represents the same biological F-actin structure.

The validation design follows the use of simulated microscopy data with exact ground truth in the [Particle Tracking Challenge](https://www.nature.com/articles/nmeth.2808) and the synthetic-then-biological validation used for [fluorescent speckle actin tracking](https://pmc.ncbi.nlm.nih.gov/articles/PMC1303246/). QFSM/STICS provides the preferred biological comparison method for F-actin flow ([QFSM protocol](https://pmc.ncbi.nlm.nih.gov/articles/PMC3688286/)).

## Metric definitions

- `absolute_velocity_index_um_per_s`: historical step-weighted mean Euclidean speed.
- `downward_velocity_index_um_per_s`: historical conditional mean `mean(dy/dt | dy > 0)`. It excludes stationary and upward steps.
- `time_weighted_mean_speed_um_per_s`: total tracked path length divided by total tracked time. Use this as the primary scalar speed when lookahead creates unequal frame gaps.
- `signed_vertical_velocity_um_per_s`: total signed y displacement divided by total tracked time. Positive image y is downward.
- `downward_velocity_contribution_um_per_s`: total positive y displacement divided by total tracked time. Upward and stationary observation time remains in the denominator.

All physical-unit values scale linearly with `microns_per_pixel / seconds_per_frame`. Those inputs must therefore come from acquisition metadata or an independent calibration—not encoded video playback FPS.

## Layer 1: automated synthetic ground truth

Run:

```bash
.venv/bin/python scripts/validate_tracker.py
```

Validate the optional template tracker separately with:

```bash
.venv/bin/python scripts/validate_tracker.py --tracking-method template
```

The benchmark writes JSON and CSV reports under `outputs/tracker_validation/`. It covers clean integer motion, subpixel motion, Poisson/read noise, photobleaching, upward motion, and a denser field.

The initial engineering gates are:

- position RMSE no greater than 0.75 px;
- scalar-speed relative error no greater than 10%;
- signed/downward component error no greater than 0.15 px/frame;
- ground-truth point recall at least 95%.

These are software gates, not universal biological acceptance limits. Before comparing genotypes, convert the tolerances to µm/s and confirm that they are materially smaller than the minimum biological effect the study needs to detect.

### Optical flow (Layer 1)

Run:

```bash
.venv/bin/python scripts/validate_optical_flow.py
```

The benchmark writes JSON and CSV reports under `outputs/optical_flow_validation/`. It uses affine-warped bright-band frames with known uniform `dx`/`dy` px/frame and compares dense Farnebäck flow magnitudes to that ground truth.

Initial engineering gates:

- scalar-speed relative error no greater than 15%;
- signed vertical and downward-component error no greater than 0.25 px/frame;
- at least 2% of ROI pixels must pass the brightness mask.

### Continuous integration

On every push and pull request to `main`, GitHub Actions runs the Layer 1 gates plus unit tests and the Shiny workflow check (see `.github/workflows/validation.yml`). Locally, run the same sequence with:

```bash
./scripts/run_validation_gates.sh
```

## Layer 2: calibrated microscope translation

Required material: a stable fluorescent bead slide or fixed fluorescent specimen and a calibrated motorized/piezo stage.

1. Confirm pixel size independently using a stage micrometer or microscope calibration record.
2. Record at least five commanded translations in each of +x, -x, +y, and -y, spanning subpixel to near-search-radius displacement.
3. Include a zero-motion recording to measure false motion and drift.
4. Use the same objective, camera settings, acquisition interval, export format, ROI workflow, and orientation operations used for biological data.
5. Run ActinTrackCV without tuning parameters separately for each direction.
6. Compare measured and commanded displacement and velocity using signed bias, MAE, RMSE, and 95% limits of agreement. Correlation alone is not evidence of agreement.
7. Repeat on at least three acquisition sessions to expose setup-dependent calibration or drift.

Do not pass this layer unless its limits of agreement fit inside the lab-approved biological error tolerance.

### Running Layer 2 analysis

1. Record bead-slide movies with the stage (include zero-motion control and ≥5 translations per axis as above).
2. Copy `examples/layer2_stage_calibration.manifest.example.json` and set `source_path`, commanded µm/frame, and **independently measured** `independent_microns_per_pixel`.
3. Run analysis and agreement statistics:

```bash
.venv/bin/python scripts/validate_stage_calibration.py \
  --manifest path/to/your_manifest.json \
  --output-dir outputs/stage_calibration_validation
```

Reports are written as `stage_calibration_report.json` and `stage_calibration_recordings.csv` under the output directory. Review signed bias, MAE, RMSE, and 95% limits of agreement for X and Y.

### Synthetic Layer 2 gate (CI / smoke test)

```bash
.venv/bin/python scripts/validate_stage_calibration.py --synthetic
```

This uses affine synthetic bead movies with known commanded translation. It does **not** replace real microscope bead-slide validation.

## Layer 3: real F-actin agreement

1. Preselect representative movies before viewing tracker results. Include low/high signal, sparse/dense landmarks, bleaching, and expected slow/fast motion.
2. Analyze identical ROIs with ActinTrackCV and QFSM/STICS where feasible. For a smaller blinded subset, obtain independent expert kymograph or manual landmark measurements.
3. Freeze calibration and tracker parameters before comparison.
4. Report paired bias, MAE, RMSE, Bland–Altman limits of agreement, track survival, and exclusions. Stratify errors by signal quality and feature density.
5. Investigate incorrect-link and identity-switch failures separately from localization error.

Only after all three layers pass should exported values be described as quantitatively validated for the tested acquisition conditions.
