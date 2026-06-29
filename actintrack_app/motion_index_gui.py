"""GUI dialogs for single-sample F-actin motion-index analysis."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cv2
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from actintrack_app.export_naming import motion_index_track_preview_path
from actintrack_app.gui_canvas import numpy_bgr_to_qimage
from actintrack_app.motion_index import (
    MotionIndexParams,
    MotionIndexResult,
    ProcessedInputOption,
    TRACKING_METHOD_BRIGHTEST_LOCAL,
    TRACKING_METHOD_TEMPLATE,
    discover_processed_inputs,
    run_motion_index_analysis,
    update_workspace_motion_index_summary,
)
from actintrack_app.project_manager import get_processed_batch_dir
from actintrack_app.utils import (
    METADATA_DIR,
    SAMPLES_CSV,
    STATUS_MOTION_INDEX_FAILED,
    STATUS_MOTION_INDEX_GENERATED,
)

if TYPE_CHECKING:
    from actintrack_app.gui import MainWindow

DEFAULT_PREVIEW_FPS = 5.0


class MotionIndexSettingsDialog(QDialog):
    """Editable parameters before running draft motion-index analysis."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("F-actin Motion Index Settings")
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Bright-point motion index on the processed cropped ROI. Absolute "
            "movement is the primary metric; downward motion is also reported."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        defaults = MotionIndexParams()
        form = QFormLayout()
        self.combo_method = QComboBox()
        self.combo_method.addItem(
            "Brightest nearby points",
            TRACKING_METHOD_BRIGHTEST_LOCAL,
        )
        self.combo_method.addItem("Template matching", TRACKING_METHOD_TEMPLATE)
        method_index = self.combo_method.findData(defaults.tracking_method)
        self.combo_method.setCurrentIndex(max(0, method_index))
        self.spin_points = QSpinBox()
        self.spin_points.setRange(1, 50)
        self.spin_points.setValue(defaults.num_starting_points)
        self.spin_spacing = QSpinBox()
        self.spin_spacing.setRange(1, 200)
        self.spin_spacing.setValue(defaults.min_point_spacing_px)
        self.spin_search = QSpinBox()
        self.spin_search.setRange(1, 100)
        self.spin_search.setValue(defaults.search_radius_px)
        self.spin_patch = QSpinBox()
        self.spin_patch.setRange(3, 101)
        self.spin_patch.setSingleStep(2)
        self.spin_patch.setValue(defaults.template_patch_size_px)
        self.spin_confidence = QDoubleSpinBox()
        self.spin_confidence.setRange(0.0, 1.0)
        self.spin_confidence.setDecimals(2)
        self.spin_confidence.setSingleStep(0.05)
        self.spin_confidence.setValue(defaults.min_template_confidence)
        self.spin_lookahead = QSpinBox()
        self.spin_lookahead.setRange(0, 3)
        self.spin_lookahead.setValue(defaults.lookahead_frames)
        self.spin_mpp = QDoubleSpinBox()
        self.spin_mpp.setRange(0.001, 10.0)
        self.spin_mpp.setDecimals(4)
        self.spin_mpp.setValue(defaults.microns_per_pixel)
        self.spin_spf = QDoubleSpinBox()
        self.spin_spf.setRange(0.001, 60.0)
        self.spin_spf.setDecimals(4)
        self.spin_spf.setValue(defaults.seconds_per_frame)
        self.combo_direction = QComboBox()
        self.combo_direction.addItem("increasing_y (downward)", "increasing_y")

        form.addRow("Tracking method:", self.combo_method)
        form.addRow("Starting points:", self.spin_points)
        form.addRow("Min point spacing (px):", self.spin_spacing)
        form.addRow("Search radius (px):", self.spin_search)
        form.addRow("Template patch size (px, odd):", self.spin_patch)
        form.addRow("Min match confidence:", self.spin_confidence)
        form.addRow("Lookahead frames:", self.spin_lookahead)
        form.addRow("Microns per pixel:", self.spin_mpp)
        form.addRow("Seconds per frame:", self.spin_spf)
        form.addRow("Downward direction:", self.combo_direction)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._try_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _try_accept(self) -> None:
        patch = int(self.spin_patch.value())
        if patch % 2 == 0:
            QMessageBox.warning(
                self,
                "Invalid Patch Size",
                "Template patch size must be an odd integer.",
            )
            return
        self.accept()

    def params(self) -> MotionIndexParams:
        return MotionIndexParams(
            num_starting_points=int(self.spin_points.value()),
            min_point_spacing_px=int(self.spin_spacing.value()),
            search_radius_px=int(self.spin_search.value()),
            template_patch_size_px=int(self.spin_patch.value()),
            min_template_confidence=float(self.spin_confidence.value()),
            lookahead_frames=int(self.spin_lookahead.value()),
            microns_per_pixel=float(self.spin_mpp.value()),
            seconds_per_frame=float(self.spin_spf.value()),
            downward_direction=str(self.combo_direction.currentData()),
            tracking_method=str(
                self.combo_method.currentData() or TRACKING_METHOD_BRIGHTEST_LOCAL
            ),
        )


