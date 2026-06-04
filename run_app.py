#!/usr/bin/env python3
"""Launch the ActinTrackCV desktop GUI from the project root."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    try:
        from actintrack_app.gui import run_app
    except ImportError as exc:
        print("ActinTrackCV could not start: missing dependencies.")
        print()
        print("From the project root, run:")
        print("  python3 -m venv .venv")
        print("  source .venv/bin/activate    # Windows: .venv\\Scripts\\activate")
        print("  pip install -r requirements.txt")
        print("  python run_app.py")
        print()
        print(f"Details: {exc}")
        sys.exit(1)

    run_app()


if __name__ == "__main__":
    main()
