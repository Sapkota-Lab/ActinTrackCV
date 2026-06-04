#!/usr/bin/env bash
# Launch ActinTrackCV GUI (macOS / Linux)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ -d ".venv/bin" ]]; then
  # shellcheck source=/dev/null
  source ".venv/bin/activate"
elif [[ -d "venv/bin" ]]; then
  # shellcheck source=/dev/null
  source "venv/bin/activate"
fi

exec python3 run_app.py "$@"