class ProcessedInputChoiceDialog(QDialog):
    def __init__(self, parent: QWidget, options: list[ProcessedInputOption]):
        super().__init__(parent)
        self.setWindowTitle("Choose Processed ROI Input")
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Multiple processed ROI outputs were found. Choose one:")
        )
        self.list_options = QListWidget()
        for opt in options:
            self.list_options.addItem(opt.label)
        self.list_options.setCurrentRow(0)
        layout.addWidget(self.list_options)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._options = options

    def selected_option(self) -> ProcessedInputOption | None:
        row = self.list_options.currentRow()
        if row < 0 or row >= len(self._options):
            return None
        return self._options[row]


class MotionIndexCompleteDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        result: MotionIndexResult,
        *,
        starting_points_warning: str = "",
        preview_warning: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle("F-actin Motion Index Complete")
        self._result = result
        layout = QVBoxLayout(self)

        lines = [
            "F-actin Motion Index Complete",
            "",
            f"Absolute Velocity Index: {result.general_movement_index_um_per_s:.4f} µm/sec",
            f"Downward Velocity Index: {result.downward_velocity_index_um_per_s:.4f} µm/sec",
            f"Tracks Started: {len(result.tracks)}",
            f"Tracks with Valid Steps: {result.num_tracks_with_valid_steps}",
            f"Total Valid Steps: {result.total_valid_steps}",
            f"Mean Track Length: {result.mean_track_length_frames:.2f} frames",
            "",
            "Outputs saved to:",
            result.output_dir,
        ]
        if starting_points_warning:
            lines.extend(["", starting_points_warning])
        if preview_warning:
            lines.extend(["", preview_warning])

        body = QLabel("\n".join(lines))
        body.setWordWrap(True)
        layout.addWidget(body)

        btn_row = QHBoxLayout()
        self.btn_folder = QPushButton("Open Output Folder")
        self.btn_folder.clicked.connect(self._open_folder)
        self.btn_preview = QPushButton("Open Track Preview")
        self.btn_preview.clicked.connect(self._open_preview)
        self.btn_csv = QPushButton("Open Trajectory CSV")
        self.btn_csv.clicked.connect(self._open_csv)
        btn_row.addWidget(self.btn_folder)
        btn_row.addWidget(self.btn_preview)
        btn_row.addWidget(self.btn_csv)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        close_row = QHBoxLayout()
        close_row.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        close_row.addWidget(btn_close)
        layout.addLayout(close_row)

        has_preview = bool(result.track_preview_video) and Path(
            result.track_preview_video
        ).is_file()
        self.btn_preview.setEnabled(has_preview)

    def _open_folder(self) -> None:
        folder = Path(self._result.output_dir)
        if not folder.is_dir():
            QMessageBox.warning(self, "Open Folder", f"Folder not found:\n{folder}")
            return
        if not _open_path_with_system(folder):
            QMessageBox.warning(self, "Open Folder", f"Could not open folder:\n{folder}")

    def _open_preview(self) -> None:
        path = Path(self._result.track_preview_video)
        if not path.is_file():
            QMessageBox.warning(self, "Track Preview", f"Preview not found:\n{path}")
            return
        open_track_preview_dialog(self.parent(), path)

    def _open_csv(self) -> None:
        path = Path(self._result.trajectory_csv)
        if not path.is_file():
            QMessageBox.warning(self, "Trajectory CSV", f"CSV not found:\n{path}")
            return
        if not _open_path_with_system(path):
            QMessageBox.warning(self, "Trajectory CSV", f"Could not open:\n{path}")


