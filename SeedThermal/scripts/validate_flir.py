#!/usr/bin/env python3
"""Validate a radiometric FLIR JPG and print basic temperature stats."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seedthermal.phenotype import load_flir_radiometric  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate radiometric FLIR JPG extraction with flyr.")
    parser.add_argument("image", type=Path, help="Path to radiometric JPG (e.g. from FLIR Ignite download)")
    args = parser.parse_args()

    path = args.image.expanduser().resolve()
    try:
        capture = load_flir_radiometric(path)
    except FileNotFoundError:
        print(f"File not found: {path}", file=sys.stderr)
        return 1
    except ImportError:
        print("flyr is not installed. Run: pip install -r requirements.txt", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"flyr failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"flyr failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    temps = capture.celsius
    print(f"file: {path}")
    print(f"shape: {temps.shape}")
    print(f"celsius_min: {float(temps.min()):.3f}")
    print(f"celsius_max: {float(temps.max()):.3f}")
    print(f"celsius_mean: {float(temps.mean()):.3f}")
    if capture.emissivity is not None:
        print(f"emissivity: {capture.emissivity}")
    if capture.object_distance_m is not None:
        print(f"object_distance: {capture.object_distance_m}")
    if capture.capture_time_utc:
        print(f"capture_time_utc: {capture.capture_time_utc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
