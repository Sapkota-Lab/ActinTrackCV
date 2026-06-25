# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller .app bundle spec for ActinTrackCV (macOS).

Build from the repo root (build_macos.sh sets the working directory):

    python -m PyInstaller --clean --noconfirm packaging/macos/actintrackcv.spec

Produces a debuggable windowed bundle:

    dist/ActinTrackCV.app

Targets PyInstaller 6.x. This spec intentionally does NOT bundle user/project
data (raw/ processed/ previews/ metadata/ raw_source/ frames/, sample videos);
those live in the user workspace (~/Documents/ActinTrackCV) at runtime.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

# build_macos.sh runs PyInstaller with CWD = repo root.
REPO_ROOT = Path.cwd()

# Single source of truth for the version (used in the bundle Info.plist).
version_ns = {}
exec((REPO_ROOT / "actintrack_app" / "__version__.py").read_text(), version_ns)
APP_VERSION = version_ns.get("__version__", "0.0.0")

ENTRY = str(REPO_ROOT / "actintrack_app" / "main.py")

# Read-only resources, laid out to match actintrack_app.paths.resource_path(),
# which resolves under sys._MEIPASS in frozen builds:
#   resource_path("README.md")                                   -> <bundle>/README.md
#   resource_path("packaging","assets","app","actintrackcv.png") -> <bundle>/packaging/assets/app/...
datas = [
    (str(REPO_ROOT / "README.md"), "."),
    (
        str(REPO_ROOT / "packaging" / "assets" / "app" / "actintrackcv.png"),
        "packaging/assets/app",
    ),
]

# Bundle the standalone ffmpeg binary that imageio-ffmpeg ships, so
# actintrack_app.video_normalize can pad odd-dimension imports to even at runtime
# (imageio_ffmpeg.get_ffmpeg_exe() resolves inside the frozen bundle).
datas += collect_data_files("imageio_ffmpeg")

# OpenCV video backends (FFmpeg dylib) are required for AVI/MP4 via cv2.VideoCapture.
# PyQt6, pandas, numpy and tifffile are imported directly and handled by hooks.
binaries = collect_dynamic_libs("cv2")

# Add hidden imports here only with evidence from a real macOS build failure.
hiddenimports = []

# macOS .app icon needs an .icns (not created yet -> see packaging/RESOURCES.md).
# Until it exists, the bundle uses the default icon; the runtime QIcon (PNG) still works.
_icns = REPO_ROOT / "packaging" / "assets" / "app" / "actintrackcv.icns"
app_icon = str(_icns) if _icns.is_file() else None


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
    console=False,  # windowed app (no terminal window)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,  # native arch (arm64 or x86_64); universal2 is a later concern
    codesign_identity=None,
    entitlements_file=None,
    icon=app_icon,
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

app = BUNDLE(
    coll,
    name="ActinTrackCV.app",
    icon=app_icon,
    bundle_identifier="org.sapkotalab.actintrackcv",
    version=APP_VERSION,
    info_plist={
        "CFBundleName": "ActinTrackCV",
        "CFBundleDisplayName": "ActinTrackCV",
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "NSHighResolutionCapable": True,
    },
)