class TrackPreviewDialog(QDialog):
    """In-app playback for a generated track-preview MP4."""

    def __init__(self, parent: QWidget | None, video_path: Path):
        super().__init__(parent)
        self.setWindowTitle(f"Track Preview — {video_path.name}")
        self.resize(760, 580)
        self._path = Path(video_path)
        self._cap = cv2.VideoCapture(str(self._path))
        if not self._cap.isOpened():
            self._cap.release()
            raise OSError(f"Cannot open track preview data file: {self._path}")

        self._frame_count = max(1, int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT)))
        self._fps = max(1.0, float(self._cap.get(cv2.CAP_PROP_FPS)) or DEFAULT_PREVIEW_FPS)
        self._index = 0
        self._playing = False

        layout = QVBoxLayout(self)
        self.lbl_image = QLabel("Loading…")
        self.lbl_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_image.setMinimumSize(480, 360)
        self.lbl_image.setStyleSheet("background-color: #1e1e1e; border: 1px solid #444;")
        layout.addWidget(self.lbl_image, stretch=1)

        self.lbl_frame = QLabel()
        layout.addWidget(self.lbl_frame)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(max(0, self._frame_count - 1))
        self.slider.valueChanged.connect(self._on_slider)
        layout.addWidget(self.slider)

        controls = QHBoxLayout()
        self.btn_play = QPushButton("Play")
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.clicked.connect(self._pause)
        controls.addWidget(self.btn_play)
        controls.addWidget(self.btn_pause)
        controls.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        controls.addWidget(btn_close)
        layout.addLayout(controls)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance_frame)
        self._show_frame(0)

    def closeEvent(self, event) -> None:
        self._release()
        super().closeEvent(event)

    def accept(self) -> None:
        self._release()
        super().accept()

    def reject(self) -> None:
        self._release()
        super().reject()

    def _release(self) -> None:
        self._timer.stop()
        if self._cap is not None:
            self._cap.release()

    def _playback_interval_ms(self) -> int:
        return max(20, int(1000.0 / self._fps))

    def _toggle_play(self) -> None:
        if self._playing:
            self._pause()
        else:
            self._playing = True
            self._timer.start(self._playback_interval_ms())

    def _pause(self) -> None:
        self._playing = False
        self._timer.stop()

    def _advance_frame(self) -> None:
        if self._index >= self._frame_count - 1:
            self._pause()
            return
        self._show_frame(self._index + 1)

    def _on_slider(self, value: int) -> None:
        if self._playing:
            self._pause()
        self._show_frame(value)

    def _show_frame(self, index: int) -> None:
        index = max(0, min(index, self._frame_count - 1))
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = self._cap.read()
        if not ok or frame is None:
            QMessageBox.warning(self, "Track Preview", f"Cannot read frame {index}.")
            self._pause()
            return

        self._index = index
        self.slider.blockSignals(True)
        self.slider.setValue(index)
        self.slider.blockSignals(False)

        qimg = numpy_bgr_to_qimage(frame)
        pix = QPixmap.fromImage(qimg)
        scaled = pix.scaled(
            self.lbl_image.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.lbl_image.setPixmap(scaled)
        self.lbl_frame.setText(
            f"Frame {index + 1} / {self._frame_count}  ({self._path.name})"
        )


def open_track_preview_dialog(parent: QWidget | None, video_path: Path) -> None:
    path = Path(video_path)
    if not path.is_file():
        QMessageBox.warning(parent, "Track Preview", f"Preview not found:\n{path}")
        return
    try:
        dlg = TrackPreviewDialog(parent, path)
        dlg.exec()
    except OSError as exc:
        QMessageBox.warning(
            parent,
            "Track Preview",
            f"Could not open in-app preview:\n{exc}\n\n"
            "Trying the system default media player instead.",
        )
        _open_path_with_system(path)


def _open_path_with_system(path: Path) -> bool:
    path = Path(path)
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
            return True
        if sys.platform.startswith("win"):
            import os

            os.startfile(str(path))  # type: ignore[attr-defined]
            return True
        subprocess.run(["xdg-open", str(path)], check=False)
        return True
    except OSError:
        return False


def resolve_processed_input(
    parent: QWidget,
    options: list[ProcessedInputOption],
) -> ProcessedInputOption | None:
    if not options:
        return None
    if len(options) == 1:
        return options[0]
    dlg = ProcessedInputChoiceDialog(parent, options)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return dlg.selected_option()


def find_existing_track_preview(
    root: Path,
    sample_row: dict[str, Any],
) -> Path | None:
    group = str(sample_row.get("group", ""))
    batch_name = str(sample_row.get("batch_name", ""))
    final_name = str(sample_row.get("final_export_name", "")).strip()
    if not group or not batch_name or not final_name:
        return None
    path = motion_index_track_preview_path(
        get_processed_batch_dir(root, group, batch_name),
        final_name,
    )
    return path if path.is_file() else None


def run_motion_index_for_sample(
    window: "MainWindow",
    *,
    show_settings: bool = True,
) -> MotionIndexResult | None:
    """GUI workflow: settings -> analyze one selected processed sample."""
    from actintrack_app.metadata import update_samples_csv

    if window._current_sample is None:
        QMessageBox.information(
            window,
            "F-actin Motion Index",
            "Please select a processed sample first.",
        )
        return None

    if window._project_root is None:
        QMessageBox.warning(window, "F-actin Motion Index", "No workspace loaded.")
        return None

    sample = window._current_sample
    options = discover_processed_inputs(window._project_root, sample)
    if not options:
        QMessageBox.information(
            window,
            "F-actin Motion Index",
            "Please process/export the ROI before generating the F-actin motion index.",
        )
        return None

    selected = resolve_processed_input(window, options)
    if selected is None:
        return None

    params: MotionIndexParams | None = None
    if show_settings:
        settings = MotionIndexSettingsDialog(window)
        if settings.exec() != QDialog.DialogCode.Accepted:
            return None
        params = settings.params()

    final_name = str(sample.get("final_export_name", "")).strip()
    group = str(sample.get("group", ""))
    batch_name = str(sample.get("batch_name", ""))
    sample_id = str(sample.get("sample_id", ""))
    out_dir = get_processed_batch_dir(window._project_root, group, batch_name)

    window._status("Running F-actin motion index…")
    QApplication.processEvents()

    starting_warning = ""
    try:
        result = run_motion_index_analysis(
            selected.path,
            output_dir=out_dir,
            final_export_name=final_name,
            sample_id=sample_id,
            params=params,
            preview_fps=DEFAULT_PREVIEW_FPS,
            frame_paths=list(selected.frame_paths) if selected.frame_paths else None,
        )
        requested = (params or MotionIndexParams()).num_starting_points
        if len(result.tracks) < requested:
            starting_warning = (
                f"Note: only {len(result.tracks)} starting point(s) were found "
                f"(requested {requested})."
            )

        update_workspace_motion_index_summary(
            window._project_root,
            result,
            group=group,
            batch_name=batch_name,
        )

        samples_path = window._project_root / METADATA_DIR / SAMPLES_CSV
        update_samples_csv(
            samples_path,
            {"sample_id": sample_id, "processing_status": STATUS_MOTION_INDEX_GENERATED},
        )
        sample["processing_status"] = STATUS_MOTION_INDEX_GENERATED
        window._refresh_sample_list()

        preview_warning = ""
        if result.track_preview_error:
            preview_warning = (
                "Track preview data file could not be written:\n"
                f"{result.track_preview_error}"
            )

        window._last_motion_index_result = result
        window._status("F-actin motion index complete.")
        if hasattr(window, "update_tracking_result_panel"):
            window.update_tracking_result_panel(sample_id)
        dlg = MotionIndexCompleteDialog(
            window,
            result,
            starting_points_warning=starting_warning,
            preview_warning=preview_warning,
        )
        dlg.exec()
        return result
    except Exception as exc:
        samples_path = window._project_root / METADATA_DIR / SAMPLES_CSV
        update_samples_csv(
            samples_path,
            {"sample_id": sample_id, "processing_status": STATUS_MOTION_INDEX_FAILED},
        )
        sample["processing_status"] = STATUS_MOTION_INDEX_FAILED
        window._refresh_sample_list()
        QMessageBox.critical(
            window,
            "F-actin Motion Index Failed",
            str(exc),
        )
        window._status("F-actin motion index failed.")
        if hasattr(window, "update_tracking_result_panel"):
            window.update_tracking_result_panel(sample_id)
        return None
