"""File > Import Data dialog for structured 2D Arabidopsis microscopy import."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from actintrack_app.batch_manager import (
    allocate_next_batch,
    batch_has_video,
    create_batch,
    create_batch_for_video_import,
    display_batch_name,
    ensure_default_batch,
    list_batches,
    rename_batch,
    sanitize_batch_name,
)
from actintrack_app.file_importer import import_files
from actintrack_app.import_classifier import (
    ImportKind,
    MIXED_MESSAGE,
    WIP_MESSAGE,
    classify_paths,
    import_kind_label,
)
from actintrack_app.metadata import load_samples_csv
from actintrack_app.utils import GROUPS, METADATA_DIR, SAMPLES_CSV

if TYPE_CHECKING:
    from actintrack_app.gui import MainWindow

NEW_VIDEO_BATCH_TOKEN = "__new_video_batch__"

ALL_IMPORT_FILTER = (
    "Microscopy files (*.png *.jpg *.jpeg *.tif *.tiff *.avi *.mp4 "
    "*.oib *.oif *.oir);;All files (*)"
)


class ImportDataDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        project_root: Path,
        last_dir: Path,
        on_success: Callable[[], None] | None = None,
        *,
        preset_group: str | None = None,
        preset_batch_name: str | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Import Data")
        self.resize(520, 520)
        self._root = Path(project_root).resolve()
        self._last_dir = last_dir
        self._on_success = on_success
        self._preset_group = preset_group
        self._preset_batch_name = preset_batch_name
        self._paths: list[Path] = []
        self._kind = ImportKind.EMPTY

        layout = QVBoxLayout(self)

        intro = QLabel(
            "Import Arabidopsis fluorescence microscopy time-lapse data showing "
            "labeled F-actin cables near the egg apparatus / nucleus-adjacent region. "
            "Select files first, then choose a condition group and biological batch."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        sel_row = QHBoxLayout()
        self.btn_select = QPushButton("Select Files…")
        self.btn_select.clicked.connect(self._on_select_files)
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.clicked.connect(self._on_clear_files)
        sel_row.addWidget(self.btn_select)
        sel_row.addWidget(self.btn_clear)
        layout.addLayout(sel_row)

        self.list_files = QListWidget()
        self.list_files.setMaximumHeight(120)
        layout.addWidget(self.list_files)

        type_box = QGroupBox("Detected import type")
        type_layout = QVBoxLayout(type_box)
        self.lbl_type = QLabel("—")
        self.lbl_type.setWordWrap(True)
        type_layout.addWidget(self.lbl_type)
        layout.addWidget(type_box)

        form = QFormLayout()
        self.combo_group = QComboBox()
        self.combo_group.addItems(list(GROUPS))
        self.combo_group.currentTextChanged.connect(self._on_group_changed)
        form.addRow("Condition group:", self.combo_group)

        batch_row = QHBoxLayout()
        self.combo_batch = QComboBox()
        self.combo_batch.setMinimumWidth(180)
        batch_row.addWidget(self.combo_batch, stretch=1)
        self.btn_new_batch = QPushButton("New Batch")
        self.btn_new_batch.clicked.connect(self._on_new_batch)
        self.btn_rename_batch = QPushButton("Rename")
        self.btn_rename_batch.clicked.connect(self._on_rename_batch)
        batch_row.addWidget(self.btn_new_batch)
        batch_row.addWidget(self.btn_rename_batch)
        form.addRow("Biological batch:", batch_row)

        self.lbl_batch_hint = QLabel("")
        self.lbl_batch_hint.setWordWrap(True)
        self.lbl_batch_hint.setStyleSheet("color: #888; font-size: 11px;")
        form.addRow("", self.lbl_batch_hint)

        self.txt_notes = QTextEdit()
        self.txt_notes.setMaximumHeight(60)
        self.txt_notes.setPlaceholderText("Optional notes for imported files")
        form.addRow("Notes:", self.txt_notes)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.btn_import = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.btn_import.setText("Import")
        self.btn_import.setEnabled(False)
        buttons.accepted.connect(self._on_import)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if self._preset_group:
            idx = self.combo_group.findText(self._preset_group)
            if idx >= 0:
                self.combo_group.setCurrentIndex(idx)
        self._on_group_changed()
        self._select_preset_batch()
        self._refresh_file_list()

    def _select_preset_batch(self) -> None:
        if not self._preset_batch_name:
            return
        idx = self.combo_batch.findText(self._preset_batch_name)
        if idx >= 0:
            self.combo_batch.setCurrentIndex(idx)

    def _on_group_changed(self) -> None:
        group = self.combo_group.currentText()
        batches = list_batches(self._root, group)
        current_data = self.combo_batch.currentData()
        self.combo_batch.blockSignals(True)
        self.combo_batch.clear()
        if self._kind == ImportKind.VIDEO:
            self.combo_batch.addItem(
                "(Create new batch for this video)", NEW_VIDEO_BATCH_TOKEN
            )
        for b in batches:
            self.combo_batch.addItem(str(b["batch_name"]), b)
        if self._preset_batch_name:
            self._select_preset_batch()
        elif self._kind == ImportKind.VIDEO:
            self.combo_batch.setCurrentIndex(0)
        elif current_data and isinstance(current_data, dict):
            idx = self.combo_batch.findText(str(current_data.get("batch_name", "")))
            if idx >= 0:
                self.combo_batch.setCurrentIndex(idx)
        self.combo_batch.blockSignals(False)
        self._update_batch_hint()

    def _selected_batch(self) -> dict | None:
        data = self.combo_batch.currentData()
        if data == NEW_VIDEO_BATCH_TOKEN:
            return None
        return data if isinstance(data, dict) else None

    def _on_select_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select files to import",
            str(self._last_dir),
            ALL_IMPORT_FILTER,
        )
        if not paths:
            return
        self._last_dir = Path(paths[0]).parent
        self._paths = [Path(p) for p in paths]
        self._refresh_file_list()

    def _on_clear_files(self) -> None:
        self._paths = []
        self._kind = ImportKind.EMPTY
        self._refresh_file_list()

    def _refresh_file_list(self) -> None:
        self.list_files.clear()
        for p in self._paths:
            self.list_files.addItem(p.name)
        self._kind, _, msg = classify_paths(self._paths)
        self._on_group_changed()
        if msg and self._kind in (ImportKind.WIP_RAW_3D, ImportKind.MIXED, ImportKind.EMPTY):
            self.lbl_type.setText(f"{import_kind_label(self._kind)}\n\n{msg}")
        elif self._kind == ImportKind.VIDEO:
            self.lbl_type.setText(
                f"{import_kind_label(self._kind)}\n\n"
                "One .avi or .mp4 file = one complete Arabidopsis sample timelapse. "
                "Default: create a new biological batch."
            )
        elif self._kind == ImportKind.IMAGE_SEQUENCE:
            n = len(self._paths)
            self.lbl_type.setText(
                f"{import_kind_label(self._kind)}\n\n"
                f"{n} image(s) will be added to the selected biological batch."
            )
        else:
            self.lbl_type.setText(import_kind_label(self._kind))
        can_import = self._kind in (ImportKind.IMAGE_SEQUENCE, ImportKind.VIDEO)
        self.btn_import.setEnabled(can_import and bool(self._paths))
        self._update_batch_hint()

    def _update_batch_hint(self) -> None:
        if self._kind == ImportKind.VIDEO:
            self.lbl_batch_hint.setText(
                "Default: new batch for this video. Choose an existing batch only "
                "if needed; you will be warned if it already contains a video or other files."
            )
        elif self._kind == ImportKind.IMAGE_SEQUENCE:
            self.lbl_batch_hint.setText(
                "Multiple 2D images can share one biological batch (image/frame collection)."
            )
        elif self._kind == ImportKind.WIP_RAW_3D:
            self.lbl_batch_hint.setText(WIP_MESSAGE)
        else:
            self.lbl_batch_hint.setText("Select supported 2D image or video files.")

    def _on_new_batch(self) -> None:
        group = self.combo_group.currentText()
        try:
            _num, default_name = allocate_next_batch(self._root, group)
            batch = create_batch(self._root, group, default_name)
            self._on_group_changed()
            self.combo_batch.setCurrentText(batch["batch_name"])
        except ValueError as e:
            QMessageBox.warning(self, "New Batch", str(e))

    def _on_rename_batch(self) -> None:
        batch = self._selected_batch()
        if not batch:
            QMessageBox.information(
                self,
                "Rename Batch",
                "Select an existing batch to rename (not the new-video placeholder).",
            )
            return
        group = self.combo_group.currentText()
        old = batch["batch_name"]
        new_name, ok = QInputDialog.getText(
            self, "Rename Biological Batch", "New batch name:", text=old
        )
        if not ok or not new_name.strip():
            return
        try:
            rename_batch(self._root, group, old, new_name.strip())
            self._on_group_changed()
            self.combo_batch.setCurrentText(sanitize_batch_name(new_name))
        except (ValueError, OSError) as e:
            QMessageBox.critical(self, "Rename Batch", str(e))

    def _batch_has_any_files(self, group: str, batch_name: str) -> bool:
        df = load_samples_csv(self._root / METADATA_DIR / SAMPLES_CSV)
        safe = sanitize_batch_name(batch_name)
        sub = df[
            (df["group"] == group)
            & (df["batch_name"].astype(str).apply(sanitize_batch_name) == safe)
        ]
        return not sub.empty

    def _on_import(self) -> None:
        try:
            self._do_import()
        except Exception as e:
            QMessageBox.critical(
                self,
                "Import Failed",
                f"Import failed unexpectedly:\n{e}",
            )

    def _do_import(self) -> None:
        kind, paths, msg = classify_paths(self._paths)
        if kind not in (ImportKind.IMAGE_SEQUENCE, ImportKind.VIDEO):
            if kind == ImportKind.WIP_RAW_3D:
                QMessageBox.information(self, "Import Not Available", WIP_MESSAGE)
            else:
                QMessageBox.warning(self, "Cannot Import", msg or MIXED_MESSAGE)
            return

        group = self.combo_group.currentText()
        notes = self.txt_notes.toPlainText().strip()

        if kind == ImportKind.VIDEO:
            path = paths[0]
            use_new = self.combo_batch.currentData() == NEW_VIDEO_BATCH_TOKEN
            batch = self._selected_batch()
            if use_new:
                batch = create_batch_for_video_import(self._root, group)
            else:
                if batch is None:
                    batch = create_batch_for_video_import(self._root, group)
                elif batch_has_video(self._root, group, batch["batch_name"]):
                    warn = QMessageBox.warning(
                        self,
                        "Video in Batch",
                        "This batch already contains a video. One video per biological "
                        "batch is strongly recommended.\n\nContinue anyway?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    if warn != QMessageBox.StandardButton.Yes:
                        return
                elif self._batch_has_any_files(group, batch["batch_name"]):
                    warn2 = QMessageBox.warning(
                        self,
                        "Batch Has Files",
                        "This batch already contains imported files. "
                        "Continue adding the video?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    if warn2 != QMessageBox.StandardButton.No:
                        return
            created = import_files(
                [path],
                group,
                batch["batch_name"],
                batch["batch_id"],
                self._root,
                batch_number=int(batch["batch_number"]),
                notes=notes,
            )
        else:
            batch = self._selected_batch()
            if batch is None:
                batch = ensure_default_batch(self._root, group)
            created = import_files(
                paths,
                group,
                batch["batch_name"],
                batch["batch_id"],
                self._root,
                batch_number=int(batch["batch_number"]),
                notes=notes,
            )

        QMessageBox.information(
            self,
            "Import Complete",
            f"Imported {len(created)} file(s) into {group} / {batch['batch_name']}.",
        )
        self.accept()

    def last_import_dir(self) -> Path:
        return self._last_dir

    @property
    def selected_group(self) -> str:
        return self.combo_group.currentText()

    @property
    def selected_batch_name(self) -> str:
        if self.combo_batch.currentData() == NEW_VIDEO_BATCH_TOKEN:
            batches = list_batches(
                self._root, self.combo_group.currentText()
            )
            if batches:
                return str(batches[-1]["batch_name"])
            return display_batch_name(1)
        return self.combo_batch.currentText()


def open_import_data_dialog(
    window: "MainWindow",
    *,
    preset_group: str | None = None,
    preset_batch_name: str | None = None,
) -> None:
    if window._project_root is None:
        QMessageBox.warning(window, "Import Data", "Open or create a workspace first.")
        return

    dlg = ImportDataDialog(
        window,
        window._project_root,
        window._last_import_dir,
        on_success=window._after_import_refresh,
        preset_group=preset_group,
        preset_batch_name=preset_batch_name,
    )
    if dlg.exec() == QDialog.DialogCode.Accepted:
        window._last_import_dir = dlg.last_import_dir()
        window._after_import_refresh()
        window.combo_filter_group.setCurrentText(dlg.selected_group)
        window._status("Import finished")
