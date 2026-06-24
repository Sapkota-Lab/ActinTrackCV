# macOS build (PyInstaller, .app bundle)

Builds a debuggable windowed `ActinTrackCV.app`. No `.dmg`, signing, or
notarization yet (see future-work notes below).

## Prerequisites

- macOS
- Python 3.10+ on PATH
- Build environment (runtime deps + PyInstaller):

```bash
python -m pip install -r requirements-build.txt
```

This installs `requirements.txt` plus `pyinstaller`. The build script verifies
PyInstaller is present but does not install anything for you.

## Build

From the repo root (or anywhere — the script locates the root):

```bash
bash packaging/macos/build_macos.sh
```

Output: `dist/ActinTrackCV.app`

Options: `SKIP_TESTS=1` and `KEEP_OLD=1` as environment variables.

## Open the app

```bash
open dist/ActinTrackCV.app
```

### Unsigned app / Gatekeeper

This build is **not code-signed or notarized**, so Gatekeeper will warn that the
app is from an unidentified developer. For an internal build, open it once via:

- **Right-click (or Control-click) `ActinTrackCV.app` → Open → Open**, or
- System Settings → Privacy & Security → "Open Anyway" after the first blocked launch.

After the first approved launch, double-click works normally. (Distributing to
other Macs cleanly requires signing + notarization — a future phase.)

## Uninstall

macOS apps do not need an uninstall wizard. Drag `ActinTrackCV.app` to the
Trash (or `rm -rf` it). Your projects in `~/Documents/ActinTrackCV` are left
untouched; delete that folder too if you no longer need them.

## What gets bundled

- `README.md` → bundle resource root, read via `resource_path("README.md")`.
- `packaging/assets/app/actintrackcv.png` → `packaging/assets/app/`, read via `icon_path()`.
- OpenCV FFmpeg/videoio dylibs (`collect_dynamic_libs("cv2")`) for AVI/MP4.

Frozen builds resolve resources under PyInstaller's `sys._MEIPASS` via
`actintrack_app.paths.resource_root()`.

## What is NOT bundled (by design)

User/project data stays in the workspace at runtime, not in the app:
`raw/`, `processed/`, `previews/`, `metadata/`, `raw_source/`, `frames/`, sample
videos. First launch creates/uses `~/Documents/ActinTrackCV` (never inside
`ActinTrackCV.app`).

## Clean-machine validation checklist

On a Mac that did not build the app (ideally without the dev environment):

- [ ] `ActinTrackCV.app` launches (right-click → Open the first time).
- [ ] About shows `ActinTrackCV 0.1.0`.
- [ ] App/runtime icon appears.
- [ ] Help → How to Run does not crash.
- [ ] Workspace is created at `~/Documents/ActinTrackCV`, not inside the `.app`.
- [ ] Add Sample opens the file picker (starts in Documents/home).
- [ ] **AVI loads.**
- [ ] **MP4 loads.**
- [ ] ROI suggestion / manual ROI works and autosaves.
- [ ] Metric Analysis View opens.
- [ ] Template Tracking runs; Optical Flow runs.
- [ ] Analysis reads saved per-Sample results.
- [ ] Nothing is written inside `ActinTrackCV.app` except logs/crash artifacts.

AVI/MP4 loading must be verified in the **frozen** app — codec issues may not
appear when running from source.

## Future phases (not done here)

- `.dmg` packaging.
- Code signing + notarization (required for clean distribution to other Macs).
- `packaging/assets/app/actintrackcv.icns` for the `.app` icon (the spec wires it
  in automatically once the file exists).
- universal2 (arm64 + x86_64) builds — current builds are native arch only.
