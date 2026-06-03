"""PyQt6 GUI for ActinTrackCV (phase 1: import, preview, manual cutoff)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PyQt6.QtCore import Qt, QPoint, QRect
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QFont, QBrush
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from actintrack_app.file_importer import import_files
from actintrack_app.metadata import (
    build_cutoff_annotation,
    load_crop_metadata,
    load_samples_csv,
    remove_samples_from_metadata,
    save_sample_crop_annotation,
    sync_samples_with_disk,
    update_samples_csv,
)
from actintrack_app.project_manager import create_project_structure, is_valid_project
from actintrack_app.utils import (
    CROP_METADATA_JSON,
    GROUPS,
    GROUP_MUTANT,
    GROUP_WT,
    METADATA_DIR,
    SAMPLES_CSV,
)
from actintrack_app.video_processing import MediaLoadError, load_media_frame


def numpy_bgr_to_qimage(frame: np.ndarray) -> QImage:
    h, w = frame.shape[:2]
    if frame.ndim == 2:
        bytes_per_line = w
        qimg = QImage(frame.data, w, h, bytes_per_line, QImage.Format.Format_Grayscale8)
    else:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        bytes_per_line = 3 * w
        qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
    return qimg.copy()


class ImageCanvas(QLabel):
    """Displays frame with draggable horizontal cutoff line."""

    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__(parent)
        self._main_window = main_window
        self.setMinimumSize(480, 360)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: #1e1e1e; border: 1px solid #444;")
        self._frame: Optional[np.ndarray] = None
        self._pixmap: Optional[QPixmap] = None
        self._cutoff_y: Optional[int] = None
        self._scale = 1.0
        self._offset_x = 0
        self._offset_y = 0
        self._dragging = False

    def clear_preview(self) -> None:
        self._frame = None
        self._pixmap = None
        self._cutoff_y = None
        self.clear()

    def set_frame(self, frame: np.ndarray) -> None:
        self._frame = frame
        self._cutoff_y = None
        self._update_pixmap()

    def set_cutoff_y(self, y: Optional[int]) -> None:
        if self._frame is None:
            return
        h = self._frame.shape[0]
        if y is None:
            self._cutoff_y = None
        else:
            self._cutoff_y = max(0, min(int(y), h - 1))
        self._redraw()

    def cutoff_y(self) -> Optional[int]:
        return self._cutoff_y

    def _update_pixmap(self) -> None:
        if self._frame is None:
            self._pixmap = None
            self.clear()
            return
        qimg = numpy_bgr_to_qimage(self._frame)
        self._pixmap = QPixmap.fromImage(qimg)
        self._redraw()

    def _redraw(self) -> None:
        if self._pixmap is None:
            return
        target = self.size()
        scaled = self._pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._scale = scaled.height() / self._pixmap.height()
        self._offset_x = (target.width() - scaled.width()) // 2
        self._offset_y = (target.height() - scaled.height()) // 2

        composite = QPixmap(target)
        composite.fill(QColor("#1e1e1e"))
        painter = QPainter(composite)
        painter.drawPixmap(self._offset_x, self._offset_y, scaled)

        if self._cutoff_y is not None and self._frame is not None:
            h = self._frame.shape[0]
            sy = self._offset_y + int(self._cutoff_y * self._scale)
            pen_line = QPen(QColor(255, 80, 80), 2)
            painter.setPen(pen_line)
            painter.drawLine(
                self._offset_x,
                sy,
                self._offset_x + scaled.width(),
                sy,
            )
            # Region labels
            painter.setFont(QFont("Helvetica", 9, QFont.Weight.Bold))
            painter.setPen(QColor(100, 220, 120))
            painter.drawText(
                self._offset_x + 8,
                self._offset_y + 18,
                "Analysis Region (above line)",
            )
            painter.setPen(QColor(255, 160, 100))
            painter.drawText(
                self._offset_x + 8,
                min(sy + 20, self._offset_y + scaled.height() - 8),
                "Excluded Blurry/Nucleus Region (below line)",
            )

        painter.end()
        self.setPixmap(composite)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._redraw()

    def _image_y_from_widget(self, wy: int) -> Optional[int]:
        if self._frame is None or self._pixmap is None:
            return None
        sy = wy - self._offset_y
        if sy < 0:
            return 0
        img_h = self._frame.shape[0]
        max_sy = int(img_h * self._scale)
        if sy > max_sy:
            return img_h - 1
        return int(round(sy / self._scale))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._frame is not None:
            y = self._image_y_from_widget(int(event.position().y()))
            if y is not None:
                self._cutoff_y = y
                self._dragging = True
                self._redraw()
                self._main_window.on_cutoff_changed(y)

    def mouseMoveEvent(self, event):
        if self._dragging and self._frame is not None:
            y = self._image_y_from_widget(int(event.position().y()))
            if y is not None:
                self._cutoff_y = y
                self._redraw()
                self._main_window.on_cutoff_changed(y)

    def mouseReleaseEvent(self, event):
        self._dragging = False


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ActinTrackCV — Phase 1")
        self.resize(1280, 800)

        self._project_root: Optional[Path] = None
        self._current_sample: Optional[dict] = None
        self._frame: Optional[np.ndarray] = None
        self._frame_index = 0
        self._total_frames = 1
        self._import_group = GROUP_WT

        self._build_ui()
        self._status("Select or create a project folder to begin.")

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Left panel ---
        left = QWidget()
        left_layout = QVBoxLayout(left)

        proj_box = QGroupBox("Project")
        proj_layout = QVBoxLayout(proj_box)
        self.btn_open_project = QPushButton("Select Project Folder…")
        self.btn_open_project.clicked.connect(self._on_select_project)
        self.lbl_project = QLabel("No project loaded")
        self.lbl_project.setWordWrap(True)
        proj_layout.addWidget(self.btn_open_project)
        proj_layout.addWidget(self.lbl_project)
        left_layout.addWidget(proj_box)

        import_box = QGroupBox("Import Files")
        import_layout = QVBoxLayout(import_box)
        self.combo_import_group = QComboBox()
        self.combo_import_group.addItems(list(GROUPS))
        self.btn_import = QPushButton("Import Files…")
        self.btn_import.clicked.connect(self._on_import_files)
        self.btn_import.setEnabled(False)
        import_layout.addWidget(QLabel("Assign to group:"))
        import_layout.addWidget(self.combo_import_group)
        import_layout.addWidget(self.btn_import)
        left_layout.addWidget(import_box)

        samples_box = QGroupBox("Samples")
        samples_layout = QVBoxLayout(samples_box)
        self.list_samples = QListWidget()
        self.list_samples.currentItemChanged.connect(self._on_sample_selected)
        samples_layout.addWidget(self.list_samples)
        btn_row = QHBoxLayout()
        self.btn_refresh_samples = QPushButton("Refresh List")
        self.btn_refresh_samples.clicked.connect(self._on_refresh_samples)
        self.btn_refresh_samples.setEnabled(False)
        self.btn_remove_missing = QPushButton("Remove Missing…")
        self.btn_remove_missing.clicked.connect(self._on_remove_missing_samples)
        self.btn_remove_missing.setEnabled(False)
        btn_row.addWidget(self.btn_refresh_samples)
        btn_row.addWidget(self.btn_remove_missing)
        samples_layout.addLayout(btn_row)
        left_layout.addWidget(samples_box, stretch=1)

        self.lbl_status = QLabel("Status: —")
        self.lbl_status.setWordWrap(True)
        left_layout.addWidget(self.lbl_status)

        splitter.addWidget(left)

        # --- Center panel ---
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.addWidget(QLabel("Preview — click or drag to set horizontal cutoff"))
        self.canvas = ImageCanvas(self)
        center_layout.addWidget(self.canvas, stretch=1)
        splitter.addWidget(center)

        # --- Right panel ---
        right = QWidget()
        right_layout = QVBoxLayout(right)

        frame_box = QGroupBox("Reference Frame")
        frame_layout = QVBoxLayout(frame_box)
        self.slider_frame = QSlider(Qt.Orientation.Horizontal)
        self.slider_frame.setMinimum(0)
        self.slider_frame.setMaximum(0)
        self.slider_frame.valueChanged.connect(self._on_frame_slider)
        self.spin_frame = QSpinBox()
        self.spin_frame.setMinimum(0)
        self.spin_frame.valueChanged.connect(self._on_frame_spin)
        self.lbl_frame_info = QLabel("Frame: — / —")
        frame_layout.addWidget(self.lbl_frame_info)
        frame_layout.addWidget(self.slider_frame)
        frame_layout.addWidget(self.spin_frame)
        self.btn_set_reference = QPushButton("Use Current Frame as Reference")
        self.btn_set_reference.clicked.connect(self._on_set_reference_frame)
        frame_layout.addWidget(self.btn_set_reference)
        right_layout.addWidget(frame_box)

        cutoff_box = QGroupBox("Blurry Region Cutoff")
        cutoff_layout = QVBoxLayout(cutoff_box)
        cutoff_layout.addWidget(
            QLabel(
                "Draw a horizontal line on the preview. "
                "Everything above the line is the analysis region."
            )
        )
        self.spin_cutoff = QSpinBox()
        self.spin_cutoff.setMinimum(0)
        self.spin_cutoff.setMaximum(99999)
        self.spin_cutoff.valueChanged.connect(self._on_cutoff_spin)
        cutoff_layout.addWidget(QLabel("Cutoff Y (image coordinates):"))
        cutoff_layout.addWidget(self.spin_cutoff)
        self.btn_clear_cutoff = QPushButton("Clear Cutoff Line")
        self.btn_clear_cutoff.clicked.connect(self._on_clear_cutoff)
        cutoff_layout.addWidget(self.btn_clear_cutoff)
        right_layout.addWidget(cutoff_box)

        notes_box = QGroupBox("Notes (saved with annotation)")
        notes_layout = QVBoxLayout(notes_box)
        self.txt_notes = QTextEdit()
        self.txt_notes.setMaximumHeight(80)
        self.txt_notes.setPlaceholderText("Optional notes for this sample…")
        notes_layout.addWidget(self.txt_notes)
        right_layout.addWidget(notes_box)

        self.btn_save_cutoff = QPushButton("Save Cutoff Annotation")
        self.btn_save_cutoff.clicked.connect(self._on_save_cutoff)
        self.btn_save_cutoff.setEnabled(False)
        right_layout.addWidget(self.btn_save_cutoff)

        phase_label = QLabel(
            "Phase 1: import, preview, manual cutoff.\n"
            "Segmentation, rotation, and crop export come in phase 2."
        )
        phase_label.setWordWrap(True)
        phase_label.setStyleSheet("color: #888;")
        right_layout.addWidget(phase_label)
        right_layout.addStretch()

        splitter.addWidget(right)
        splitter.setSizes([280, 720, 280])

        layout.addWidget(splitter)
        self.setStatusBar(QStatusBar())

    def _status(self, msg: str) -> None:
        self.statusBar().showMessage(msg)
        self.lbl_status.setText(f"Status: {msg}")

    def _on_select_project(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select or Create Project Folder",
            str(Path.home()),
        )
        if not folder:
            return
        root = Path(folder)
        try:
            if not is_valid_project(root):
                create_project_structure(root)
            self._project_root = root.resolve()
            self.lbl_project.setText(str(self._project_root))
            self.btn_import.setEnabled(True)
            self.btn_refresh_samples.setEnabled(True)
            self._refresh_sample_list()
            self._status(f"Project loaded: {self._project_root.name}")
        except OSError as e:
            QMessageBox.critical(self, "Project Error", f"Could not set up project:\n{e}")

    def _refresh_sample_list(self) -> None:
        self.list_samples.clear()
        if self._project_root is None:
            return
        samples_path = self._project_root / METADATA_DIR / SAMPLES_CSV
        try:
            df, missing_ids = sync_samples_with_disk(self._project_root)
        except Exception as e:
            QMessageBox.warning(self, "Metadata", f"Could not load samples.csv:\n{e}")
            return

        self.btn_remove_missing.setEnabled(bool(missing_ids))
        if missing_ids:
            self._status(
                f"{len(missing_ids)} sample(s) missing on disk — marked [missing file]. "
                "Use Remove Missing to clean up metadata."
            )

        for group in GROUPS:
            sub = df[df["group"] == group]
            if sub.empty:
                continue
            header = QListWidgetItem(f"── {group} ──")
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_samples.addItem(header)
            for _, row in sub.iterrows():
                status = str(row["processing_status"])
                if status == "missing_file":
                    label = (
                        f"⚠ {row['sample_id']}  [missing file]  {row['original_filename']}"
                    )
                else:
                    label = (
                        f"{row['sample_id']}  [{status}]  {row['original_filename']}"
                    )
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, row.to_dict())
                if status == "missing_file":
                    item.setForeground(QBrush(QColor("#cc6666")))
                self.list_samples.addItem(item)

    def _on_refresh_samples(self) -> None:
        if self._project_root is None:
            return
        self._refresh_sample_list()
        if not self.btn_remove_missing.isEnabled():
            self._status("Sample list synced with disk.")

    def _on_remove_missing_samples(self) -> None:
        if self._project_root is None:
            return
        _, missing_ids = sync_samples_with_disk(self._project_root)
        if not missing_ids:
            QMessageBox.information(self, "Remove Missing", "No missing samples to remove.")
            return

        names = ", ".join(missing_ids[:8])
        if len(missing_ids) > 8:
            names += f", … (+{len(missing_ids) - 8} more)"

        reply = QMessageBox.question(
            self,
            "Remove Missing Samples",
            f"Remove {len(missing_ids)} sample(s) from metadata?\n\n{names}\n\n"
            "This deletes their rows in samples.csv and crop_metadata.json. "
            "It does not affect other files on disk.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            removed = remove_samples_from_metadata(self._project_root, missing_ids)
            self._current_sample = None
            self.canvas.clear_preview()
            self.btn_save_cutoff.setEnabled(False)
            self._refresh_sample_list()
            self._status(f"Removed {removed} missing sample(s) from metadata.")
        except OSError as e:
            QMessageBox.critical(self, "Remove Failed", str(e))

    def _on_import_files(self) -> None:
        if self._project_root is None:
            QMessageBox.warning(self, "Import", "Select a project folder first.")
            return

        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Microscopy Files",
            str(Path.home()),
            "Media (*.avi *.mp4 *.tif *.tiff *.png *.jpg *.jpeg);;All Files (*)",
        )
        if not paths:
            return

        group = self.combo_import_group.currentText()
        try:
            created = import_files(paths, group, self._project_root)
            self._refresh_sample_list()
            self._status(f"Imported {len(created)} file(s) into {group}")
        except (FileNotFoundError, ValueError, OSError) as e:
            QMessageBox.critical(self, "Import Failed", str(e))

    def _on_sample_selected(
        self,
        current: Optional[QListWidgetItem],
        previous: Optional[QListWidgetItem],
    ) -> None:
        if current is None:
            return
        data = current.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        self._current_sample = data
        if str(data.get("processing_status", "")) == "missing_file":
            self._status(
                f"{data['sample_id']}: raw file deleted. "
                "Click Remove Missing… to drop it from the list."
            )
            return
        self._load_sample_preview()

    def _sample_file_path(self) -> Optional[Path]:
        if self._project_root is None or self._current_sample is None:
            return None
        return self._project_root / self._current_sample["stored_path"]

    def _load_sample_preview(self) -> None:
        path = self._sample_file_path()
        if path is None or not path.exists():
            QMessageBox.warning(self, "Load Error", "Sample file not found on disk.")
            return

        ref_idx = int(self._current_sample.get("reference_frame_index", 0) or 0)
        try:
            frame, idx, total = load_media_frame(path, ref_idx)
        except MediaLoadError as e:
            QMessageBox.critical(self, "Load Error", str(e))
            return

        self._frame = frame
        self._frame_index = idx
        self._total_frames = total
        h, w = frame.shape[:2]

        self.slider_frame.blockSignals(True)
        self.spin_frame.blockSignals(True)
        self.slider_frame.setMaximum(max(0, total - 1))
        self.spin_frame.setMaximum(max(0, total - 1))
        self.slider_frame.setValue(idx)
        self.spin_frame.setValue(idx)
        self.slider_frame.setEnabled(total > 1)
        self.spin_frame.setEnabled(total > 1)
        self.slider_frame.blockSignals(False)
        self.spin_frame.blockSignals(False)

        self.lbl_frame_info.setText(f"Frame: {idx} / {max(0, total - 1)}  ({w}×{h})")
        self.canvas.set_frame(frame)

        self.spin_cutoff.setMaximum(h - 1)
        self._restore_cutoff_from_metadata()
        self.btn_save_cutoff.setEnabled(True)
        self._status(f"Loaded {self._current_sample['sample_id']}")

    def _restore_cutoff_from_metadata(self) -> None:
        if self._project_root is None or self._current_sample is None:
            return
        meta_path = self._project_root / METADATA_DIR / CROP_METADATA_JSON
        data = load_crop_metadata(meta_path)
        sid = self._current_sample["sample_id"]
        ann = data.get("samples", {}).get(sid)
        if ann and ann.get("cutoff_y") is not None:
            y = int(ann["cutoff_y"])
            self.canvas.set_cutoff_y(y)
            self.spin_cutoff.blockSignals(True)
            self.spin_cutoff.setValue(y)
            self.spin_cutoff.blockSignals(False)
        else:
            self.canvas.set_cutoff_y(None)
            self.spin_cutoff.setValue(0)

    def _on_frame_slider(self, value: int) -> None:
        self.spin_frame.blockSignals(True)
        self.spin_frame.setValue(value)
        self.spin_frame.blockSignals(False)
        self._load_frame_index(value)

    def _on_frame_spin(self, value: int) -> None:
        self.slider_frame.blockSignals(True)
        self.slider_frame.setValue(value)
        self.slider_frame.blockSignals(False)
        self._load_frame_index(value)

    def _load_frame_index(self, index: int) -> None:
        path = self._sample_file_path()
        if path is None:
            return
        try:
            frame, idx, total = load_media_frame(path, index)
        except MediaLoadError as e:
            QMessageBox.critical(self, "Load Error", str(e))
            return
        self._frame = frame
        self._frame_index = idx
        self._total_frames = total
        h, w = frame.shape[:2]
        self.lbl_frame_info.setText(f"Frame: {idx} / {max(0, total - 1)}  ({w}×{h})")
        self.canvas.set_frame(frame)
        self.spin_cutoff.setMaximum(h - 1)
        # Keep cutoff if still in range
        cy = self.canvas.cutoff_y()
        if cy is not None and cy < h:
            self.canvas.set_cutoff_y(cy)
        else:
            self.canvas.set_cutoff_y(None)

    def _on_set_reference_frame(self) -> None:
        if self._current_sample is None:
            return
        # Stored in memory; persisted on save cutoff
        self._status(f"Reference frame set to {self._frame_index} (save annotation to persist)")

    def on_cutoff_changed(self, y: int) -> None:
        self.spin_cutoff.blockSignals(True)
        self.spin_cutoff.setValue(y)
        self.spin_cutoff.blockSignals(False)

    def _on_cutoff_spin(self, y: int) -> None:
        self.canvas.set_cutoff_y(y)

    def _on_clear_cutoff(self) -> None:
        self.canvas.set_cutoff_y(None)

    def _on_save_cutoff(self) -> None:
        if self._project_root is None or self._current_sample is None or self._frame is None:
            QMessageBox.warning(self, "Save", "Load a sample and set a cutoff line first.")
            return

        cutoff = self.canvas.cutoff_y()
        if cutoff is None:
            QMessageBox.warning(
                self,
                "Save",
                "Place a horizontal cutoff line on the preview before saving.",
            )
            return

        h, w = int(self._frame.shape[0]), int(self._frame.shape[1])
        sid = str(self._current_sample["sample_id"])
        notes = self.txt_notes.toPlainText().strip()

        annotation = build_cutoff_annotation(
            sample_id=sid,
            group=str(self._current_sample["group"]),
            original_file=str(self._current_sample["original_filename"]),
            stored_raw_path=str(self._current_sample["stored_path"]),
            reference_frame_index=int(self._frame_index),
            cutoff_y=int(cutoff),
            image_width=w,
            image_height=h,
            notes=notes,
        )

        crop_path = self._project_root / METADATA_DIR / CROP_METADATA_JSON
        try:
            save_sample_crop_annotation(crop_path, sid, annotation)
            update_samples_csv(
                self._project_root / METADATA_DIR / SAMPLES_CSV,
                {
                    "sample_id": sid,
                    "processing_status": "cutoff_marked",
                    "notes": notes,
                },
            )
            self._refresh_sample_list()
            self._status(f"Saved cutoff annotation for {sid} (y={cutoff})")
            QMessageBox.information(
                self,
                "Saved",
                f"Cutoff annotation saved for {sid}.\n"
                f"Analysis region: y = 0 … {cutoff}\n"
                f"Excluded region: y = {cutoff} … {h}",
            )
        except (OSError, TypeError, ValueError) as e:
            QMessageBox.critical(self, "Save Error", str(e))
        except Exception as e:
            QMessageBox.critical(
                self,
                "Save Error",
                f"Could not save annotation:\n{e}",
            )


def run_app() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("ActinTrackCV")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
