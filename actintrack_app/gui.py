"""PyQt6 GUI for ActinTrackCV 2D tracking setup."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PyQt6.QtCore import Qt
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
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from actintrack_app.file_importer import import_files
from actintrack_app.image_processing import TrackingCrop, detect_tracking_crop
from actintrack_app.metadata import (
    build_cutoff_annotation,
    load_crop_metadata,
    remove_samples_from_metadata,
    save_sample_crop_annotation,
    sync_samples_with_disk,
    update_samples_csv,
)
from actintrack_app.project_manager import create_project_structure, is_valid_project
from actintrack_app.utils import (
    CROP_METADATA_JSON,
    GROUPS,
    GROUP_WT,
    METADATA_DIR,
    RAW_DIR,
    SAMPLES_CSV,
    is_supported_file,
)
from actintrack_app.video_processing import MediaLoadError, load_media_frame


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = APP_ROOT / "raw_source"
MEDIA_FILE_FILTER = (
    "Microscopy files (*.avi *.mp4 *.tif *.tiff *.oib *.oif *.oir *.png *.jpg *.jpeg);;"
    "All Files (*)"
)
AUTO_APPLY_ROI_CONFIDENCE = 0.15


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
    """Displays frame with draggable horizontal biological cutoff line."""

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
                "Tracking ROI (above line)",
            )
            painter.setPen(QColor(255, 160, 100))
            painter.drawText(
                self._offset_x + 8,
                min(sy + 20, self._offset_y + scaled.height() - 8),
                "Excluded lower perinuclear region",
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
        self.setWindowTitle("ActinTrackCV - 2D Tracking Setup")
        self.resize(1280, 800)

        self._project_root: Optional[Path] = None
        self._current_sample: Optional[dict] = None
        self._frame: Optional[np.ndarray] = None
        self._frame_index = 0
        self._total_frames = 1
        self._tracking_crop: Optional[TrackingCrop] = None
        self._import_group = GROUP_WT
        self._workspace_root = APP_ROOT
        self._default_source_root = (
            DEFAULT_SOURCE_ROOT if DEFAULT_SOURCE_ROOT.exists() else self._workspace_root
        )
        self._last_import_dir = self._default_source_root

        self._build_ui()
        self._load_project(self._workspace_root, "Workspace project loaded")

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        tabs = QTabWidget()
        tracking_tab = QWidget()
        tracking_layout = QHBoxLayout(tracking_tab)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Left panel ---
        left = QWidget()
        left_layout = QVBoxLayout(left)

        proj_box = QGroupBox("Workspace")
        proj_layout = QVBoxLayout(proj_box)
        self.btn_use_workspace = QPushButton("Use ActinTrackCV Workspace")
        self.btn_use_workspace.clicked.connect(self._on_use_workspace_project)
        self.btn_open_project = QPushButton("Choose Different Project Folder…")
        self.btn_open_project.clicked.connect(self._on_select_project)
        self.lbl_project = QLabel("No project loaded")
        self.lbl_project.setWordWrap(True)
        proj_layout.addWidget(self.btn_use_workspace)
        proj_layout.addWidget(self.btn_open_project)
        proj_layout.addWidget(self.lbl_project)
        left_layout.addWidget(proj_box)

        import_box = QGroupBox("Import Source Data")
        import_layout = QVBoxLayout(import_box)
        import_help = QLabel(
            "Imports copy source files into the project workspace. "
            "Original files stay in place."
        )
        import_help.setWordWrap(True)
        self.combo_import_group = QComboBox()
        self.combo_import_group.addItems(list(GROUPS))
        self.combo_import_group.currentTextChanged.connect(self._update_path_labels)
        self.lbl_import_destination = QLabel("Destination: —")
        self.lbl_import_destination.setWordWrap(True)
        self.lbl_import_destination.setStyleSheet("color: #888;")
        self.btn_import = QPushButton("Import Files to Selected Group…")
        self.btn_import.clicked.connect(self._on_import_files)
        self.btn_import.setEnabled(False)
        self.btn_import_folder = QPushButton("Import raw_source Folder by Group…")
        self.btn_import_folder.clicked.connect(self._on_import_source_folder)
        self.btn_import_folder.setEnabled(False)
        import_layout.addWidget(import_help)
        import_layout.addWidget(QLabel("Assign to group:"))
        import_layout.addWidget(self.combo_import_group)
        import_layout.addWidget(self.lbl_import_destination)
        import_layout.addWidget(self.btn_import)
        import_layout.addWidget(self.btn_import_folder)
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

        selected_box = QGroupBox("Selected File")
        selected_layout = QVBoxLayout(selected_box)
        self.lbl_selected_file = QLabel("No sample selected")
        self.lbl_selected_file.setWordWrap(True)
        self.lbl_selected_file.setStyleSheet("color: #888;")
        selected_layout.addWidget(self.lbl_selected_file)
        right_layout.addWidget(selected_box)

        roi_box = QGroupBox("Tracking ROI Detection")
        roi_layout = QVBoxLayout(roi_box)
        roi_label = QLabel(
            "Detects the upper/central filament tracking region from actin "
            "foreground, row-wise signal mass, and the gradient into the lower "
            "perinuclear region."
        )
        roi_label.setWordWrap(True)
        self.lbl_roi_info = QLabel("ROI detector: no frame loaded")
        self.lbl_roi_info.setWordWrap(True)
        self.lbl_roi_info.setStyleSheet("color: #888;")
        self.btn_auto_detect_roi = QPushButton("Auto Detect Tracking ROI")
        self.btn_auto_detect_roi.clicked.connect(self._on_auto_detect_roi)
        self.btn_auto_detect_roi.setEnabled(False)
        roi_layout.addWidget(roi_label)
        roi_layout.addWidget(self.btn_auto_detect_roi)
        roi_layout.addWidget(self.lbl_roi_info)
        right_layout.addWidget(roi_box)

        cutoff_box = QGroupBox("Tracking Region Cutoff")
        cutoff_layout = QVBoxLayout(cutoff_box)
        cutoff_layout.addWidget(
            QLabel(
                "Use auto-detect or manually draw a horizontal line. Everything "
                "above the line is kept for 2D velocity tracking."
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
            "2D focus: import, preview, signal ROI detection, and cutoff review.\n"
            "Tracking export is next; 3D stack metrics stay separate."
        )
        phase_label.setWordWrap(True)
        phase_label.setStyleSheet("color: #888;")
        right_layout.addWidget(phase_label)
        right_layout.addStretch()

        splitter.addWidget(right)
        splitter.setSizes([280, 720, 280])

        tracking_layout.addWidget(splitter)
        tabs.addTab(tracking_tab, "2D Tracking")
        tabs.addTab(self._build_3d_tab(), "3D Analysis (Future)")
        layout.addWidget(tabs)
        self.setStatusBar(QStatusBar())

    def _build_3d_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        info_box = QGroupBox("3D Analysis (Future Milestone)")
        info_layout = QVBoxLayout(info_box)
        label = QLabel(
            "Reserved for .tif stack thickness and depth-profile analysis. "
            "This module stays decoupled while the 2D A/B velocity tracking "
            "pipeline is built first."
        )
        label.setWordWrap(True)
        info_layout.addWidget(label)

        disabled = QLabel(
            "No 3D processing controls are active yet. Use the 2D Tracking tab "
            "for import, preview, signal ROI detection, and cutoff annotation."
        )
        disabled.setWordWrap(True)
        disabled.setStyleSheet("color: #888;")
        info_layout.addWidget(disabled)

        layout.addWidget(info_box)
        layout.addStretch()
        return tab

    def _status(self, msg: str) -> None:
        self.statusBar().showMessage(msg)
        self.lbl_status.setText(f"Status: {msg}")

    def _load_project(self, root: Path, status_msg: str) -> None:
        try:
            root = Path(root).resolve()
            if not is_valid_project(root):
                create_project_structure(root)
            self._project_root = root
            self.btn_import.setEnabled(True)
            self.btn_import_folder.setEnabled(True)
            self.btn_refresh_samples.setEnabled(True)
            self._update_path_labels()
            self._refresh_sample_list()
            self._status(f"{status_msg}: {root}")
        except OSError as e:
            QMessageBox.critical(self, "Project Error", f"Could not set up project:\n{e}")

    def _update_path_labels(self) -> None:
        if self._project_root is None:
            self.lbl_project.setText("No project loaded")
            self.lbl_import_destination.setText("Destination: —")
            return

        group = self.combo_import_group.currentText()
        raw_root = self._project_root / RAW_DIR
        metadata_path = self._project_root / METADATA_DIR / SAMPLES_CSV
        selected_dest = raw_root / group
        source_hint = self._default_source_root

        self.lbl_project.setText(
            "Project root:\n"
            f"{self._project_root}\n\n"
            "Imported copies:\n"
            f"{raw_root}\n\n"
            "Sample metadata:\n"
            f"{metadata_path}\n\n"
            "Default source folder:\n"
            f"{source_hint}"
        )
        self.lbl_import_destination.setText(
            "Destination for selected group:\n"
            f"{selected_dest}"
        )

    def _default_import_dir(self) -> Path:
        if self._last_import_dir.exists():
            return self._last_import_dir
        if self._default_source_root.exists():
            return self._default_source_root
        if self._project_root is not None:
            return self._project_root
        return Path.home()

    def _on_use_workspace_project(self) -> None:
        self._load_project(self._workspace_root, "Workspace project loaded")

    def _confirm_project_root_if_source_folder(self, root: Path) -> Optional[Path]:
        raw_source = DEFAULT_SOURCE_ROOT.resolve()
        root = root.resolve()
        if root != raw_source:
            return root

        reply = QMessageBox.question(
            self,
            "Use Workspace Instead?",
            "The selected folder is raw_source, which should stay as the source-data "
            "folder.\n\nUse the ActinTrackCV workspace as the project root instead?\n\n"
            f"Project root: {self._workspace_root}\n"
            f"Source data: {raw_source}",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            return self._workspace_root
        if reply == QMessageBox.StandardButton.No:
            return root
        return None

    def _collect_grouped_source_files(self, source_root: Path) -> dict[str, list[Path]]:
        grouped: dict[str, list[Path]] = {}
        for group in GROUPS:
            group_dir = source_root / group
            if not group_dir.is_dir():
                continue
            files = [
                path
                for path in sorted(group_dir.iterdir())
                if path.is_file() and is_supported_file(path)
            ]
            if files:
                grouped[group] = files
        return grouped

    def _confirm_import(self, paths: list[str | Path], group: str) -> bool:
        if self._project_root is None:
            return False
        dest = self._project_root / RAW_DIR / group
        examples = "\n".join(f"• {Path(path).name}" for path in paths[:8])
        if len(paths) > 8:
            examples += f"\n• … {len(paths) - 8} more"
        reply = QMessageBox.question(
            self,
            "Confirm Import",
            f"Copy {len(paths)} file(s) into the project workspace?\n\n"
            f"Destination:\n{dest}\n\n"
            f"Source file examples:\n{examples}\n\n"
            "Original source files will not be modified.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _show_import_results(
        self,
        created: list[dict],
        *,
        requested_count: int,
        destination_hint: Path | None = None,
    ) -> None:
        if not created:
            QMessageBox.information(
                self,
                "Import",
                "No files were imported. Check that the selected source contains "
                "supported microscopy files.",
            )
            return

        examples = []
        for record in created[:8]:
            src = Path(str(record.get("source_path", record["original_filename"]))).name
            examples.append(f"• {src} -> {record['stored_path']}")
        if len(created) > 8:
            examples.append(f"• … {len(created) - 8} more")

        dest_text = f"\n\nDestination:\n{destination_hint}" if destination_hint else ""
        QMessageBox.information(
            self,
            "Import Complete",
            f"Imported {len(created)} of {requested_count} selected file(s)."
            f"{dest_text}\n\n"
            + "\n".join(examples),
        )

    def _apply_tracking_crop(self, crop: TrackingCrop) -> None:
        self._tracking_crop = crop
        self.canvas.set_cutoff_y(crop.cutoff_y)
        self.spin_cutoff.blockSignals(True)
        self.spin_cutoff.setValue(crop.cutoff_y)
        self.spin_cutoff.blockSignals(False)
        self.lbl_roi_info.setText(
            f"Detected cutoff y={crop.cutoff_y}; ROI "
            f"x={crop.x0}..{crop.x1}, y={crop.y0}..{crop.y1}; "
            f"confidence={crop.confidence:.2f}; signal={crop.signal_source}"
        )

    def _detect_tracking_crop_for_current_frame(self, *, show_error: bool) -> Optional[TrackingCrop]:
        if self._frame is None:
            return None
        try:
            return detect_tracking_crop(self._frame)
        except ValueError as e:
            self._tracking_crop = None
            self.lbl_roi_info.setText(f"ROI detector unavailable: {e}")
            if show_error:
                QMessageBox.warning(self, "ROI Detection", str(e))
            return None

    def _on_auto_detect_roi(self) -> None:
        crop = self._detect_tracking_crop_for_current_frame(show_error=True)
        if crop is not None:
            self._apply_tracking_crop(crop)
            if crop.confidence < AUTO_APPLY_ROI_CONFIDENCE:
                self._status(
                    f"Low-confidence ROI cutoff y={crop.cutoff_y}; review manually."
                )
            else:
                self._status(f"Auto-detected tracking ROI cutoff y={crop.cutoff_y}")

    def _on_select_project(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose ActinTrackCV Project Workspace",
            str(self._workspace_root),
        )
        if not folder:
            return
        root = self._confirm_project_root_if_source_folder(Path(folder))
        if root is None:
            return
        self._load_project(root, "Project loaded")

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
                if self._project_root is not None:
                    item.setToolTip(str(self._project_root / str(row["stored_path"])))
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
            self.lbl_selected_file.setText("No sample selected")
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
            "Select Source Files to Copy Into Project",
            str(self._default_import_dir()),
            MEDIA_FILE_FILTER,
        )
        if not paths:
            return

        self._last_import_dir = Path(paths[0]).parent
        group = self.combo_import_group.currentText()
        if not self._confirm_import(paths, group):
            return

        try:
            created = import_files(paths, group, self._project_root)
            self._refresh_sample_list()
            destination = self._project_root / RAW_DIR / group
            self._show_import_results(
                created,
                requested_count=len(paths),
                destination_hint=destination,
            )
            self._status(f"Imported {len(created)} file(s) into {destination}")
        except (FileNotFoundError, ValueError, OSError) as e:
            QMessageBox.critical(self, "Import Failed", str(e))

    def _on_import_source_folder(self) -> None:
        if self._project_root is None:
            QMessageBox.warning(self, "Import", "Load a project workspace first.")
            return

        folder = QFileDialog.getExistingDirectory(
            self,
            "Select raw_source Folder",
            str(self._default_source_root),
        )
        if not folder:
            return

        source_root = Path(folder).resolve()
        grouped = self._collect_grouped_source_files(source_root)
        if not grouped:
            QMessageBox.warning(
                self,
                "Import Source Folder",
                "No supported files were found in group folders under:\n"
                f"{source_root}\n\n"
                "Expected folders like 1_WT_218, 2_WT_550, 3_Mutant_515, "
                "or 4_Mutant_175.",
            )
            return

        summary_lines = []
        total = 0
        for group, files in grouped.items():
            total += len(files)
            summary_lines.append(
                f"• {group}: {len(files)} file(s) -> "
                f"{self._project_root / RAW_DIR / group}"
            )

        reply = QMessageBox.question(
            self,
            "Confirm Grouped Import",
            f"Copy {total} file(s) from:\n{source_root}\n\n"
            f"Into project:\n{self._project_root}\n\n"
            + "\n".join(summary_lines)
            + "\n\nOriginal source files will not be modified.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        created: list[dict] = []
        try:
            for group, files in grouped.items():
                created.extend(import_files(files, group, self._project_root))
            self._last_import_dir = source_root
            self._refresh_sample_list()
            self._show_import_results(created, requested_count=total)
            self._status(f"Imported {len(created)} file(s) from {source_root}")
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
            self.lbl_selected_file.setText(
                "Missing copied file:\n"
                f"{self._project_root / str(data.get('stored_path', ''))}"
            )
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
        self.lbl_selected_file.setText(
            f"Sample: {self._current_sample['sample_id']}\n"
            f"Original: {self._current_sample['original_filename']}\n\n"
            "Copied project file:\n"
            f"{path}\n\n"
            f"Stored path: {self._current_sample['stored_path']}"
        )
        self.canvas.set_frame(frame)
        self.btn_auto_detect_roi.setEnabled(True)

        self.spin_cutoff.setMaximum(h - 1)
        restored = self._restore_cutoff_from_metadata()
        if not restored:
            crop = self._detect_tracking_crop_for_current_frame(show_error=False)
            if crop is not None and crop.confidence >= AUTO_APPLY_ROI_CONFIDENCE:
                self._apply_tracking_crop(crop)
            elif crop is not None:
                self.lbl_roi_info.setText(
                    f"Low-confidence detector result y={crop.cutoff_y} "
                    f"(confidence={crop.confidence:.2f}). Press Auto Detect to "
                    "review/apply or set the cutoff manually."
                )
        self.btn_save_cutoff.setEnabled(True)
        self._status(f"Loaded {self._current_sample['sample_id']}")

    def _restore_cutoff_from_metadata(self) -> bool:
        if self._project_root is None or self._current_sample is None:
            return False
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
            auto_roi = ann.get("tracking_roi")
            if isinstance(auto_roi, dict):
                self.lbl_roi_info.setText(
                    f"Loaded saved ROI cutoff y={y}; "
                    f"method={auto_roi.get('method', 'unknown')}"
                )
            else:
                self.lbl_roi_info.setText(f"Loaded saved manual cutoff y={y}")
            return True
        else:
            self.canvas.set_cutoff_y(None)
            self.spin_cutoff.setValue(0)
            self.lbl_roi_info.setText("ROI detector: no saved cutoff")
            return False

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
        cy = self.canvas.cutoff_y()
        self.canvas.set_frame(frame)
        self.btn_auto_detect_roi.setEnabled(True)
        self.spin_cutoff.setMaximum(h - 1)
        # Keep cutoff if still in range
        if cy is not None and cy < h:
            self.canvas.set_cutoff_y(cy)
        else:
            crop = self._detect_tracking_crop_for_current_frame(show_error=False)
            if crop is not None and crop.confidence >= AUTO_APPLY_ROI_CONFIDENCE:
                self._apply_tracking_crop(crop)
            elif crop is not None:
                self.lbl_roi_info.setText(
                    f"Low-confidence detector result y={crop.cutoff_y} "
                    f"(confidence={crop.confidence:.2f}). Press Auto Detect to "
                    "review/apply or set the cutoff manually."
                )
                self.canvas.set_cutoff_y(None)
            else:
                self.canvas.set_cutoff_y(None)

    def _on_set_reference_frame(self) -> None:
        if self._current_sample is None:
            return
        # Stored in memory; persisted on save cutoff
        self._status(f"Reference frame set to {self._frame_index} (save annotation to persist)")

    def on_cutoff_changed(self, y: int) -> None:
        self._tracking_crop = None
        self.lbl_roi_info.setText(f"Manual cutoff y={y}")
        self.spin_cutoff.blockSignals(True)
        self.spin_cutoff.setValue(y)
        self.spin_cutoff.blockSignals(False)

    def _on_cutoff_spin(self, y: int) -> None:
        self._tracking_crop = None
        self.lbl_roi_info.setText(f"Manual cutoff y={y}")
        self.canvas.set_cutoff_y(y)

    def _on_clear_cutoff(self) -> None:
        self._tracking_crop = None
        self.lbl_roi_info.setText("ROI detector: cutoff cleared")
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
            tracking_roi=self._tracking_crop.as_dict() if self._tracking_crop else None,
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
            if self._tracking_crop is not None:
                saved_detail = (
                    f"Tracking ROI: x = {self._tracking_crop.x0} … {self._tracking_crop.x1}, "
                    f"y = {self._tracking_crop.y0} … {self._tracking_crop.y1}\n"
                    f"Detector confidence: {self._tracking_crop.confidence:.2f}"
                )
            else:
                saved_detail = (
                    f"Manual tracking region: y = 0 … {cutoff}\n"
                    f"Excluded region: y = {cutoff} … {h}"
                )
            QMessageBox.information(
                self,
                "Saved",
                f"Cutoff annotation saved for {sid}.\n"
                f"{saved_detail}",
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
