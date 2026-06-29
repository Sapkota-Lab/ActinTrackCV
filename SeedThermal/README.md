# SeedThermal

**SeedThermal** is a standalone Python project for exploratory **seed thermal phenotyping** using radiometric exports from a **FLIR ONE Edge** camera. It lives alongside [ActinTrackCV](../README.md) in this repository but is **not** part of the Arabidopsis F-actin microscopy / motion-index workflow.

## What it does

- Loads **radiometric JPG** files downloaded from [FLIR Ignite](https://ignite.flir.com) (not chat/Photos exports)
- Extracts per-pixel °C arrays with [`flyr`](https://pypi.org/project/flyr/)
- Computes per-ROI temperature statistics over time
- Writes clean optical and false-color preview images (no FLIR watermark in analysis outputs)
- Outputs `plate_temperature_timeseries.csv` + `thermal_run_manifest.json`

**MP4 video from the FLIR app is preview-only** — do not use it for quantitative temperature work.

## Install

```bash
cd SeedThermal
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Validate one file

```bash
python scripts/validate_flir.py /path/to/IMG_2628.JPG
```

## Batch process a folder

Put **only** Ignite radiometric JPGs in a folder, then:

```bash
python scripts/run_thermal_phenotype.py \
  --input /path/to/ignite_jpgs \
  --plate-id seed_plate_01
```

Optional ROI config (thermal array coordinates, height × width):

```bash
python scripts/run_thermal_phenotype.py \
  --input /path/to/ignite_jpgs \
  --plate-id seed_plate_01 \
  --roi-config examples/rois.example.json
```

Outputs go to `SeedThermal/processed/runs/<plate_id>/<timestamp>/`.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Relationship to ActinTrackCV

| Project | Focus |
|---------|--------|
| **ActinTrackCV** | Arabidopsis reproductive-cell confocal microscopy, F-actin bright-point tracking |
| **SeedThermal** | FLIR thermal imaging, seed/plate temperature time series, viability pilot work |

No shared Python modules — install and run each project independently.

## Hardware notes (FLIR ONE Edge)

- Native thermal sensor: **80×60**; exports include upscaled arrays (~640×480) via `flyr`
- Use **Ignite download** for radiometric stills; **30 sec/frame** still series for imbibition pilots
- Exploratory seed phenotyping is feasible on **larger seeds**; Arabidopsis-sized seeds may be pixel-limited
