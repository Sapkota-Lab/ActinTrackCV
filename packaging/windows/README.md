# Windows build (PyInstaller, one-folder)

Builds a debuggable one-folder, windowed Windows app for Windows 10/11 x64.
This is a **one-folder pre-release** (zip), **not** an installer wizard yet.

> **Must run on Windows.** PyInstaller does not cross-compile — the `.exe` must
> be built on a Windows 10/11 x64 machine.

## Prerequisites

- Windows 10/11
- Python 3.10+ on PATH
- Build environment (runtime deps + PyInstaller):

```powershell
python -m pip install -r requirements-build.txt
```

This installs `requirements.txt` plus `pyinstaller`. The build script verifies
PyInstaller is present before running.

## Build

From the repo root (or anywhere — the script locates the root):

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build_windows.ps1
```

Output: `dist\ActinTrackCV\ActinTrackCV.exe`

## What gets bundled

- `README.md` → bundle root, read via `resource_path("README.md")`.
- `packaging/assets/app/actintrackcv.png` → `packaging/assets/app/`, read via `icon_path()`.
- `packaging/assets/app/actintrackcv.ico` → embedded as the `.exe` icon, and
  bundled as a resource fallback.
- OpenCV FFmpeg/videoio DLLs (`collect_dynamic_libs("cv2")`) for AVI/MP4.

Frozen builds resolve resources under PyInstaller's `sys._MEIPASS` via
`actintrack_app.paths.resource_root()`.

## Package as a release zip

Zip the **whole** one-folder app (the `.exe` needs the `_internal` folder and
bundled files next to it — do not zip the `.exe` alone). From the repo root:

```powershell
Compress-Archive -Path dist\ActinTrackCV -DestinationPath ActinTrackCV-0.2.1-windows-x64-onefolder.zip -Force
```

Verify the zip contains a top-level `ActinTrackCV\` folder with `ActinTrackCV.exe`
and `_internal\` inside it.

## End-user instructions (unsigned pre-release)

1. Download `ActinTrackCV-0.2.1-windows-x64-onefolder.zip`.
2. Unzip it.
3. Open the `ActinTrackCV` folder.
4. Double-click `ActinTrackCV.exe`.
5. Keep the whole folder together — do **not** move `ActinTrackCV.exe` out on its own.

Because the build is **unsigned**, Windows SmartScreen may warn on first launch:
click **More info → Run anyway**.

## Debugging a frozen-build crash

A windowed (default) build hides Python tracebacks and can vanish on an
unhandled error. Two opt-in aids help diagnose import/decoding crashes:

1. **Console debug build** — attach a console so tracebacks/ffmpeg output are
   visible when launched from PowerShell:

   ```powershell
   powershell -ExecutionPolicy Bypass -File packaging\windows\build_windows.ps1 -Console
   .\dist\ActinTrackCV\ActinTrackCV.exe   # run from PowerShell to see output
   ```

2. **Breadcrumb log** — set `ACTINTRACKCV_DEBUG=1` before launching to append
   flushed checkpoints of the Add Sample import path to
   `Documents\ActinTrackCV\logs\import_debug.log`. Because each line is flushed
   and fsynced, the last line survives even a hard native crash, pinpointing the
   failing step (validation, dimension probe, ffmpeg normalization, etc.):

   ```powershell
   $env:ACTINTRACKCV_DEBUG = "1"
   .\dist\ActinTrackCV\ActinTrackCV.exe
   # reproduce the crash, then inspect:
   Get-Content "$env:USERPROFILE\Documents\ActinTrackCV\logs\import_debug.log" -Tail 40
   ```

Both are temporary debugging aids. Release builds must leave `-Console` off and
do not require `ACTINTRACKCV_DEBUG` (logging is a no-op when it is unset).

## What is NOT bundled (by design)

User/project data stays in the workspace at runtime, not in the app:
`raw/`, `processed/`, `previews/`, `metadata/`, `raw_source/`, `frames/`, sample
videos. First launch creates/uses `~/Documents/ActinTrackCV`.

## Future work

- Validate AVI/MP4 loading on a clean Windows machine without Python.
- Installer wizard (Inno Setup / NSIS / WiX).
- Code signing certificate to reduce SmartScreen warnings.
