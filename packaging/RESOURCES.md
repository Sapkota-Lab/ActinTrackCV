# Bundled resources

Read-only resources that future packaging specs (PyInstaller, etc.) must include
so the frozen app can find them via `actintrack_app.paths.resource_path(...)`.

These are resolved relative to `resource_root()`:
- in development → source repo root
- when frozen → PyInstaller's `sys._MEIPASS`

## Asset layout

```text
packaging/assets/
  app/
    actintrackcv.png      ← runtime window/app icon (QIcon)
    actintrackcv.ico      ← TODO (Windows .exe / installer icon)
    actintrackcv.icns     ← TODO (macOS .app bundle icon)
  screenshots/            ← reserved for future docs screenshots
```

## Must bundle
- `README.md` — shown by Help → How to Run.
- `packaging/assets/app/actintrackcv.png` — runtime window/app icon (QIcon).

## Icon assets
- `packaging/assets/app/actintrackcv.png` — present (final app icon).
- `packaging/assets/app/actintrackcv.ico` — TODO (Windows .exe / installer icon).
- `packaging/assets/app/actintrackcv.icns` — TODO (macOS .app bundle icon).

The `.png` is used at runtime by Qt. The `.ico`/`.icns` are needed by the
installer/bundle steps in a later phase and are not loaded by the running app.
The Windows spec wires the `.ico` into the EXE automatically once the file
exists; the macOS spec wires the `.icns` into the `.app` automatically once it
exists. Until then both use the default PyInstaller icon (runtime PNG still works).

## Platform builds

- **Windows** — PyInstaller one-folder app (`packaging/windows/`):
  `dist/ActinTrackCV/ActinTrackCV.exe`.
- **macOS** — PyInstaller `.app` bundle (`packaging/macos/`):
  `dist/ActinTrackCV.app`. Unsigned/un-notarized for now (Gatekeeper warning;
  right-click → Open for internal builds).

Both bundle `README.md` and `packaging/assets/app/actintrackcv.png`, and neither
bundles user/project data folders.

> No `.dmg` or installer-wizard scripts live here yet — those are later phases.
