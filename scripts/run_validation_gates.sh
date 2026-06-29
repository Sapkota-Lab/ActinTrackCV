#!/usr/bin/env bash
# Run the same publication validation gates as CI (from repository root).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi

export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"

echo "==> Python unit tests"
"$PYTHON" -m unittest discover -s tests -v

echo "==> Layer 1 — landmark tracking synthetic gate"
"$PYTHON" scripts/validate_tracker.py

echo "==> Layer 1 — template tracking synthetic gate"
"$PYTHON" scripts/validate_tracker.py --tracking-method template

echo "==> Layer 1 — optical flow synthetic gate"
"$PYTHON" scripts/validate_optical_flow.py

echo "==> Layer 2 — stage calibration synthetic gate"
"$PYTHON" scripts/validate_stage_calibration.py --synthetic

if command -v Rscript >/dev/null 2>&1; then
  echo "==> Shiny helper tests"
  Rscript tests/test_shiny_helpers.R
else
  echo "WARN: Rscript not found; skipping Shiny helper tests"
fi

echo "==> End-to-end Shiny workflow gate"
"$PYTHON" scripts/validate_shiny_workflow.py

echo "All validation gates passed."
