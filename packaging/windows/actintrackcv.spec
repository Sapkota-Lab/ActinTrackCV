# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder spec for ActinTrackCV (Windows).

Build from the repo root (build_windows.ps1 sets the working directory):

    python -m PyInstaller --clean --noconfirm packaging/windows/actintrackcv.spec

Produces a debuggable one-folder, windowed app:

    dist/ActinTrackCV/ActinTrackCV.exe

Targets PyInstaller 6.x. This spec intentionally does NOT bundle user/project
data (raw/ processed/ previews/ metadata/ raw_source/ frames/, sample videos);
those live in the user workspace (~/Documents/ActinTrackCV) at runtime.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

# build_windows.ps1 runs PyInstaller with CWD = repo root.
REPO_ROOT = Path.cwd()

ENTRY = str(REPO_ROOT / "actintrack_app" / "main.py")

# Read-only resources, laid out to match actintrack_app.paths.resource_path(),
# which resolves under sys._MEIPASS in frozen builds:
#   resource_path("README.md")                                     -> <bundle>/README.md
#   resource_path("packaging","assets","app","actintrackcv.png")   -> <bundle>/packaging/assets/app/...
_ASSET_DIR = REPO_ROOT / "packaging" / "assets" / "app"
datas = [
    (str(REPO_ROOT / "README.md"), "."),
    (str(_ASSET_DIR / "actintrackcv.png"), "packaging/assets/app"),
]

# Windows EXE icon: embed the .ico when present. Also bundle it as a resource so
# actintrack_app.paths.icon_path() can fall back to it at runtime; the .png stays
# the primary runtime QIcon source.
_ico = _ASSET_DIR / "actintrackcv.ico"
exe_icon = str(_ico) if _ico.is_file() else None
if _ico.is_file():
    datas.append((str(_ico), "packaging/assets/app"))

# Bundle the standalone ffmpeg binary that imageio-ffmpeg ships, so
# actintrack_app.video_normalize can pad odd-dimension imports to even at runtime
# (imageio_ffmpeg.get_ffmpeg_exe() resolves inside the frozen app). This is the
# fix for odd-height MP4/AVI files decoding to black/garbled frames on Windows.
datas += collect_data_files("imageio_ffmpeg")

# OpenCV video backends (FFmpeg DLL) are required for AVI/MP4 via cv2.VideoCapture.
# Pull them explicitly so video loading works on a clean machine. PyQt6, pandas,
# numpy and tifffile are imported directly and handled by PyInstaller's hooks.
binaries = collect_dynamic_libs("cv2")

# Add hidden imports here only with evidence from a real Windows build failure.
hiddenimports = []


a = Analysis(
    [ENTRY],
    pathex=[str(REPO_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ActinTrackCV",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # windowed: no console window on double-click
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=exe_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ActinTrackCV",
)
