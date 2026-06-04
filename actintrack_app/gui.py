"""PyQt6 GUI — 2D Arabidopsis F-actin preprocessing and ROI annotation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
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

from actintrack_app.annotation_schema import (
    annotation_from_legacy,
    build_sample_annotation,
    merge_processed_into_annotation,
)
from actintrack_app.batch_annotation import (
    annotation_is_protected,
    propagate_annotation,
    resolve_propagation_targets,
    save_propagated_annotations,
)
from actintrack_app.batch_manager import (
    allocate_next_batch,
    batch_has_samples,
    create_batch,
    delete_empty_batch,
    display_batch_name,
    ensure_default_batch,
    get_batch_by_name,
    list_batches,
    parse_batch_number_from_name,
    prune_all_groups_without_samples,
    rename_batch,
    repair_batch_registry,
    reset_batches_registry_workspace,
    sanitize_batch_name,
)
from actintrack_app.file_importer import set_custom_export_name
from actintrack_app.import_dialog import open_import_data_dialog
from actintrack_app.gui_menus import (
    PurgeFilteredDialog,
    refresh_recent_workspaces_menu,
    setup_application_menus,
)
from actintrack_app.gui_canvas import ImageCanvas
from actintrack_app.image_processing import TrackingCrop, detect_tracking_crop
from actintrack_app.metadata import (
    get_sample_annotation,
    load_crop_metadata,
    migrate_workspace_schema,
    remove_samples_from_metadata,
    save_sample_crop_annotation,
    sync_samples_with_disk,
    update_samples_csv,
)
from actintrack_app.purge_cleanup_dialog import pick_empty_batch_name
from actintrack_app.purge_manager import (
    complete_batch_purge,
    delete_sample_from_batch,
    purge_batch_annotations,
    purge_filtered_samples,
    purge_sample_annotations_only,
    purge_sample_completely,
)
from actintrack_app.recent_workspaces import add_recent
from actintrack_app.orientation import (
    OrientationState,
    RectROI,
    apply_orientation,
    tracking_crop_to_rect,
)
from actintrack_app.project_manager import create_project_structure, is_valid_project
from actintrack_app.cropped_roi_preview import open_cropped_roi_preview
from actintrack_app.roi_workflow import (
    RoiValidationResult,
    is_wip_sample_path,
    list_output_paths_for_export,
    process_batch_approved_rois,
    process_sample_roi,
    validate_roi_for_sample,
)
from actintrack_app.utils import (
    CROP_METADATA_JSON,
    GROUPS,
    GROUP_PREFIX,
    METADATA_DIR,
    RAW_DIR,
    SAMPLES_CSV,
    STATUS_IMPORTED,
    STATUS_PROCESSED,
    STATUS_RAW_IMPORTED,
    STATUS_ROI_APPROVED,
    STATUS_ROI_MARKED,
    STATUS_ROI_PROPAGATED,
    STATUS_UNANNOTATED,
    SCOPE_SELECTED,
)
from actintrack_app.video_processing import MediaLoadError, load_media_frame


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = APP_ROOT / "raw_source"
AUTO_APPLY_ROI_CONFIDENCE = 0.15

STATUS_COLORS = {
    STATUS_IMPORTED: QColor("#bbbbbb"),
    STATUS_RAW_IMPORTED: QColor("#bbbbbb"),
    STATUS_UNANNOTATED: QColor("#aaaaaa"),
    "cutoff_marked": QColor("#c9b84c"),
    STATUS_ROI_MARKED: QColor("#6aa8ff"),
    STATUS_ROI_PROPAGATED: QColor("#ff9944"),
    STATUS_ROI_APPROVED: QColor("#66dd88"),
    STATUS_PROCESSED: QColor("#3ddc84"),
    "missing_file": QColor("#cc6666"),
}


class PropagateDialog(QDialog):
    def __init__(self, parent: QWidget, group: str, batch_name: str):
        super().__init__(parent)
        self.setWindowTitle("Propagate Annotation to Biological Batch")
        layout = QFormLayout(self)
        help_lbl = QLabel(
            "By default, annotations apply only within the same biological batch "
            "(one Arabidopsis sample), not across other batches in the condition group."
        )
        help_lbl.setWordWrap(True)
        layout.addRow(help_lbl)
        self.combo_scope = QComboBox()
        self.combo_scope.addItems(
            [
                f"Same biological batch ({batch_name})",
                f"Unprocessed files in {batch_name}",
                f"All files in condition {group}",
                "Currently selected files in list",
            ]
        )
        self.combo_scaling = QComboBox()
        self.combo_scaling.addItems(
            ["proportional_scaled", "same_coordinates"]
        )
        self.chk_overwrite = QCheckBox(
            "Overwrite existing annotations (never overwrites approved/processed without extra confirm)"
        )
        layout.addRow("Propagation scope:", self.combo_scope)
        layout.addRow("ROI scaling:", self.combo_scaling)
        layout.addRow(self.chk_overwrite)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def scope_key(self) -> str:
        from actintrack_app.utils import (
            SCOPE_ALL_IN_GROUP,
            SCOPE_SAME_BATCH,
            SCOPE_UNPROCESSED_IN_BATCH,
        )

        text = self.combo_scope.currentText()
        if text.startswith("Same biological"):
            return SCOPE_SAME_BATCH
        if text.startswith("Unprocessed"):
            return SCOPE_UNPROCESSED_IN_BATCH
        if "condition" in text:
            return SCOPE_ALL_IN_GROUP
        return SCOPE_SELECTED

    def scaling_method(self) -> str:
        return self.combo_scaling.currentText()

    def overwrite(self) -> bool:
        return self.chk_overwrite.isChecked()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ActinTrackCV — 2D Arabidopsis F-actin Preprocessing")
        self.resize(1280, 720)
        self.setMinimumSize(960, 600)

        self._project_root: Optional[Path] = None
        self._current_sample: Optional[dict] = None
        self._base_frame: Optional[np.ndarray] = None
        self._frame_index = 0
        self._total_frames = 1
        self._reference_frame_index = 0
        self._orientation = OrientationState()
        self._workspace_root = APP_ROOT
        self._default_source_root = (
            DEFAULT_SOURCE_ROOT if DEFAULT_SOURCE_ROOT.exists() else self._workspace_root
        )
        self._last_import_dir = self._default_source_root
        self._roi_user_adjusted = False
        self._loaded_annotation_source = "manual"

        self._build_ui()
        setup_application_menus(self)
        self._load_project(self._workspace_root, "Workspace project loaded")

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left_sidebar())
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.addWidget(
            QLabel(
                "Preview — orient the Arabidopsis sample and draw a rectangle "
                "around the usable actin-rich region (exclude the blurry "
                "nucleus-adjacent area)"
            )
        )
        self.canvas = ImageCanvas(self)
        center_layout.addWidget(self.canvas, stretch=1)
        splitter.addWidget(center)
        splitter.addWidget(self._build_right_sidebar())
        splitter.setSizes([260, 740, 280])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        layout.addWidget(splitter)
        self.setStatusBar(QStatusBar())

    def _build_left_sidebar(self) -> QWidget:
        """Sample list and view filters (import/setup is in the menu bar)."""
        panel = QWidget()
        panel.setMinimumWidth(260)
        panel.setMaximumWidth(360)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self._build_samples_panel(), stretch=1)
        return panel

    def _build_right_sidebar(self) -> QTabWidget:
        """Frame, ROI, and batch controls on separate tabs."""
        tabs = QTabWidget()
        tabs.setMinimumWidth(280)
        tabs.setMaximumWidth(380)

        preview = QWidget()
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(6, 6, 6, 6)
        preview_layout.addWidget(self._build_frame_panel())
        preview_layout.addWidget(self._build_selected_panel())
        preview_layout.addStretch()
        tabs.addTab(preview, "Frame")

        roi_tab = QWidget()
        roi_layout = QVBoxLayout(roi_tab)
        roi_layout.setContentsMargins(6, 6, 6, 6)
        roi_layout.addWidget(self._build_orientation_panel())
        roi_layout.addWidget(self._build_roi_panel())
        roi_layout.addStretch()
        tabs.addTab(roi_tab, "Orient && ROI")

        batch_tab = QWidget()
        batch_layout = QVBoxLayout(batch_tab)
        batch_layout.setContentsMargins(6, 6, 6, 6)
        batch_layout.addWidget(self._build_batch_panel())
        batch_layout.addWidget(self._build_notes_panel())
        batch_layout.addStretch()
        tabs.addTab(batch_tab, "Batch")
        return tabs

    def _build_samples_panel(self) -> QGroupBox:
        box = QGroupBox("Arabidopsis samples")
        layout = QVBoxLayout(box)
        self.lbl_workspace = QLabel("Workspace: —")
        self.lbl_workspace.setWordWrap(True)
        self.lbl_workspace.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self.lbl_workspace)
        self.combo_filter_group = QComboBox()
        self.combo_filter_group.addItems(list(GROUPS))
        self.combo_filter_group.currentTextChanged.connect(self._on_filter_group_changed)
        layout.addWidget(QLabel("Condition group:"))
        layout.addWidget(self.combo_filter_group)
        self.list_samples = QListWidget()
        self.list_samples.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection
        )
        self.list_samples.currentItemChanged.connect(self._on_sample_selected)
        self.list_samples.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.list_samples.customContextMenuRequested.connect(
            self._on_sample_list_context_menu
        )
        layout.addWidget(self.list_samples, stretch=1)
        self.btn_refresh_samples = self._tool_button(
            "Refresh",
            "Reload the sample list from workspace metadata.",
            self._on_refresh_samples,
        )
        layout.addWidget(self.btn_refresh_samples)
        nav = QHBoxLayout()
        self.btn_prev_sample = self._tool_button(
            "◀ Prev",
            "Select the previous file in the list.",
            self._on_prev_sample,
        )
        self.btn_next_sample = self._tool_button(
            "Next ▶",
            "Select the next file in the list.",
            self._on_next_sample,
        )
        nav.addWidget(self.btn_prev_sample)
        nav.addWidget(self.btn_next_sample)
        layout.addLayout(nav)
        hint = QLabel(
            "All batches for the selected condition are listed together. "
            "Batch menu actions use the selected sample's batch when applicable."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)
        return box

    def _build_frame_panel(self) -> QGroupBox:
        box = QGroupBox("Reference Frame")
        layout = QVBoxLayout(box)
        self.lbl_frame_info = QLabel("Frame: —")
        self.slider_frame = QSlider(Qt.Orientation.Horizontal)
        self.slider_frame.valueChanged.connect(self._on_frame_slider)
        self.spin_frame = QSpinBox()
        self.spin_frame.valueChanged.connect(self._on_frame_spin)
        self.btn_set_reference = QPushButton("Use Current Frame as Reference")
        self.btn_set_reference.clicked.connect(self._on_set_reference_frame)
        layout.addWidget(self.lbl_frame_info)
        layout.addWidget(self.slider_frame)
        layout.addWidget(self.spin_frame)
        layout.addWidget(self.btn_set_reference)
        return box

    def _build_selected_panel(self) -> QGroupBox:
        box = QGroupBox("Selected File")
        layout = QVBoxLayout(box)
        self.lbl_selected_file = QLabel("No sample selected")
        self.lbl_selected_file.setWordWrap(True)
        layout.addWidget(self.lbl_selected_file)
        layout.addWidget(QLabel("Export name:"))
        self.edit_export_name = QLineEdit()
        self.edit_export_name.setPlaceholderText("auto-generated from condition + batch")
        self.edit_export_name.editingFinished.connect(self._on_export_name_edited)
        layout.addWidget(self.edit_export_name)
        self.lbl_auto_export_name = QLabel("Auto name: —")
        self.lbl_auto_export_name.setWordWrap(True)
        self.lbl_auto_export_name.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self.lbl_auto_export_name)
        return box

    def _build_orientation_panel(self) -> QGroupBox:
        box = QGroupBox("Orientation")
        layout = QVBoxLayout(box)
        row1 = QHBoxLayout()
        self.btn_rot_left = QPushButton("Rotate 90° Left")
        self.btn_rot_right = QPushButton("Rotate 90° Right")
        self.btn_rot_left.clicked.connect(lambda: self._rotate_by(90))
        self.btn_rot_right.clicked.connect(lambda: self._rotate_by(-90))
        row1.addWidget(self.btn_rot_left)
        row1.addWidget(self.btn_rot_right)
        layout.addLayout(row1)
        custom = QHBoxLayout()
        custom.addWidget(QLabel("Custom °:"))
        self.spin_custom_angle = QDoubleSpinBox()
        self.spin_custom_angle.setRange(-180, 180)
        self.spin_custom_angle.setDecimals(1)
        self.btn_apply_custom = QPushButton("Apply")
        self.btn_apply_custom.clicked.connect(self._on_apply_custom_angle)
        custom.addWidget(self.spin_custom_angle)
        custom.addWidget(self.btn_apply_custom)
        layout.addLayout(custom)
        self.btn_flip = QPushButton("Flip 180°")
        self.btn_flip.clicked.connect(self._on_flip_180)
        self.btn_reset_orientation = QPushButton("Reset Orientation")
        self.btn_reset_orientation.clicked.connect(self._on_reset_orientation)
        self.lbl_orientation = QLabel("Angle: 0°  Flip: no")
        self.lbl_orientation.setWordWrap(True)
        layout.addWidget(self.btn_flip)
        layout.addWidget(self.btn_reset_orientation)
        layout.addWidget(self.lbl_orientation)
        return box

    def _build_roi_panel(self) -> QGroupBox:
        box = QGroupBox("Analysis ROI")
        layout = QVBoxLayout(box)
        self.lbl_roi_info = QLabel("Draw a rectangle on the preview.")
        self.lbl_roi_info.setWordWrap(True)
        self.btn_auto_roi = QPushButton("Suggest ROI from F-actin Signal")
        self.btn_auto_roi.clicked.connect(self._on_auto_suggest_roi)
        self.btn_clear_roi = QPushButton("Clear ROI")
        self.btn_clear_roi.clicked.connect(self._on_clear_roi)
        self.btn_preview_crop = self._tool_button(
            "Preview Cropped ROI",
            "Play or scrub through the cropped ROI over time (video or image sequence). "
            "Preview only — does not write files.",
            self._on_preview_crop,
        )
        self.btn_save_annotation = self._tool_button(
            "Save ROI",
            "Save the rectangular ROI annotation to workspace metadata.",
            self._on_save_annotation,
        )
        self.btn_process = self._tool_button(
            "Export ROI",
            "Crop and export processed outputs to the processed/ folder.",
            self._on_process_sample,
        )
        layout.addWidget(self.lbl_roi_info)
        layout.addWidget(self.btn_auto_roi)
        layout.addWidget(self.btn_clear_roi)
        layout.addWidget(self.btn_preview_crop)
        layout.addWidget(self.btn_save_annotation)
        layout.addWidget(self.btn_process)
        return box

    def _build_batch_panel(self) -> QGroupBox:
        box = QGroupBox("Batch Annotation & Review")
        layout = QVBoxLayout(box)
        review = QHBoxLayout()
        self.btn_approve = self._tool_button(
            "Approve",
            "Mark the current ROI as approved for export.",
            self._on_approve_roi,
        )
        self.btn_reject = self._tool_button(
            "Reject",
            "Remove the ROI annotation and reset sample status.",
            self._on_reject_roi,
        )
        review.addWidget(self.btn_approve)
        review.addWidget(self.btn_reject)
        layout.addLayout(review)
        batch_hint = QLabel(
            "Apply to batch, process batch, delete file: Batch menu."
        )
        batch_hint.setWordWrap(True)
        batch_hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(batch_hint)
        return box

    def _build_notes_panel(self) -> QGroupBox:
        box = QGroupBox("Notes")
        layout = QVBoxLayout(box)
        self.txt_notes = QTextEdit()
        self.txt_notes.setMaximumHeight(70)
        layout.addWidget(self.txt_notes)
        return box

    @staticmethod
    def _tool_button(text: str, tooltip: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.setToolTip(tooltip)
        btn.clicked.connect(slot)
        return btn

    def _status(self, msg: str) -> None:
        self.statusBar().showMessage(msg, 8000)

    def _update_orientation_label(self) -> None:
        self.lbl_orientation.setText(
            f"Angle: {self._orientation.rotation_angle_degrees:.1f}°  "
            f"Flip: {'yes' if self._orientation.flipped_180 else 'no'}\n"
            f"Steps: {', '.join(self._orientation.manual_rotation_steps) or '—'}"
        )

    def _oriented_frame(self) -> Optional[np.ndarray]:
        if self._base_frame is None:
            return None
        return apply_orientation(self._base_frame, self._orientation)

    def _refresh_display(self, *, keep_roi: bool = True) -> None:
        oriented = self._oriented_frame()
        if oriented is None:
            return
        roi = self.canvas.rect_roi() if keep_roi else None
        self.canvas.set_frame(oriented, keep_roi=keep_roi)
        if roi is not None:
            self.canvas.set_rect_roi(roi.clamp(oriented.shape[1], oriented.shape[0]))
        self._update_orientation_label()

    def _rotate_by(self, delta: float) -> None:
        self._orientation.rotation_angle_degrees += delta
        step = "rotate_left_90" if delta > 0 else "rotate_right_90"
        self._orientation.add_step(step)
        self._refresh_display()

    def _on_apply_custom_angle(self) -> None:
        angle = self.spin_custom_angle.value()
        self._orientation.rotation_angle_degrees = angle
        self._orientation.add_step(f"custom_angle_{angle:.1f}")
        self._refresh_display()

    def _on_flip_180(self) -> None:
        self._orientation.flipped_180 = not self._orientation.flipped_180
        self._orientation.add_step("flip_180")
        self._refresh_display()

    def _on_reset_orientation(self) -> None:
        self._orientation = OrientationState()
        self._refresh_display(keep_roi=True)

    def on_roi_changed(self, roi: Optional[RectROI]) -> None:
        if roi is None:
            self.lbl_roi_info.setText("No ROI selected.")
            return
        self._roi_user_adjusted = True
        if self._base_frame is not None:
            check = validate_roi_for_sample(
                roi, base_frame=self._base_frame, orientation=self._orientation
            )
            if check.roi_original is not None:
                self.lbl_roi_info.setText(
                    f"ROI (oriented): x={roi.x} y={roi.y} w={roi.width} h={roi.height}\n"
                    f"Original frame: x={check.roi_original.x} y={check.roi_original.y} "
                    f"w={check.roi_original.width} h={check.roi_original.height}"
                )
                return
        self.lbl_roi_info.setText(
            f"ROI x={roi.x} y={roi.y} w={roi.width} h={roi.height}"
        )

    def _on_clear_roi(self) -> None:
        self.canvas.set_rect_roi(None)
        self.lbl_roi_info.setText("ROI cleared.")
        self._roi_user_adjusted = True

    def _on_preview_crop(self) -> None:
        if self._project_root is None or self._current_sample is None:
            QMessageBox.warning(self, "Preview Cropped ROI", "Select a sample first.")
            return
        check = self._validate_current_roi()
        if not check.ok:
            QMessageBox.warning(self, "Preview Cropped ROI", check.message)
            return
        path = self._sample_file_path()
        if path is None or not path.exists():
            QMessageBox.warning(self, "Preview Cropped ROI", "Sample file not found.")
            return
        if is_wip_sample_path(path):
            QMessageBox.information(
                self,
                "Unsupported",
                "Raw or 3D formats are not supported in the 2D crop workflow.",
            )
            return
        ann = get_sample_annotation(
            self._project_root, str(self._current_sample["sample_id"])
        )
        open_cropped_roi_preview(
            self,
            sample_row=self._current_sample,
            source_path=path,
            orientation=self._orientation,
            roi_validation=check,
            annotation=ann,
        )

    def _on_auto_suggest_roi(self) -> None:
        oriented = self._oriented_frame()
        if oriented is None:
            return
        try:
            crop = detect_tracking_crop(oriented)
            self.canvas.set_rect_roi(tracking_crop_to_rect(crop))
            self.lbl_roi_info.setText(
                f"Suggested ROI (confidence {crop.confidence:.2f}) — review and adjust."
            )
        except ValueError as e:
            QMessageBox.warning(self, "ROI Suggestion", str(e))

    def _validate_current_roi(self) -> RoiValidationResult:
        if self._base_frame is None:
            return RoiValidationResult(False, "No frame loaded. Select a sample first.")
        roi = self.canvas.rect_roi()
        if roi is None and self._project_root is not None and self._current_sample:
            ann = get_sample_annotation(
                self._project_root, str(self._current_sample["sample_id"])
            )
            if ann:
                _, roi = annotation_from_legacy(ann)
        if roi is None:
            return RoiValidationResult(
                False,
                "Please draw or load a rectangular ROI before previewing "
                "the cropped region.",
            )
        return validate_roi_for_sample(
            roi,
            base_frame=self._base_frame,
            orientation=self._orientation,
        )

    def _annotation_source_for_save(self) -> str:
        src = str(self._loaded_annotation_source or "manual")
        if self._roi_user_adjusted and src in ("propagated", "propagated_adjusted"):
            return "propagated_adjusted"
        if self._roi_user_adjusted and src != "manual":
            return "propagated_adjusted"
        return src if src else "manual"

    def _current_annotation_dict(self, *, status: str) -> dict[str, Any]:
        assert self._current_sample is not None and self._base_frame is not None
        check = self._validate_current_roi()
        if not check.ok:
            raise ValueError(check.message)
        assert check.roi_oriented is not None and check.roi_original is not None
        oriented = self._oriented_frame()
        assert oriented is not None
        oh, ow = oriented.shape[:2]
        bh, bw = self._base_frame.shape[:2]
        review = str(self._current_sample.get("review_status", "approved"))
        requires_review = status == STATUS_ROI_PROPAGATED
        if status == STATUS_ROI_MARKED and self._annotation_source_for_save().startswith(
            "propagated"
        ):
            review = "pending"
            requires_review = True
        return build_sample_annotation(
            sample_id=str(self._current_sample["sample_id"]),
            group=str(self._current_sample["group"]),
            batch_name=str(self._current_sample.get("batch_name", "")),
            batch_id=str(self._current_sample.get("batch_id", "")),
            original_file=str(self._current_sample["original_filename"]),
            stored_raw_path=str(self._current_sample["stored_path"]),
            reference_frame_index=self._reference_frame_index,
            orientation=self._orientation,
            roi=check.roi_oriented.clamp(ow, oh),
            roi_original=check.roi_original.clamp(bw, bh),
            original_dimensions={"width": bw, "height": bh},
            oriented_dimensions={"width": ow, "height": oh},
            notes=self.txt_notes.toPlainText().strip(),
            annotation_source=self._annotation_source_for_save(),
            roi_method="manual_rectangle",
            segmentation_method="manual",
            segmentation_parameters={},
            status=status,
            requires_review=requires_review,
            review_status=review if requires_review else "approved",
        )

    def _on_save_annotation(self) -> None:
        if self._project_root is None or self._current_sample is None:
            QMessageBox.warning(self, "Save ROI", "Select a sample first.")
            return
        try:
            ann = self._current_annotation_dict(status=STATUS_ROI_MARKED)
        except ValueError as e:
            QMessageBox.warning(self, "Save ROI", str(e))
            return
        sid = ann["sample_id"]
        crop_path = self._project_root / METADATA_DIR / CROP_METADATA_JSON
        save_sample_crop_annotation(crop_path, sid, ann)
        update_samples_csv(
            self._project_root / METADATA_DIR / SAMPLES_CSV,
            {
                "sample_id": sid,
                "processing_status": STATUS_ROI_MARKED,
                "notes": ann["notes"],
                "annotation_source": ann["annotation_source"],
                "review_status": ann.get("review_status", "approved"),
            },
        )
        self._loaded_annotation_source = ann["annotation_source"]
        self._roi_user_adjusted = False
        self._refresh_sample_list()
        self._status(f"Saved ROI for {sid}")
        QMessageBox.information(self, "Saved", f"ROI annotation saved for {sid}.")

    def _process_kwargs_from_sample(self) -> dict[str, Any]:
        assert self._current_sample is not None
        try:
            batch_number = int(self._current_sample.get("batch_number", 1) or 1)
        except ValueError:
            batch_number = 1
        is_video = str(self._current_sample.get("is_video", "")).lower() == "true"
        return {
            "batch_number": batch_number,
            "final_export_name": str(
                self._current_sample.get("final_export_name", "")
            ).strip(),
            "is_video": is_video,
        }

    def _confirm_overwrite(self, paths: list[Path]) -> bool:
        existing = [p for p in paths if p.exists()]
        if not existing:
            return True
        names = "\n".join(f"  • {p.name}" for p in existing[:5])
        if len(existing) > 5:
            names += f"\n  … +{len(existing) - 5} more"
        reply = QMessageBox.question(
            self,
            "Overwrite Outputs?",
            f"The following processed file(s) already exist:\n{names}\n\nOverwrite?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _confirm_pending_export(self, ann: dict[str, Any]) -> bool:
        if str(ann.get("review_status", "")) != "pending" and not ann.get(
            "requires_review"
        ):
            return True
        reply = QMessageBox.warning(
            self,
            "ROI Not Approved",
            "This ROI is marked pending review (e.g. propagated annotation). "
            "Export anyway without approving?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _on_process_sample(self) -> None:
        if self._project_root is None or self._current_sample is None:
            return
        try:
            ann = self._current_annotation_dict(status=STATUS_ROI_MARKED)
        except ValueError as e:
            QMessageBox.warning(self, "Export ROI", str(e))
            return
        if not self._confirm_pending_export(ann):
            return
        path = self._sample_file_path()
        if path is None or not path.exists():
            QMessageBox.warning(self, "Export ROI", "Sample file not found.")
            return
        if is_wip_sample_path(path):
            QMessageBox.information(
                self,
                "Unsupported",
                "Raw or 3D formats are not supported in the 2D crop workflow.",
            )
            return
        sid = str(self._current_sample["sample_id"])
        pk = self._process_kwargs_from_sample()
        if not pk["final_export_name"]:
            QMessageBox.warning(self, "Export ROI", "Export name is missing.")
            return
        check = self._validate_current_roi()
        assert check.roi_oriented is not None and check.roi_original is not None
        out_paths = list_output_paths_for_export(
            self._project_root,
            str(self._current_sample["group"]),
            str(self._current_sample.get("batch_name", "")),
            pk["final_export_name"],
            pk["is_video"],
        )
        if not self._confirm_overwrite(out_paths):
            return
        try:
            result = process_sample_roi(
                root=self._project_root,
                sample_row=self._current_sample,
                annotation=ann,
                source_path=path,
                orientation=self._orientation,
                roi_oriented=check.roi_oriented,
                roi_original=check.roi_original,
                overwrite=True,
                export_frames=False,
            )
            ann = merge_processed_into_annotation(ann, result)
            ann.update(result.get("export_metadata", {}))
            save_sample_crop_annotation(
                self._project_root / METADATA_DIR / CROP_METADATA_JSON, sid, ann
            )
            update_samples_csv(
                self._project_root / METADATA_DIR / SAMPLES_CSV,
                {
                    "sample_id": sid,
                    "processing_status": STATUS_PROCESSED,
                    "review_status": "approved",
                },
            )
            self._refresh_sample_list()
            QMessageBox.information(
                self,
                "Export Complete",
                f"Exported {result['frame_count']} frame(s) to:\n{result.get('output_file')}",
            )
            self._status(f"Processed {sid}")
        except FileExistsError as e:
            QMessageBox.warning(self, "Export ROI", str(e))
        except (MediaLoadError, OSError, ValueError) as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def _on_propagate_batch(self) -> None:
        if self._project_root is None or self._current_sample is None:
            return
        if self.canvas.rect_roi() is None:
            QMessageBox.warning(
                self,
                "Propagate",
                "Set orientation and ROI on the source sample first.",
            )
            return
        group = str(self._current_sample["group"])
        batch_name = str(self._current_sample.get("batch_name", ""))
        if not batch_name:
            QMessageBox.warning(
                self,
                "Propagate",
                "Current sample has no biological batch. Re-import or migrate project.",
            )
            return
        dlg = PropagateDialog(self, group, batch_name)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        source_ann = self._current_annotation_dict(status=STATUS_ROI_MARKED)
        source_id = source_ann["sample_id"]
        scope = dlg.scope_key()
        selected = None
        if scope == SCOPE_SELECTED:
            selected = self._selected_sample_ids()
            if not selected:
                QMessageBox.warning(self, "Propagate", "Select target samples in the list.")
                return
        targets = resolve_propagation_targets(
            self._project_root, source_id, scope, selected
        )
        if not targets:
            QMessageBox.information(self, "Propagate", "No target samples for this scope.")
            return
        crop_data = load_crop_metadata(self._project_root / METADATA_DIR / CROP_METADATA_JSON)
        src_orient = source_ann.get("oriented_dimensions", {})
        src_w, src_h = int(src_orient.get("width", 0)), int(src_orient.get("height", 0))
        dim_warnings: list[str] = []
        to_write: list[dict] = []
        skipped = 0
        protected_skipped = 0
        for tgt in targets:
            tid = str(tgt["sample_id"])
            existing = crop_data.get("samples", {}).get(tid)
            tgt_status = str(tgt.get("processing_status", ""))
            if annotation_is_protected(tgt_status) or (
                existing and annotation_is_protected(str(existing.get("status", "")))
            ):
                protected_skipped += 1
                continue
            if existing and not dlg.overwrite():
                skipped += 1
                continue
            try:
                ann = propagate_annotation(
                    self._project_root,
                    source_ann,
                    tgt,
                    scaling_method=dlg.scaling_method(),
                )
                tgt_o = ann.get("oriented_dimensions", {})
                tw, th = int(tgt_o.get("width", 0)), int(tgt_o.get("height", 0))
                if src_w and src_h and (tw != src_w or th != src_h):
                    dim_warnings.append(
                        f"{tid}: {src_w}×{src_h} → {tw}×{th} ({dlg.scaling_method()})"
                    )
                to_write.append(ann)
            except (MediaLoadError, ValueError) as e:
                QMessageBox.warning(
                    self, "Propagate", f"Skipped {tid}: {e}"
                )
        if not to_write:
            QMessageBox.information(
                self,
                "Propagate",
                f"No annotations written ({skipped} skipped).",
            )
            return
        if dim_warnings and dlg.scaling_method() == "same_coordinates":
            preview = "\n".join(dim_warnings[:6])
            if len(dim_warnings) > 6:
                preview += f"\n… +{len(dim_warnings) - 6} more"
            reply = QMessageBox.warning(
                self,
                "Dimension Mismatch",
                "Some targets differ in size from the source. "
                "Using same_coordinates may place the ROI incorrectly.\n\n"
                f"{preview}\n\nContinue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        save_propagated_annotations(self._project_root, to_write)
        samples_path = self._project_root / METADATA_DIR / SAMPLES_CSV
        for ann in to_write:
            update_samples_csv(
                samples_path,
                {
                    "sample_id": ann["sample_id"],
                    "processing_status": STATUS_ROI_PROPAGATED,
                },
            )
        self._refresh_sample_list()
        QMessageBox.information(
            self,
            "Propagate",
            f"Propagated to {len(to_write)} sample(s). "
            f"{skipped} skipped (existing annotations). "
            f"{protected_skipped} skipped (approved/processed). "
            "Review each with Approve / Adjust / Reject.",
        )

    def _on_approve_roi(self) -> None:
        self._set_review_status(STATUS_ROI_APPROVED, requires_review=False)

    def _on_reject_roi(self) -> None:
        if self._project_root is None or self._current_sample is None:
            return
        sid = str(self._current_sample["sample_id"])
        crop_path = self._project_root / METADATA_DIR / CROP_METADATA_JSON
        data = load_crop_metadata(crop_path)
        data.get("samples", {}).pop(sid, None)
        with crop_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        update_samples_csv(
            self._project_root / METADATA_DIR / SAMPLES_CSV,
            {"sample_id": sid, "processing_status": STATUS_IMPORTED},
        )
        self.canvas.set_rect_roi(None)
        self._refresh_sample_list()
        self._status(f"Rejected ROI for {sid}")

    def _set_review_status(self, status: str, *, requires_review: bool) -> None:
        if self._project_root is None or self._current_sample is None:
            return
        sid = str(self._current_sample["sample_id"])
        ann = get_sample_annotation(self._project_root, sid)
        if not ann:
            QMessageBox.warning(self, "Review", "No saved annotation for this sample.")
            return
        ann["status"] = status
        ann["requires_review"] = requires_review
        ann["review_status"] = "approved" if status == STATUS_ROI_APPROVED else ann.get(
            "review_status", "pending"
        )
        save_sample_crop_annotation(
            self._project_root / METADATA_DIR / CROP_METADATA_JSON, sid, ann
        )
        update_samples_csv(
            self._project_root / METADATA_DIR / SAMPLES_CSV,
            {"sample_id": sid, "processing_status": status},
        )
        self._refresh_sample_list()
        self._status(f"{sid} → {status}")

    def _on_process_approved_batch(self) -> None:
        if self._project_root is None or self._current_sample is None:
            return
        group = str(self._current_sample["group"])
        batch_name = sanitize_batch_name(str(self._current_sample.get("batch_name", "")))
        approved, skipped, _ = process_batch_approved_rois(
            root=self._project_root,
            group=group,
            batch_name=batch_name,
            overwrite=False,
            export_frames=False,
        )
        pre_skipped = len(skipped)
        if not approved:
            QMessageBox.information(
                self,
                "Batch Export",
                f"No ROI-approved samples ready in {group} / {batch_name}.\n"
                f"Skipped (not approved or missing ROI): {pre_skipped}",
            )
            return
        reply = QMessageBox.question(
            self,
            "Process Approved Samples in Batch",
            f"Condition group: {group}\n"
            f"Biological batch: {batch_name}\n\n"
            f"Samples to export: {len(approved)}\n"
            f"Samples skipped: {pre_skipped}\n\n"
            "Only approved ROIs will be exported. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        all_out: list[Path] = []
        df = pd.read_csv(
            self._project_root / METADATA_DIR / SAMPLES_CSV,
            dtype=str,
            keep_default_na=False,
        )
        for sid in approved:
            row = df[df["sample_id"] == sid].iloc[0].to_dict()
            final_name = str(row.get("final_export_name", "")).strip()
            is_video = str(row.get("is_video", "")).lower() == "true"
            if final_name:
                all_out.extend(
                    list_output_paths_for_export(
                        self._project_root,
                        group,
                        batch_name,
                        final_name,
                        is_video,
                    )
                )
        if not self._confirm_overwrite(all_out):
            return
        _, _, report = process_batch_approved_rois(
            root=self._project_root,
            group=group,
            batch_name=batch_name,
            overwrite=True,
            export_frames=False,
        )
        self._refresh_sample_list()
        err_preview = ""
        if report.errors:
            err_preview = "\n\nIssues:\n" + "\n".join(report.errors[:8])
            if len(report.errors) > 8:
                err_preview += f"\n… +{len(report.errors) - 8} more"
        QMessageBox.information(
            self,
            "Batch Export Complete",
            f"Successful exports: {report.processed}\n"
            f"Failed: {report.failed}\n"
            f"Skipped: {pre_skipped + report.skipped}"
            f"{err_preview}",
        )

    def _list_item_meta(self, item: QListWidgetItem | None) -> dict[str, Any] | None:
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else None

    @staticmethod
    def _is_sample_item(item: QListWidgetItem | None) -> bool:
        if item is None:
            return False
        data = item.data(Qt.ItemDataRole.UserRole)
        return isinstance(data, dict) and data.get("item_type") == "sample"

    def _selected_sample_ids(self) -> list[str]:
        ids = []
        for item in self.list_samples.selectedItems():
            data = self._list_item_meta(item)
            if data and data.get("item_type") == "sample":
                ids.append(str(data["sample_id"]))
        return ids

    def _navigate_sample(self, delta: int) -> None:
        rows = []
        for i in range(self.list_samples.count()):
            item = self.list_samples.item(i)
            if self._is_sample_item(item):
                rows.append(i)
        if not rows:
            return
        cur = self.list_samples.currentRow()
        try:
            pos = rows.index(cur)
        except ValueError:
            pos = 0
        pos = max(0, min(len(rows) - 1, pos + delta))
        self.list_samples.setCurrentRow(rows[pos])

    def _on_prev_sample(self) -> None:
        self._navigate_sample(-1)

    def _on_next_sample(self) -> None:
        self._navigate_sample(1)

    # --- Project / import (unchanged core) ---

    def _load_project(self, root: Path, status_msg: str) -> None:
        try:
            root = Path(root).resolve()
            if not is_valid_project(root):
                create_project_structure(root)
            migrate_workspace_schema(root)
            repair_batch_registry(root)
            self._project_root = root
            add_recent(root, root)
            self._refresh_recent_menu()
            self.btn_refresh_samples.setEnabled(True)
            self._update_workspace_label()
            self._refresh_sample_list()
            self._status(f"{status_msg}: {root}")
        except OSError as e:
            QMessageBox.critical(self, "Project Error", str(e))

    def _on_filter_group_changed(self) -> None:
        self._refresh_sample_list()

    def _after_import_refresh(self) -> None:
        self._refresh_sample_list()

    def _ensure_filter_group_valid(self) -> str:
        """Keep a valid condition group selected; fall back to the first."""
        if self.combo_filter_group.currentText() in GROUPS:
            return self.combo_filter_group.currentText()
        self.combo_filter_group.blockSignals(True)
        self.combo_filter_group.setCurrentIndex(0)
        self.combo_filter_group.blockSignals(False)
        return self.combo_filter_group.currentText()

    def _selected_batch_record(self) -> dict[str, str] | None:
        if self._project_root is None:
            return None
        group = self._ensure_filter_group_valid()
        name = self._context_batch_name(group)
        if not name:
            return None
        return get_batch_by_name(self._project_root, group, name)

    @staticmethod
    def _batch_list_header_text(group: str, batch: dict[str, Any]) -> str:
        num = int(batch.get("batch_number", 1) or 1)
        name = str(batch.get("batch_name", "")).strip()
        canonical = display_batch_name(num)
        if sanitize_batch_name(name) == sanitize_batch_name(canonical):
            return f"──── {group} / {canonical} ────"
        return f"──── {group} / {canonical}: {name} ────"

    def _context_batch_name(self, group: str | None = None) -> str | None:
        """Batch for menu actions: current sample's batch, or ask if ambiguous."""
        if self._project_root is None:
            return None
        group = group or self._ensure_filter_group_valid()
        if self._current_sample and str(self._current_sample.get("group")) == group:
            name = str(self._current_sample.get("batch_name", "")).strip()
            if name:
                return name
        batches = list_batches(self._project_root, group)
        if not batches:
            return None
        if len(batches) == 1:
            return str(batches[0]["batch_name"])
        labels = [self._batch_list_header_text(group, b) for b in batches]
        names = [str(b["batch_name"]) for b in batches]
        picked, ok = QInputDialog.getItem(
            self,
            "Select Batch",
            f"Choose a batch in {group}:",
            labels,
            0,
            False,
        )
        if not ok or not picked:
            return None
        idx = labels.index(picked)
        return names[idx]

    def _pick_batch_name_to_rename(self, group: str) -> str | None:
        batches = list_batches(self._project_root, group) if self._project_root else []
        if not batches:
            QMessageBox.information(
                self, "Rename Batch", "No batches exist for this condition group."
            )
            return None
        labels = [self._batch_list_header_text(group, b) for b in batches]
        names = [str(b["batch_name"]) for b in batches]
        picked, ok = QInputDialog.getItem(
            self,
            "Rename Biological Batch",
            f"Batch to rename in {group}:",
            labels,
            0,
            False,
        )
        if not ok or not picked:
            return None
        return names[labels.index(picked)]

    def _on_new_batch(self) -> None:
        if self._project_root is None:
            return
        group = self.combo_filter_group.currentText()
        _num, default_name = allocate_next_batch(self._project_root, group)
        name, ok = QInputDialog.getText(
            self,
            "New Biological Batch",
            f"Batch name for condition {group}:",
            text=default_name,
        )
        if not ok or not name.strip():
            return
        try:
            num, _ = allocate_next_batch(
                self._project_root, group, preferred_name=name.strip()
            )
            batch = create_batch(
                self._project_root, group, name.strip(), batch_number=num
            )
            self._refresh_sample_list()
            self._status(f"Created biological batch {batch['batch_name']}")
        except ValueError as e:
            QMessageBox.warning(self, "New Batch", str(e))

    def _on_rename_batch(self) -> None:
        if self._project_root is None:
            return
        group = self._ensure_filter_group_valid()
        old = self._pick_batch_name_to_rename(group)
        if not old:
            return
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Biological Batch",
            "New batch name:",
            text=old,
        )
        if not ok or not new_name.strip():
            return
        try:
            rename_batch(self._project_root, group, old, new_name.strip())
            self._refresh_sample_list()
        except (ValueError, OSError) as e:
            QMessageBox.critical(self, "Rename Batch", str(e))

    def _update_workspace_label(self) -> None:
        if self._project_root is None:
            self.lbl_workspace.setText("Workspace: —")
            return
        self.lbl_workspace.setText(f"Workspace:\n{self._project_root}")

    def _default_import_dir(self) -> Path:
        if self._last_import_dir.exists():
            return self._last_import_dir
        if self._default_source_root.exists():
            return self._default_source_root
        return self._project_root or Path.home()

    def _on_select_project(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Project folder", str(self._workspace_root)
        )
        if folder:
            self._load_project(Path(folder), "Project loaded")

    def _add_sample_list_header(self, group: str, batch: dict[str, Any]) -> None:
        text = self._batch_list_header_text(group, batch)
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setForeground(QBrush(QColor("#888888")))
        item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "item_type": "batch_header",
                "group": group,
                "batch_name": str(batch.get("batch_name", "")),
                "batch_number": int(batch.get("batch_number", 1) or 1),
            },
        )
        self.list_samples.addItem(item)

    def _add_sample_list_message(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setForeground(QBrush(QColor("#aaaaaa")))
        self.list_samples.addItem(item)

    def _add_sample_list_row(self, row: pd.Series) -> None:
        status = str(row["processing_status"])
        export_name = str(
            row.get("final_export_name") or row.get("auto_export_name") or ""
        ).strip()
        if not export_name:
            export_name = str(row["sample_id"])
        original = str(row.get("original_filename", ""))
        label = f"    [{status}] {export_name} — {original}"
        item = QListWidgetItem(label)
        sample_data = row.to_dict()
        sample_data["item_type"] = "sample"
        item.setData(Qt.ItemDataRole.UserRole, sample_data)
        color = STATUS_COLORS.get(status)
        if color:
            item.setForeground(QBrush(color))
        self.list_samples.addItem(item)

    def _refresh_sample_list(self) -> None:
        keep_id = (
            str(self._current_sample["sample_id"])
            if self._current_sample
            else None
        )
        self.list_samples.clear()
        if self._project_root is None:
            return
        try:
            df, _missing_ids = sync_samples_with_disk(self._project_root)
        except Exception as e:
            QMessageBox.warning(self, "Metadata", str(e))
            return

        group = self._ensure_filter_group_valid()
        group_df = df[df["group"] == group]

        # After a full workspace purge samples.csv is empty but batches.json may still
        # list Batch 1 for untouched groups — clear those ghost labels on refresh.
        if df.empty:
            reset_batches_registry_workspace(self._project_root)

        batches = list_batches(self._project_root, group)

        if not batches:
            self._add_sample_list_message(
                "No batches available for this condition group."
            )
            self._current_sample = None
            self._clear_preview_pane()
            return

        seen_batches: set[str] = set()
        for batch in batches:
            batch_name = str(batch["batch_name"])
            safe = sanitize_batch_name(batch_name)
            seen_batches.add(safe)
            self._add_sample_list_header(group, batch)
            batch_rows = group_df[
                group_df["batch_name"].astype(str).apply(sanitize_batch_name)
                == safe
            ]
            if batch_rows.empty:
                continue
            batch_rows = batch_rows.sort_values(
                by=["frame_number", "sample_id"],
                key=lambda col: col.astype(str),
            )
            for _, row in batch_rows.iterrows():
                self._add_sample_list_row(row)

        orphan = group_df[
            ~group_df["batch_name"]
            .astype(str)
            .apply(sanitize_batch_name)
            .isin(seen_batches)
        ]
        if not orphan.empty:
            for batch_name in sorted(
                orphan["batch_name"].astype(str).unique(),
                key=lambda n: sanitize_batch_name(n),
            ):
                safe = sanitize_batch_name(batch_name)
                orphan_batch = {
                    "batch_name": batch_name,
                    "batch_number": parse_batch_number_from_name(batch_name) or 0,
                }
                self._add_sample_list_header(group, orphan_batch)
                batch_rows = orphan[
                    orphan["batch_name"]
                    .astype(str)
                    .apply(sanitize_batch_name)
                    == safe
                ].sort_values(
                    by=["frame_number", "sample_id"],
                    key=lambda col: col.astype(str),
                )
                for _, row in batch_rows.iterrows():
                    self._add_sample_list_row(row)

        if keep_id:
            for i in range(self.list_samples.count()):
                item = self.list_samples.item(i)
                data = self._list_item_meta(item)
                if (
                    data
                    and data.get("item_type") == "sample"
                    and str(data.get("sample_id")) == keep_id
                ):
                    self.list_samples.setCurrentItem(item)
                    break
        else:
            first_sample = None
            for i in range(self.list_samples.count()):
                item = self.list_samples.item(i)
                if self._is_sample_item(item):
                    first_sample = item
                    break
            if first_sample is not None:
                self.list_samples.setCurrentItem(first_sample)
            else:
                self._current_sample = None
                self._clear_preview_pane()

    def _on_refresh_samples(self) -> None:
        self._refresh_sample_list()

    def _on_remove_missing_samples(self) -> None:
        if self._project_root is None:
            return
        _, missing_ids = sync_samples_with_disk(self._project_root)
        if not missing_ids:
            return
        if (
            QMessageBox.question(
                self,
                "Remove Missing",
                f"Remove {len(missing_ids)} missing sample(s) from metadata?",
            )
            == QMessageBox.StandardButton.Yes
        ):
            remove_samples_from_metadata(self._project_root, missing_ids)
            self._refresh_sample_list()

    def _menu_import_data(self) -> None:
        open_import_data_dialog(self)

    def _clear_preview_pane(self) -> None:
        self.lbl_selected_file.setText("No file selected.")
        self.lbl_auto_export_name.setText("Auto name: —")
        self.edit_export_name.clear()
        self.lbl_frame_info.setText("—")
        self.lbl_roi_info.setText("Select a file in the sample list.")
        self.canvas.clear_preview()

    def _on_sample_selected(
        self,
        current: Optional[QListWidgetItem],
        _previous: Optional[QListWidgetItem],
    ) -> None:
        if current is None:
            return
        data = self._list_item_meta(current)
        if not data or data.get("item_type") != "sample":
            return
        self._current_sample = data
        group = str(data.get("group", ""))
        if group and group in GROUPS and self.combo_filter_group.currentText() != group:
            self.combo_filter_group.blockSignals(True)
            idx = self.combo_filter_group.findText(group)
            if idx >= 0:
                self.combo_filter_group.setCurrentIndex(idx)
            self.combo_filter_group.blockSignals(False)
        if data.get("processing_status") == "missing_file":
            return
        self._load_sample_preview()

    def _sample_file_path(self) -> Optional[Path]:
        if self._project_root is None or self._current_sample is None:
            return None
        return self._project_root / str(self._current_sample["stored_path"])

    def _restore_annotation(self, ann: dict[str, Any]) -> None:
        self._orientation, roi = annotation_from_legacy(ann)
        self._reference_frame_index = int(ann.get("reference_frame_index", 0))
        self.txt_notes.setPlainText(str(ann.get("notes", "")))
        self._refresh_display(keep_roi=False)
        if roi is not None:
            oriented = self._oriented_frame()
            if oriented is not None:
                self.canvas.set_rect_roi(roi.clamp(oriented.shape[1], oriented.shape[0]))
        src = ann.get("annotation_source", "saved")
        self.lbl_roi_info.setText(f"Loaded annotation ({src}).")
        self._update_orientation_label()

    def _load_sample_preview(self) -> None:
        path = self._sample_file_path()
        if path is None or not path.exists():
            QMessageBox.warning(self, "Load", "File not found.")
            return
        if self._project_root is None or self._current_sample is None:
            return
        sid = str(self._current_sample["sample_id"])
        ann = get_sample_annotation(self._project_root, sid)
        ref_idx = int(ann.get("reference_frame_index", 0)) if ann else 0
        try:
            frame, idx, total = load_media_frame(path, ref_idx)
        except MediaLoadError as e:
            QMessageBox.critical(self, "Load", str(e))
            return
        self._base_frame = frame
        self._frame_index = idx
        self._reference_frame_index = idx
        self._total_frames = total
        self._orientation = OrientationState()

        self.slider_frame.setMaximum(max(0, total - 1))
        self.spin_frame.setMaximum(max(0, total - 1))
        self.slider_frame.setValue(idx)
        self.spin_frame.setValue(idx)
        h, w = frame.shape[:2]
        self.lbl_frame_info.setText(f"Frame {idx}/{max(0, total-1)} ({w}×{h})")
        self.lbl_selected_file.setText(
            f"{sid}\n{self._current_sample['original_filename']}"
        )
        auto_name = str(self._current_sample.get("auto_export_name", ""))
        final_name = str(self._current_sample.get("final_export_name", ""))
        custom = str(self._current_sample.get("custom_export_name", ""))
        self.lbl_auto_export_name.setText(f"Auto name: {auto_name or '—'}")
        self.edit_export_name.blockSignals(True)
        self.edit_export_name.setText(custom or final_name or auto_name)
        self.edit_export_name.blockSignals(False)

        if ann:
            self._restore_annotation(ann)
        else:
            self._refresh_display(keep_roi=False)
            oriented = self._oriented_frame()
            if oriented is not None:
                try:
                    crop = detect_tracking_crop(oriented)
                    if crop.confidence >= AUTO_APPLY_ROI_CONFIDENCE:
                        self.canvas.set_rect_roi(tracking_crop_to_rect(crop))
                except ValueError:
                    pass

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
        roi = self.canvas.rect_roi()
        try:
            frame, idx, total = load_media_frame(path, index)
        except MediaLoadError as e:
            QMessageBox.critical(self, "Load", str(e))
            return
        self._base_frame = frame
        self._frame_index = idx
        self._total_frames = total
        self._refresh_display(keep_roi=True)
        if roi is not None:
            oriented = self._oriented_frame()
            if oriented is not None:
                self.canvas.set_rect_roi(
                    roi.clamp(oriented.shape[1], oriented.shape[0])
                )
        h, w = frame.shape[:2]
        self.lbl_frame_info.setText(f"Frame {idx}/{max(0, total-1)} ({w}×{h})")

    def _on_set_reference_frame(self) -> None:
        self._reference_frame_index = self._frame_index
        self._status(f"Reference frame = {self._frame_index}")

    def _refresh_recent_menu(self) -> None:
        refresh_recent_workspaces_menu(self)

    def _on_export_name_edited(self) -> None:
        if self._project_root is None or self._current_sample is None:
            return
        sid = str(self._current_sample["sample_id"])
        auto_name = str(self._current_sample.get("auto_export_name", ""))
        text = self.edit_export_name.text().strip()
        custom = None if text == auto_name or not text else text
        try:
            result = set_custom_export_name(self._project_root, sid, custom)
            self._current_sample.update(result)
            update_samples_csv(
                self._project_root / METADATA_DIR / SAMPLES_CSV,
                {"sample_id": sid, **result},
            )
            self._status(f"Export name: {result['final_export_name']}")
        except ValueError as e:
            QMessageBox.warning(self, "Export Name", str(e))
            self.edit_export_name.setText(
                str(self._current_sample.get("final_export_name", auto_name))
            )

    def _menu_new_workspace(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "New workspace folder", str(self._workspace_root)
        )
        if folder:
            root = Path(folder)
            create_project_structure(root)
            self._load_project(root, "New workspace created")

    def _menu_refresh_workspace(self) -> None:
        if self._project_root is None:
            return
        migrate_workspace_schema(self._project_root)
        repair_batch_registry(self._project_root)
        pruned = prune_all_groups_without_samples(self._project_root)
        self._refresh_sample_list()
        msg = "Workspace refreshed"
        if pruned:
            parts = ", ".join(f"{g} ({n})" for g, n in pruned.items())
            msg += f"; removed orphan batch label(s): {parts}"
        self._status(msg)

    def _menu_open_workspace_folder(self) -> None:
        if self._project_root is None:
            return
        import subprocess
        import sys

        path = str(self._project_root)
        if sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        elif sys.platform.startswith("win"):
            subprocess.run(["explorer", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)

    def _after_purge_refresh(self, *, prefer_sample_id: str | None = None) -> None:
        if self._project_root is not None:
            prune_all_groups_without_samples(self._project_root)
        if prefer_sample_id:
            self._current_sample = {"sample_id": prefer_sample_id}
        self._refresh_sample_list()

    def _ask_remove_workspace_raw(self, title: str, text: str) -> bool | None:
        """Return True to remove raw copy, False to keep, None if cancelled."""
        chk = QCheckBox("Also remove workspace raw copy in raw/")
        chk.setChecked(False)
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setCheckBox(chk)
        box.setStandardButtons(
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
        )
        if box.exec() != QMessageBox.StandardButton.Ok:
            return None
        return chk.isChecked()

    def _confirm_typed_phrase(
        self,
        title: str,
        message: str,
        phrase: str,
    ) -> bool:
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(message))
        layout.addWidget(QLabel(f'Type "{phrase}" to confirm:'))
        edit = QLineEdit()
        layout.addWidget(edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        return edit.text().strip() == phrase

    def _show_purge_summary(self, title: str, stats: dict[str, Any]) -> None:
        lines = [f"  • {k}: {v}" for k, v in stats.items() if v not in (None, "", [])]
        QMessageBox.information(
            self,
            title,
            "Operation finished.\n\n" + ("\n".join(lines) if lines else "Done."),
        )

    def _on_sample_list_context_menu(self, pos) -> None:
        if self._project_root is None:
            return
        item = self.list_samples.itemAt(pos)
        menu = QMenu(self)
        meta = self._list_item_meta(item)

        if meta and meta.get("item_type") == "sample":
            sid = str(meta.get("sample_id", ""))
            menu.addAction(
                "Delete File from Batch",
                lambda: self._ctx_delete_file(sid, meta),
            )
            menu.addSeparator()
            menu.addAction(
                "Purge File Annotations Only",
                lambda: self._ctx_purge_file_annotations(sid),
            )
            menu.addAction(
                "Purge Selected File Completely",
                lambda: self._ctx_purge_file_complete(sid, meta),
            )
        elif meta and meta.get("item_type") == "batch_header":
            group = str(meta.get("group", self._ensure_filter_group_valid()))
            batch_name = str(meta.get("batch_name", ""))
            menu.addAction(
                "Delete Batch",
                lambda: self._ctx_delete_batch(group, batch_name),
            )
            menu.addSeparator()
            menu.addAction(
                "Purge Batch Annotations Only",
                lambda: self._ctx_purge_batch_annotations(group, batch_name),
            )
            menu.addAction(
                "Complete Batch Purge",
                lambda: self._ctx_complete_batch_purge(group, batch_name),
            )
        else:
            menu.addAction("Create Batch…", self._on_new_batch)

        if not menu.isEmpty():
            menu.exec(self.list_samples.mapToGlobal(pos))

    def _ctx_purge_file_annotations(self, sample_id: str) -> None:
        if self._project_root is None:
            return
        reply = QMessageBox.question(
            self,
            "Purge File Annotations",
            "Clear annotations, previews, and processed outputs for this file?\n\n"
            "The file entry and workspace raw copy will be kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            stats = purge_sample_annotations_only(self._project_root, sample_id)
            self._after_purge_refresh(prefer_sample_id=sample_id)
            self._show_purge_summary("Purge Complete", stats)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Purge", str(e))

    def _ctx_purge_file_complete(
        self, sample_id: str, meta: dict[str, Any]
    ) -> None:
        if self._project_root is None:
            return
        reply = QMessageBox.question(
            self,
            "Purge Selected File Completely",
            "Remove this file from the app database and delete its annotations, "
            "previews, and processed outputs?\n\n"
            "Original external source files will not be deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        remove_raw = self._ask_remove_workspace_raw(
            "Workspace Raw Copy",
            "Keep or remove the copied file in the workspace raw/ folder?",
        )
        if remove_raw is None:
            return
        try:
            stats = purge_sample_completely(
                self._project_root,
                sample_id,
                remove_workspace_raw=remove_raw,
            )
            group = str(meta.get("group", ""))
            batch_name = str(meta.get("batch_name", ""))
            self._current_sample = None
            self._after_purge_refresh()
            self._show_purge_summary("Purge Complete", stats)
            if group and batch_name and not batch_has_samples(
                self._project_root, group, batch_name
            ):
                if (
                    QMessageBox.question(
                        self,
                        "Empty Batch",
                        f"Batch '{batch_name}' is now empty. Delete the batch label too?",
                        QMessageBox.StandardButton.Yes
                        | QMessageBox.StandardButton.No,
                    )
                    == QMessageBox.StandardButton.Yes
                ):
                    delete_empty_batch(self._project_root, group, batch_name)
                    self._refresh_sample_list()
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Purge", str(e))

    def _ctx_delete_file(self, sample_id: str, meta: dict[str, Any]) -> None:
        if self._project_root is None:
            return
        reply = QMessageBox.question(
            self,
            "Delete File from Batch",
            "Delete this file from the batch? This will remove its metadata, "
            "annotations, previews, and processed outputs. Raw workspace copy "
            "will be kept unless you choose to remove it.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        remove_raw = self._ask_remove_workspace_raw(
            "Workspace Raw Copy",
            "Keep or remove the copied file in the workspace raw/ folder?",
        )
        if remove_raw is None:
            return
        try:
            delete_sample_from_batch(
                self._project_root,
                sample_id,
                remove_workspace_raw=remove_raw,
            )
            group = str(meta.get("group", ""))
            batch_name = str(meta.get("batch_name", ""))
            self._current_sample = None
            self._after_purge_refresh()
            self._status(f"Deleted {sample_id} from batch")
            if group and batch_name and not batch_has_samples(
                self._project_root, group, batch_name
            ):
                if (
                    QMessageBox.question(
                        self,
                        "Empty Batch",
                        f"Batch '{batch_name}' is now empty. Delete the batch label too?",
                        QMessageBox.StandardButton.Yes
                        | QMessageBox.StandardButton.No,
                    )
                    == QMessageBox.StandardButton.Yes
                ):
                    delete_empty_batch(self._project_root, group, batch_name)
                    self._refresh_sample_list()
        except (ValueError, OSError) as e:
            QMessageBox.critical(self, "Delete Failed", str(e))

    def _ctx_purge_batch_annotations(self, group: str, batch_name: str) -> None:
        if self._project_root is None:
            return
        reply = QMessageBox.question(
            self,
            "Purge Batch Annotations",
            f"Clear annotations and processed outputs for batch '{batch_name}'?\n\n"
            "File entries and workspace raw copies will be kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            stats = purge_batch_annotations(self._project_root, group, batch_name)
            self._after_purge_refresh()
            self._show_purge_summary("Purge Complete", stats)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Purge", str(e))

    def _ctx_complete_batch_purge(self, group: str, batch_name: str) -> None:
        if self._project_root is None:
            return
        if not self._confirm_typed_phrase(
            "Complete Batch Purge",
            "This will completely remove this batch from the workspace. It will delete "
            "the batch label, all file entries in the app database, all annotations, "
            "previews, and processed outputs for this batch. Workspace raw copies can "
            "also be deleted if you choose. Original external source files will not be "
            "touched. This cannot be undone.",
            "PURGE BATCH",
        ):
            QMessageBox.information(
                self, "Cancelled", 'Type exactly "PURGE BATCH" to run this action.'
            )
            return
        remove_raw = self._ask_remove_workspace_raw(
            "Workspace Raw Copies",
            "Also remove workspace raw copies for this batch?",
        )
        if remove_raw is None:
            return
        try:
            stats = complete_batch_purge(
                self._project_root,
                group,
                batch_name,
                remove_workspace_raw=remove_raw,
            )
            self._current_sample = None
            self._after_purge_refresh()
            self._show_purge_summary("Complete Batch Purge", stats)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Purge", str(e))

    def _ctx_delete_batch(self, group: str, batch_name: str) -> None:
        if self._project_root is None:
            return
        has_files = batch_has_samples(self._project_root, group, batch_name)
        if has_files:
            understand = QCheckBox(
                "I understand this will remove the whole batch from the workspace database."
            )
            box = QMessageBox(self)
            box.setWindowTitle("Delete Batch")
            box.setText(
                "Delete this entire batch? This will remove all files in the batch from "
                "the app database and delete all annotations, previews, and processed "
                "outputs for the batch. Raw workspace copies will be kept unless you "
                "choose to remove them. Original external files will not be touched."
            )
            box.setCheckBox(understand)
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if (
                box.exec() != QMessageBox.StandardButton.Yes
                or not understand.isChecked()
            ):
                return
            remove_raw = self._ask_remove_workspace_raw(
                "Workspace Raw Copies",
                "Also remove workspace raw copies for all files in this batch?",
            )
            if remove_raw is None:
                return
            try:
                stats = complete_batch_purge(
                    self._project_root,
                    group,
                    batch_name,
                    remove_workspace_raw=remove_raw,
                )
                self._current_sample = None
                self._after_purge_refresh()
                self._show_purge_summary("Batch Deleted", stats)
            except (ValueError, OSError) as e:
                QMessageBox.warning(self, "Delete Batch", str(e))
            return

        reply = QMessageBox.question(
            self,
            "Delete Empty Batch",
            f"Delete empty batch '{batch_name}' from this condition group?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_empty_batch(self._project_root, group, batch_name)
            self._after_purge_refresh()
            self._status(f"Deleted empty batch {batch_name}")
        except ValueError as e:
            QMessageBox.warning(self, "Delete Batch", str(e))

    def _menu_purge_filtered(self) -> None:
        if self._project_root is None:
            return
        dlg = PurgeFilteredDialog(self, self._project_root)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        ids = dlg.selected_sample_ids()
        if not ids:
            QMessageBox.information(self, "Purge", "No samples match the filters.")
            return
        reply = QMessageBox.question(
            self,
            "Confirm Filtered Purge",
            f"Purge annotations/processed for {len(ids)} sample(s)?\n"
            "Raw files will be kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        stats = purge_filtered_samples(self._project_root, ids)
        self._refresh_sample_list()
        QMessageBox.information(
            self,
            "Purge Complete",
            f"Updated {stats['samples_updated']} sample(s).",
        )

    def _menu_delete_empty_batch(self) -> None:
        if self._project_root is None:
            return
        group = self._ensure_filter_group_valid()
        batch_name = pick_empty_batch_name(self, self._project_root, group)
        if not batch_name:
            return
        reply = QMessageBox.question(
            self,
            "Delete Empty Batch",
            f"Delete empty batch '{batch_name}' from this condition group?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_empty_batch(self._project_root, group, batch_name)
            self._after_purge_refresh()
            self._status(f"Deleted empty batch {batch_name}")
        except ValueError as e:
            QMessageBox.warning(self, "Delete Batch", str(e))

    def _menu_delete_file_from_batch(self) -> None:
        if self._project_root is None or self._current_sample is None:
            QMessageBox.warning(self, "Delete", "Select a file in the batch list first.")
            return
        sid = str(self._current_sample["sample_id"])
        self._ctx_delete_file(sid, self._current_sample)

    def _menu_review_batch(self) -> None:
        self._refresh_sample_list()
        self._status(
            "Review propagated annotations using Approve / Reject on each file."
        )

    def _menu_how_to_run(self) -> None:
        readme = APP_ROOT / "README.md"
        text = (
            "From the ActinTrackCV project folder:\n\n"
            "  ./run_app.sh\n"
            "  python run_app.py\n"
            "  python -m actintrack_app.main\n"
        )
        if readme.is_file():
            text += f"\nSee {readme} for dependencies and workspace setup."
        QMessageBox.information(self, "How to Run", text)

    def _menu_about(self) -> None:
        QMessageBox.about(
            self,
            "About ActinTrackCV",
            "ActinTrackCV — Arabidopsis F-actin fluorescence microscopy: 2D preprocessing, "
            "orientation, ROI annotation, and cropped export for actin cable analysis.",
        )

    def _confirm_project_root_if_source_folder(self, root: Path) -> Optional[Path]:
        if root.resolve() != DEFAULT_SOURCE_ROOT.resolve():
            return root
        reply = QMessageBox.question(
            self,
            "Use workspace?",
            "Use workspace root instead of raw_source?",
        )
        if reply == QMessageBox.StandardButton.Yes:
            return self._workspace_root
        return root if reply == QMessageBox.StandardButton.No else None


def run_app() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("ActinTrackCV")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
