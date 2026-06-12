"""PyQt6 GUI — 2D Arabidopsis F-actin preprocessing and ROI annotation."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt, QTimer
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
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QSizePolicy,
    QWidget,
)

from actintrack_app.analysis_service import AnalysisReport, build_analysis_report
from actintrack_app.analysis_view import AnalysisViewWidget
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
    batch_has_samples,
    delete_empty_batch,
    display_batch_name,
    display_sample_label,
    ensure_default_batch,
    get_batch_by_name,
    list_batches,
    parse_batch_number_from_name,
    rename_batch,
    repair_batch_registry,
    sanitize_batch_name,
    sync_registry_from_samples,
)
from actintrack_app.file_importer import set_custom_export_name
from actintrack_app.gui_menus import (
    PurgeFilteredDialog,
    refresh_recent_workspaces_menu,
    setup_application_menus,
)
from actintrack_app.gui_canvas import ImageCanvas
from actintrack_app.image_processing import TrackingCrop, detect_tracking_crop
from actintrack_app.export_naming import motion_index_summary_json_path
from actintrack_app.metadata import (
    load_samples_csv,
    get_sample_annotation,
    load_crop_metadata,
    migrate_workspace_schema,
    remove_samples_from_metadata,
    save_sample_crop_annotation,
    sync_samples_with_disk,
    update_samples_csv,
)
from actintrack_app.purge_cleanup_dialog import pick_empty_batch_name
from actintrack_app.sample_service import (
    DATA_IMPORT_FILTER,
    create_sample_from_data,
    delete_sample_and_artifacts,
    get_primary_data_row,
    replace_sample_data,
    sample_has_derived_state,
)
from actintrack_app.purge_manager import (
    complete_batch_purge,
    delete_sample_from_batch,
    purge_batch_annotations,
    purge_filtered_samples,
    purge_sample_annotations_only,
    purge_sample_completely,
)
from actintrack_app.recent_workspaces import add_recent
from actintrack_app.user_preferences import get_last_import_breed, set_last_import_breed
from actintrack_app.orientation import (
    OrientationState,
    RectROI,
    apply_orientation,
    tracking_crop_to_rect,
)
from actintrack_app.project_manager import (
    create_project_structure,
    get_processed_batch_dir,
    is_valid_project,
)
from actintrack_app.motion_index import MotionIndexParams
from actintrack_app.optical_flow_motion_index import (
    OpticalFlowResult,
    OpticalFlowSettings,
    build_optical_flow_fingerprint,
    compute_optical_flow_motion_index,
    result_from_dict,
    result_to_dict,
)
from actintrack_app.optical_flow_overlay import (
    OpticalFlowFlowCache,
    OpticalFlowVisualizationSettings,
    build_flow_cache,
    format_optical_flow_qc,
    get_flow_arrows_for_frame,
    render_optical_flow_overlay,
    resolve_qc_status,
)
from actintrack_app.preview_workflow import (
    CroppedPreviewAnalysis,
    analyze_cropped_preview,
    is_supported_video_path,
    load_cropped_frames_from_video,
    render_cropped_tracking_frame,
)
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
    STATUS_MOTION_INDEX_FAILED,
    STATUS_MOTION_INDEX_GENERATED,
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
DRAFT_TRACKING_DIR = "draft_tracking"
METRIC_DEBOUNCE_MS = 5000
_METRIC_ANALYSIS_VIEW_LABEL = "Metric Analysis View"

_ADVANCED_SAMPLE_STATUSES = frozenset(
    {
        STATUS_PROCESSED,
        STATUS_MOTION_INDEX_GENERATED,
        STATUS_MOTION_INDEX_FAILED,
    }
)
_ROI_STATUS_UPGRADE_FROM = frozenset(
    {
        STATUS_RAW_IMPORTED,
        STATUS_IMPORTED,
        STATUS_UNANNOTATED,
    }
)


@dataclass(frozen=True)
class _TrackingRunSnapshot:
    sample_id: str
    roi_key: tuple[int, int, int, int]
    params_key: tuple[tuple[str, Any], ...]
    orientation_key: tuple[float, bool, bool]
    video_path: str
    run_token: int


@dataclass(frozen=True)
class _OpticalFlowRunSnapshot:
    sample_id: str
    roi_key: tuple[int, int, int, int]
    settings_key: tuple[tuple[str, Any], ...]
    orientation_key: tuple[float, bool, bool]
    video_path: str
    run_token: int


@dataclass
class SampleTrackingResultView:
    """Display-ready tracking/index values for one sample."""

    status: str  # success, failed, none
    downward_velocity: float = 0.0
    general_movement: float = 0.0
    tracks_used: int = 0
    tracks_requested: int = 0
    valid_steps: int = 0
    failure_reason: str = ""


@dataclass
class OpticalFlowResultView:
    """Display-ready optical-flow motion index values for one sample."""

    status: str  # success, failed, none
    general_movement: Optional[float] = None
    downward_motion: Optional[float] = None
    net_y_velocity: Optional[float] = None
    directionality_ratio: Optional[float] = None
    valid_pixel_fraction: Optional[float] = None
    saturated_pixel_fraction: Optional[float] = None
    failure_reason: str = ""

def _optional_gui_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_optional_float(value: Optional[float], *, places: int = 4) -> str:
    if value is None:
        return "—"
    return f"{value:.{places}f}"


STATUS_COLORS = {
    STATUS_IMPORTED: QColor("#bbbbbb"),
    STATUS_RAW_IMPORTED: QColor("#bbbbbb"),
    STATUS_UNANNOTATED: QColor("#aaaaaa"),
    "cutoff_marked": QColor("#c9b84c"),
    STATUS_ROI_MARKED: QColor("#6aa8ff"),
    STATUS_ROI_PROPAGATED: QColor("#ff9944"),
    STATUS_ROI_APPROVED: QColor("#66dd88"),
    STATUS_PROCESSED: QColor("#3ddc84"),
    STATUS_MOTION_INDEX_GENERATED: QColor("#2ec4b6"),
    STATUS_MOTION_INDEX_FAILED: QColor("#e07070"),
    "missing_file": QColor("#cc6666"),
}


class PropagateDialog(QDialog):
    def __init__(self, parent: QWidget, group: str, batch_name: str):
        super().__init__(parent)
        self.setWindowTitle("Propagate Annotation to Sample")
        layout = QFormLayout(self)
        num = parse_batch_number_from_name(batch_name) or 1
        sample_label = display_sample_label(num, batch_name)
        help_lbl = QLabel(
            "By default, annotations apply only within the same sample, "
            "not across other samples in the breed."
        )
        help_lbl.setWordWrap(True)
        layout.addRow(help_lbl)
        self.combo_scope = QComboBox()
        self.combo_scope.addItems(
            [
                f"Same sample ({sample_label})",
                f"Unprocessed data in {sample_label}",
                f"All data in breed {group}",
                "Currently selected data in list",
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
        if text.startswith("Same sample"):
            return SCOPE_SAME_BATCH
        if text.startswith("Unprocessed"):
            return SCOPE_UNPROCESSED_IN_BATCH
        if text.startswith("All data in breed"):
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
        self._current_sample_id: Optional[str] = None
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
        self._last_import_breed: Optional[str] = None
        self._roi_user_adjusted = False
        self._loaded_annotation_source = "manual"
        self._last_motion_index_result: Optional[Any] = None
        self._preview_mode = "full"
        self._preview_playing = False
        self._preview_frame_index = 0
        self._cropped_preview: Optional[CroppedPreviewAnalysis] = None
        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._on_preview_timer_tick)
        self._roi_autosave_pending = False
        self._tracking_results_by_sample: dict[str, CroppedPreviewAnalysis] = {}
        self._tracking_result_stale_by_sample: dict[str, bool] = {}
        self._pending_tracking_snapshot: Optional[_TrackingRunSnapshot] = None
        self._tracking_run_token = 0
        self._tracking_job_running = False
        self._cropped_metric_mode = "template"
        self._metric_analysis_view_active = False
        self._optical_flow_results_by_sample: dict[str, OpticalFlowResult] = {}
        self._optical_flow_stale_by_sample: dict[str, bool] = {}
        self._optical_flow_run_token = 0
        self._optical_flow_job_running = False
        self._pending_optical_flow_snapshot: Optional[_OpticalFlowRunSnapshot] = None
        self._metric_debounce_timer = QTimer(self)
        self._metric_debounce_timer.setSingleShot(True)
        self._metric_debounce_timer.setInterval(METRIC_DEBOUNCE_MS)
        self._metric_debounce_timer.timeout.connect(self._on_metric_debounce_fired)
        self._metric_settings_timer = QTimer(self)
        self._metric_settings_timer.setSingleShot(True)
        self._metric_settings_timer.setInterval(METRIC_DEBOUNCE_MS)
        self._metric_settings_timer.timeout.connect(
            self._on_metric_settings_debounce_fired
        )
        self._of_flow_caches: dict[str, OpticalFlowFlowCache] = {}

        self._build_ui()
        self._set_tracking_settings_editable(False)
        setup_application_menus(self)
        self._load_project(self._workspace_root, "Workspace project loaded")

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left_sidebar())
        self._preview_page = QWidget()
        preview_page = self._preview_page
        center_layout = QVBoxLayout(preview_page)
        self.lbl_preview_mode = QLabel(
            "Full Sample Preview — orient the data and draw a rectangle around "
            "the usable actin-rich region."
        )
        self.lbl_preview_mode.setWordWrap(True)
        center_layout.addWidget(self.lbl_preview_mode)

        metric_mode_row = QHBoxLayout()
        self.lbl_metric_mode = QLabel("Preview mode:")
        self.combo_metric_mode = QComboBox()
        self.combo_metric_mode.addItem("Template Tracking", "template")
        self.combo_metric_mode.addItem("Optical Flow (Draft)", "optical_flow")
        self.combo_metric_mode.currentIndexChanged.connect(self._on_cropped_metric_mode_changed)
        metric_mode_row.addWidget(self.lbl_metric_mode)
        metric_mode_row.addWidget(self.combo_metric_mode)
        metric_mode_row.addStretch()
        self._metric_mode_widgets = (
            self.lbl_metric_mode,
            self.combo_metric_mode,
        )
        for widget in self._metric_mode_widgets:
            widget.hide()
        center_layout.addLayout(metric_mode_row)

        self.canvas = ImageCanvas(self)
        center_layout.addWidget(self.canvas, stretch=1)

        preview_crop_row = QHBoxLayout()
        preview_crop_row.addStretch()
        self.btn_metric_analysis = self._tool_button(
            _METRIC_ANALYSIS_VIEW_LABEL,
            "Open the cropped ROI metric analysis view with Template Tracking "
            "and Optical Flow metrics, overlay, and playback.",
            self._on_show_metric_analysis_view,
        )
        self.btn_metric_analysis.hide()
        preview_crop_row.addWidget(self.btn_metric_analysis)
        preview_crop_row.addStretch()
        center_layout.addLayout(preview_crop_row)

        preview_controls = QVBoxLayout()
        preview_controls.setSpacing(4)
        preview_transport_row = QHBoxLayout()
        preview_speed_row = QHBoxLayout()
        self.btn_preview_play = QPushButton("Play")
        self.btn_preview_play.clicked.connect(self._preview_play)
        self.btn_preview_pause = QPushButton("Pause")
        self.btn_preview_pause.clicked.connect(self._preview_pause)
        self.lbl_cropped_frame = QLabel("Frame 1 / 1")
        self.lbl_cropped_frame.setMinimumWidth(72)
        self.slider_cropped_frame = QSlider(Qt.Orientation.Horizontal)
        self.slider_cropped_frame.setMinimumWidth(120)
        self.slider_cropped_frame.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.slider_cropped_frame.valueChanged.connect(self._on_cropped_preview_frame_slider)
        self.lbl_preview_speed = QLabel("Speed:")
        self.combo_preview_speed = QComboBox()
        self.combo_preview_speed.addItems(["0.25×", "0.5×", "1×", "1.5×", "2×"])
        self.combo_preview_speed.setCurrentText("1×")
        self.combo_preview_speed.currentTextChanged.connect(
            self._on_preview_speed_changed
        )
        self.combo_preview_speed.setMinimumWidth(72)
        self.combo_preview_speed.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.btn_return_full_preview = QPushButton("Return to Full Preview")
        self.btn_return_full_preview.clicked.connect(self._exit_cropped_preview_mode)
        self.btn_return_full_preview.setSizePolicy(
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Fixed,
        )
        for widget in (
            self.btn_preview_play,
            self.btn_preview_pause,
            self.lbl_cropped_frame,
            self.slider_cropped_frame,
            self.lbl_preview_speed,
            self.combo_preview_speed,
            self.btn_return_full_preview,
        ):
            widget.hide()
        preview_transport_row.addWidget(self.btn_preview_play)
        preview_transport_row.addWidget(self.btn_preview_pause)
        preview_transport_row.addWidget(self.lbl_cropped_frame)
        preview_transport_row.addWidget(self.slider_cropped_frame, stretch=1)
        preview_speed_row.addWidget(self.lbl_preview_speed)
        preview_speed_row.addWidget(self.combo_preview_speed)
        preview_speed_row.addStretch()
        preview_speed_row.addWidget(self.btn_return_full_preview)
        preview_controls.addLayout(preview_transport_row)
        preview_controls.addLayout(preview_speed_row)
        center_layout.addLayout(preview_controls)
        self._preview_control_widgets = (
            self.btn_preview_play,
            self.btn_preview_pause,
            self.lbl_cropped_frame,
            self.slider_cropped_frame,
            self.lbl_preview_speed,
            self.combo_preview_speed,
            self.btn_return_full_preview,
        )
        self._analysis_view = AnalysisViewWidget()
        self._center_stack = QStackedWidget()
        self._center_stack.addWidget(preview_page)
        self._center_stack.addWidget(self._analysis_view)
        splitter.addWidget(self._center_stack)
        splitter.addWidget(self._build_right_sidebar())
        splitter.setSizes([260, 780, 260])
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

    def _build_right_sidebar(self) -> QStackedWidget:
        """Normal tabbed controls, or full-column Advanced Tracking Settings."""
        stack = QStackedWidget()
        stack.setMinimumWidth(260)
        stack.setMaximumWidth(380)

        self._right_tabs = QTabWidget()
        preview = QWidget()
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(6, 6, 6, 6)
        preview_layout.addWidget(self._build_frame_panel())
        preview_layout.addWidget(self._build_selected_panel())
        preview_layout.addStretch()
        self._right_tabs.addTab(preview, "Frame")

        roi_tab = QWidget()
        roi_layout = QVBoxLayout(roi_tab)
        roi_layout.setContentsMargins(6, 6, 6, 6)
        roi_layout.addWidget(self._build_unified_orient_roi_panel())
        roi_layout.addStretch()
        self._right_tabs.addTab(roi_tab, "Orient && ROI")

        sample_tab = QWidget()
        sample_layout = QVBoxLayout(sample_tab)
        sample_layout.setContentsMargins(6, 6, 6, 6)
        sample_layout.addWidget(self._build_tracking_result_panel())
        sample_layout.addWidget(self._build_notes_panel())
        sample_layout.addStretch()
        self._right_tabs.addTab(sample_tab, "Sample")

        analysis_tab = QWidget()
        analysis_tab_layout = QVBoxLayout(analysis_tab)
        analysis_tab_layout.setContentsMargins(6, 6, 6, 6)
        analysis_hint = QLabel(
            "Breed and sample tracking metrics appear in the center column. "
            "Results are loaded from saved data; tracking is not re-run here."
        )
        analysis_hint.setWordWrap(True)
        analysis_hint.setStyleSheet("color: #666; font-size: 11px;")
        analysis_tab_layout.addWidget(analysis_hint)
        self.btn_refresh_analysis = QPushButton("Refresh Analysis")
        self.btn_refresh_analysis.setToolTip(
            "Reload analysis tables from saved tracking and motion-index results."
        )
        self.btn_refresh_analysis.clicked.connect(self.refresh_analysis_view)
        analysis_tab_layout.addWidget(self.btn_refresh_analysis)
        analysis_tab_layout.addStretch()
        self._right_tabs.addTab(analysis_tab, "Analysis")

        self._right_tabs.currentChanged.connect(self._on_right_tab_changed)

        stack.addWidget(self._right_tabs)
        stack.addWidget(self._build_tracking_settings_page())
        stack.addWidget(self._build_optical_flow_settings_page())
        self._right_stack = stack
        return stack

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
        layout.addWidget(QLabel("Breed:"))
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
            "Select the previous data entry in the list.",
            self._on_prev_sample,
        )
        self.btn_next_sample = self._tool_button(
            "Next ▶",
            "Select the next data entry in the list.",
            self._on_next_sample,
        )
        nav.addWidget(self.btn_prev_sample)
        nav.addWidget(self.btn_next_sample)
        layout.addLayout(nav)
        hint = QLabel(
            "All samples for the selected breed are listed together. "
            "Right-click to add a sample or import data."
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
        box = QGroupBox("Selected Data File")
        layout = QVBoxLayout(box)
        self.lbl_selected_file = QLabel("No data selected")
        self.lbl_selected_file.setWordWrap(True)
        layout.addWidget(self.lbl_selected_file)
        layout.addWidget(QLabel("Export name:"))
        self.edit_export_name = QLineEdit()
        self.edit_export_name.setPlaceholderText("auto-generated from breed and sample")
        self.edit_export_name.editingFinished.connect(self._on_export_name_edited)
        layout.addWidget(self.edit_export_name)
        self.lbl_auto_export_name = QLabel("Auto name: —")
        self.lbl_auto_export_name.setWordWrap(True)
        self.lbl_auto_export_name.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self.lbl_auto_export_name)
        return box

    @staticmethod
    def _configure_orient_roi_control(widget: QWidget) -> None:
        widget.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
        if isinstance(widget, QDoubleSpinBox):
            widget.setMaximumWidth(72)

    def _build_unified_orient_roi_panel(self) -> QGroupBox:
        box = QGroupBox("Orient and ROI")
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        custom = QHBoxLayout()
        angle_label = QLabel("Rotation:")
        angle_label.setSizePolicy(
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Fixed,
        )
        custom.addWidget(angle_label)
        self.spin_custom_angle = QDoubleSpinBox()
        self.spin_custom_angle.setRange(-180, 180)
        self.spin_custom_angle.setDecimals(1)
        self._configure_orient_roi_control(self.spin_custom_angle)
        self.btn_apply_custom = QPushButton("Apply")
        self.btn_apply_custom.clicked.connect(self._on_apply_custom_angle)
        self._configure_orient_roi_control(self.btn_apply_custom)
        custom.addWidget(self.spin_custom_angle)
        custom.addWidget(self.btn_apply_custom)
        custom.addStretch()
        layout.addLayout(custom)

        self.chk_mirror_y = QCheckBox("Mirror Y-Axis")
        self.chk_mirror_y.setToolTip("Mirror the data left-right before ROI and tracking.")
        self.chk_mirror_y.toggled.connect(self._on_mirror_y_axis)
        layout.addWidget(self.chk_mirror_y)

        orient_extras = QHBoxLayout()
        self.btn_flip = QPushButton("Flip 180°")
        self.btn_flip.clicked.connect(self._on_flip_180)
        self.btn_reset_orientation = QPushButton("Reset Orientation")
        self.btn_reset_orientation.clicked.connect(self._on_reset_orientation)
        orient_extras.addWidget(self.btn_flip)
        orient_extras.addWidget(self.btn_reset_orientation)
        layout.addLayout(orient_extras)

        self.btn_auto_roi = QPushButton("Suggest ROI from F-actin Signal")
        self.btn_auto_roi.setToolTip(
            "Suggest a rectangular region with strong visible F-actin signal. "
            "Review and adjust before export."
        )
        self.btn_auto_roi.clicked.connect(self._on_auto_suggest_roi)
        layout.addWidget(self.btn_auto_roi)

        self.btn_clear_roi = QPushButton("Clear ROI")
        self.btn_clear_roi.setToolTip("Remove the current ROI rectangle from the preview.")
        self.btn_clear_roi.clicked.connect(self._on_clear_roi)
        layout.addWidget(self.btn_clear_roi)

        self.btn_process = self._tool_button(
            "Export ROI",
            "Crop and export processed outputs to the processed/ folder.",
            self._on_process_sample,
        )
        layout.addWidget(self.btn_process)

        self.lbl_roi_save_status = QLabel("—")
        self.lbl_roi_save_status.setWordWrap(True)
        self._set_roi_save_status("No ROI saved yet", saved=False)
        layout.addWidget(self.lbl_roi_save_status)
        return box

    @staticmethod
    def _configure_tracking_field(widget: QWidget, *, full_column: bool = False) -> None:
        widget.setMinimumWidth(160 if full_column else 140)
        widget.setMinimumHeight(36 if full_column else 30)
        policy = QSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        widget.setSizePolicy(policy)

    def _create_tracking_setting_widgets(self) -> None:
        defaults = MotionIndexParams()
        self.spin_track_points = QSpinBox()
        self.spin_track_points.setRange(1, 50)
        self.spin_track_points.setValue(defaults.num_starting_points)
        self.spin_track_points.setToolTip(
            "Number of bright F-actin signal points selected in the first frame."
        )

        self.spin_track_spacing = QSpinBox()
        self.spin_track_spacing.setRange(1, 200)
        self.spin_track_spacing.setValue(defaults.min_point_spacing_px)
        self.spin_track_spacing.setToolTip(
            "Minimum pixel distance between starting points so they are spread out."
        )

        self.spin_track_search = QSpinBox()
        self.spin_track_search.setRange(1, 100)
        self.spin_track_search.setValue(defaults.search_radius_px)
        self.spin_track_search.setToolTip(
            "Maximum pixel distance a point can move between frames."
        )

        self.spin_track_patch = QSpinBox()
        self.spin_track_patch.setRange(3, 101)
        self.spin_track_patch.setSingleStep(2)
        self.spin_track_patch.setValue(defaults.template_patch_size_px)
        self.spin_track_patch.setToolTip(
            "Size of the square image patch used for template matching. Must be odd."
        )

        self.spin_track_confidence = QDoubleSpinBox()
        self.spin_track_confidence.setRange(0.0, 1.0)
        self.spin_track_confidence.setDecimals(2)
        self.spin_track_confidence.setSingleStep(0.05)
        self.spin_track_confidence.setValue(defaults.min_template_confidence)
        self.spin_track_confidence.setToolTip(
            "Lowest accepted template-matching score."
        )

        self.spin_track_lookahead = QSpinBox()
        self.spin_track_lookahead.setRange(0, 3)
        self.spin_track_lookahead.setValue(defaults.lookahead_frames)
        self.spin_track_lookahead.setToolTip(
            "Number of future frames to check if a point is temporarily lost."
        )

        
        self.spin_track_mpp = QDoubleSpinBox()
        self.spin_track_mpp.setRange(0.001, 10.0)
        self.spin_track_mpp.setDecimals(4)
        self.spin_track_mpp.setValue(defaults.microns_per_pixel)
        self.spin_track_mpp.setToolTip(
            "Physical image scale used to convert pixels to microns."
        )

        self.spin_track_spf = QDoubleSpinBox()
        self.spin_track_spf.setRange(0.001, 60.0)
        self.spin_track_spf.setDecimals(4)
        self.spin_track_spf.setValue(defaults.seconds_per_frame)
        self.spin_track_spf.setToolTip(
            "Time interval between frames used to convert displacement to velocity."
        )

        self._tracking_setting_widgets = (
            self.spin_track_points,
            self.spin_track_spacing,
            self.spin_track_search,
            self.spin_track_patch,
            self.spin_track_confidence,
            self.spin_track_lookahead,
            self.spin_track_mpp,
            self.spin_track_spf,
        )
        for widget in self._tracking_setting_widgets:
            self._configure_tracking_field(widget, full_column=True)
            if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.valueChanged.connect(self._on_tracking_setting_changed)

    @staticmethod
    def _add_tracking_setting_row(
        layout: QVBoxLayout,
        label_text: str,
        widget: QWidget,
        tooltip: str,
    ) -> None:
        label = QLabel(label_text)
        label.setWordWrap(True)
        label.setToolTip(tooltip)
        widget.setToolTip(tooltip)
        layout.addWidget(label)
        layout.addWidget(widget)

    def _build_tracking_settings_form(self) -> QGroupBox:
        box = QGroupBox("Advanced Tracking Settings")
        box.setToolTip(
            "Draft point-tracking parameters used in Metric Analysis View."
        )
        layout = QVBoxLayout(box)
        layout.setSpacing(10)
        layout.setContentsMargins(8, 12, 8, 8)
        rows: list[tuple[str, QWidget, str]] = [
            ("Starting Points", self.spin_track_points, self.spin_track_points.toolTip()),
            (
                "Minimum Point Spacing (px)",
                self.spin_track_spacing,
                self.spin_track_spacing.toolTip(),
            ),
            (
                "Search Radius (px)",
                self.spin_track_search,
                self.spin_track_search.toolTip(),
            ),
            (
                "Template Patch Size (px)",
                self.spin_track_patch,
                self.spin_track_patch.toolTip(),
            ),
            (
                "Minimum Match Confidence",
                self.spin_track_confidence,
                self.spin_track_confidence.toolTip(),
            ),
            (
                "Lookahead Frames",
                self.spin_track_lookahead,
                self.spin_track_lookahead.toolTip(),
            ),
            ("Microns per Pixel", self.spin_track_mpp, self.spin_track_mpp.toolTip()),
            ("Seconds per Frame", self.spin_track_spf, self.spin_track_spf.toolTip()),
        ]
        for label_text, widget, tooltip in rows:
            self._add_tracking_setting_row(layout, label_text, widget, tooltip)
        layout.addStretch()
        return box

    def _build_tracking_settings_page(self) -> QWidget:
        self._create_tracking_setting_widgets()
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        hint = QLabel(
            "Edit tracking parameters below while previewing the cropped ROI. "
            "Changes auto-refresh tracking for the current sample."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)
        layout.addWidget(self._build_tracking_settings_form(), stretch=1)
        return page

    def _create_optical_flow_setting_widgets(self) -> None:
        defaults = OpticalFlowSettings()
        self.spin_of_mask_percentile = QDoubleSpinBox()
        self.spin_of_mask_percentile.setRange(0.0, 100.0)
        self.spin_of_mask_percentile.setDecimals(1)
        self.spin_of_mask_percentile.setValue(defaults.mask_percentile)
        self.spin_of_mask_percentile.setToolTip(
            "Include pixels brighter than this percentile in optical-flow averaging."
        )

        self.combo_of_blur = QComboBox()
        self.combo_of_blur.addItem("Off (0)", 0)
        self.combo_of_blur.addItem("3", 3)
        self.combo_of_blur.addItem("5", 5)
        self.combo_of_blur.setCurrentIndex(1)
        self.combo_of_blur.setToolTip("Light Gaussian blur applied before optical flow.")

        self.spin_of_pyr_scale = QDoubleSpinBox()
        self.spin_of_pyr_scale.setRange(0.01, 0.99)
        self.spin_of_pyr_scale.setDecimals(2)
        self.spin_of_pyr_scale.setSingleStep(0.05)
        self.spin_of_pyr_scale.setValue(defaults.pyr_scale)

        self.spin_of_levels = QSpinBox()
        self.spin_of_levels.setRange(1, 8)
        self.spin_of_levels.setValue(defaults.levels)

        self.spin_of_winsize = QSpinBox()
        self.spin_of_winsize.setRange(3, 99)
        self.spin_of_winsize.setSingleStep(2)
        self.spin_of_winsize.setValue(defaults.winsize)

        self.spin_of_iterations = QSpinBox()
        self.spin_of_iterations.setRange(1, 20)
        self.spin_of_iterations.setValue(defaults.iterations)

        self.spin_of_poly_n = QSpinBox()
        self.spin_of_poly_n.setRange(3, 15)
        self.spin_of_poly_n.setSingleStep(2)
        self.spin_of_poly_n.setValue(defaults.poly_n)

        self.spin_of_poly_sigma = QDoubleSpinBox()
        self.spin_of_poly_sigma.setRange(0.1, 5.0)
        self.spin_of_poly_sigma.setDecimals(2)
        self.spin_of_poly_sigma.setValue(defaults.poly_sigma)

        viz_defaults = OpticalFlowVisualizationSettings()
        self.chk_show_of_overlay = QCheckBox("Show Optical Flow Overlay")
        self.chk_show_of_overlay.setChecked(True)
        self.chk_show_of_overlay.setToolTip(
            "Draw sampled optical-flow arrows on the cropped ROI preview."
        )
        self.chk_show_of_overlay.toggled.connect(self._on_show_of_overlay_changed)

        self.spin_of_arrow_spacing = QSpinBox()
        self.spin_of_arrow_spacing.setRange(8, 40)
        self.spin_of_arrow_spacing.setValue(viz_defaults.arrow_spacing_px)
        self.spin_of_arrow_spacing.valueChanged.connect(self._on_of_viz_setting_changed)

        self.spin_of_arrow_scale = QDoubleSpinBox()
        self.spin_of_arrow_scale.setRange(0.1, 20.0)
        self.spin_of_arrow_scale.setDecimals(1)
        self.spin_of_arrow_scale.setSingleStep(0.5)
        self.spin_of_arrow_scale.setValue(viz_defaults.arrow_scale)
        self.spin_of_arrow_scale.valueChanged.connect(self._on_of_viz_setting_changed)

        self.lbl_of_qc = QLabel("QC: —")
        self.lbl_of_qc.setWordWrap(True)
        self.lbl_of_qc.setStyleSheet("color: #aaa; font-size: 11px;")

        self._optical_flow_metric_widgets = (
            self.spin_of_mask_percentile,
            self.combo_of_blur,
            self.spin_of_pyr_scale,
            self.spin_of_levels,
            self.spin_of_winsize,
            self.spin_of_iterations,
            self.spin_of_poly_n,
            self.spin_of_poly_sigma,
        )
        self._optical_flow_setting_widgets = (
            *self._optical_flow_metric_widgets,
            self.chk_show_of_overlay,
            self.spin_of_arrow_spacing,
            self.spin_of_arrow_scale,
        )
        for widget in self._optical_flow_metric_widgets:
            self._configure_tracking_field(widget, full_column=True)
            if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.valueChanged.connect(self._on_optical_flow_setting_changed)
            elif isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._on_optical_flow_setting_changed)
        for widget in (self.spin_of_arrow_spacing, self.spin_of_arrow_scale):
            self._configure_tracking_field(widget, full_column=True)

    def _build_optical_flow_overlay_panel(self) -> QGroupBox:
        box = QGroupBox("Optical Flow Overlay")
        layout = QVBoxLayout(box)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 10, 8, 6)
        self.chk_show_of_overlay.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.chk_show_of_overlay)
        self._add_tracking_setting_row(
            layout,
            "Arrow Spacing (px)",
            self.spin_of_arrow_spacing,
            "Grid spacing for sampled flow arrows.",
        )
        self._add_tracking_setting_row(
            layout,
            "Arrow Scale",
            self.spin_of_arrow_scale,
            "Multiplier for arrow length relative to flow magnitude.",
        )
        return box

    def _build_optical_flow_qc_panel(self) -> QGroupBox:
        box = QGroupBox("Optical Flow QC")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 10, 8, 6)
        layout.addWidget(self.lbl_of_qc)
        return box

    def _build_optical_flow_settings_form(self) -> QGroupBox:
        box = QGroupBox("Optical Flow Advanced Settings")
        box.setToolTip(
            "Dense Farnebäck optical-flow parameters used for the draft motion index."
        )
        layout = QVBoxLayout(box)
        layout.setSpacing(10)
        layout.setContentsMargins(8, 12, 8, 8)
        rows: list[tuple[str, QWidget, str]] = [
            ("Mask Percentile", self.spin_of_mask_percentile, self.spin_of_mask_percentile.toolTip()),
            ("Gaussian Blur Kernel", self.combo_of_blur, self.combo_of_blur.toolTip()),
            ("Farnebäck pyr_scale", self.spin_of_pyr_scale, ""),
            ("Farnebäck levels", self.spin_of_levels, ""),
            ("Farnebäck winsize", self.spin_of_winsize, ""),
            ("Farnebäck iterations", self.spin_of_iterations, ""),
            ("Farnebäck poly_n", self.spin_of_poly_n, ""),
            ("Farnebäck poly_sigma", self.spin_of_poly_sigma, ""),
        ]
        for label_text, widget, tooltip in rows:
            self._add_tracking_setting_row(layout, label_text, widget, tooltip)
        units_hint = QLabel(
            "Microns per Pixel and Seconds per Frame are shared with Template "
            "Tracking settings on the other preview mode panel."
        )
        units_hint.setWordWrap(True)
        units_hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(units_hint)
        return box

    def _build_optical_flow_settings_page(self) -> QWidget:
        self._create_optical_flow_setting_widgets()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        hint = QLabel(
            "Edit optical-flow parameters below while previewing the cropped ROI. "
            "Changes auto-recompute the draft optical-flow motion index."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)
        layout.addWidget(self._build_optical_flow_settings_form())
        layout.addWidget(self._build_optical_flow_overlay_panel())
        layout.addWidget(self._build_optical_flow_qc_panel())
        layout.addStretch()
        scroll.setWidget(content)
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(scroll)
        return page

    def _build_tracking_result_panel(self) -> QGroupBox:
        box = QGroupBox("Tracking / Motion Index Results: No sample selected")
        self.grp_tracking_result = box
        layout = QVBoxLayout(box)
        self.lbl_tracking_result = QLabel("Not generated yet")
        self.lbl_tracking_result.setWordWrap(True)
        self.lbl_tracking_result.setStyleSheet("font-size: 12px;")
        layout.addWidget(self.lbl_tracking_result)
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

    _FULL_PREVIEW_HINT = (
        "Full Sample Preview — orient the data and draw a rectangle around "
        "the usable actin-rich region."
    )
    _SELECT_SAMPLE_HINT = "Select a sample to preview."

    def reset_preview_state(
        self,
        *,
        clear_image: bool = True,
        placeholder: Optional[str] = None,
        reset_roi_controls: bool = True,
    ) -> None:
        """Stop playback and clear cropped/tracking preview when context changes."""
        self._preview_pause()
        self._metric_debounce_timer.stop()
        self._metric_settings_timer.stop()
        self._cancel_pending_debounced_tracking()
        self._set_metric_mode_widgets_visible(False)
        self._clear_of_flow_cache()
        self._preview_frame_index = 0
        self._cropped_preview = None
        self._preview_playing = False
        self.canvas.set_interactive(True)
        self._set_preview_controls_visible(False)
        if reset_roi_controls:
            self._set_tracking_settings_editable(False)
            self._show_roi_controls_view()
        if clear_image:
            self._base_frame = None
            self._total_frames = 1
            self._frame_index = 0
            self._reference_frame_index = 0
            self.canvas.clear_preview()
            self.lbl_frame_info.setText("—")
            self.slider_frame.setMaximum(0)
            self.spin_frame.setMaximum(0)
            self.slider_frame.setValue(0)
            self.spin_frame.setValue(0)
            self._preview_mode = "no_sample"
        else:
            self._preview_mode = "full"
        if placeholder is not None:
            self.lbl_preview_mode.setText(placeholder)
        elif clear_image and self._current_sample is None:
            self.lbl_preview_mode.setText(self._SELECT_SAMPLE_HINT)
        elif not clear_image and self._current_sample is not None:
            self.lbl_preview_mode.setText(self._FULL_PREVIEW_HINT)
        if self._current_sample_id is None:
            self.update_tracking_result_panel()
        self._update_metric_analysis_button_visibility()

    def _show_tracking_settings_view(self) -> None:
        self._right_stack.setCurrentIndex(1)

    def _show_optical_flow_settings_view(self) -> None:
        self._right_stack.setCurrentIndex(2)

    def _show_cropped_metric_settings_view(self) -> None:
        if self._cropped_metric_mode == "optical_flow":
            self._show_optical_flow_settings_view()
        else:
            self._show_tracking_settings_view()

    def _set_metric_mode_widgets_visible(self, visible: bool) -> None:
        for widget in getattr(self, "_metric_mode_widgets", ()):
            widget.setVisible(visible)

    def _sync_metric_mode_combo(self) -> None:
        idx = self.combo_metric_mode.findData(self._cropped_metric_mode)
        if idx >= 0:
            self.combo_metric_mode.blockSignals(True)
            self.combo_metric_mode.setCurrentIndex(idx)
            self.combo_metric_mode.blockSignals(False)

    def _on_cropped_metric_mode_changed(self, _index: int) -> None:
        mode = self.combo_metric_mode.currentData()
        if mode not in ("template", "optical_flow"):
            return
        self._cropped_metric_mode = str(mode)
        if self._preview_mode == "cropped_tracking":
            self._show_cropped_metric_settings_view()
            self._update_optical_flow_qc_readout()
            self._show_cropped_preview_frame(self._preview_frame_index)

    def _show_roi_controls_view(self) -> None:
        self._right_stack.setCurrentIndex(0)
        for i in range(self._right_tabs.count()):
            if self._right_tabs.tabText(i) == "Orient && ROI":
                self._right_tabs.setCurrentIndex(i)
                break

    def _on_right_tab_changed(self, index: int) -> None:
        if index < 0:
            return
        if self._right_tabs.tabText(index) == "Analysis":
            if self._preview_mode == "cropped_tracking":
                self._exit_cropped_preview_mode()
            self._center_stack.setCurrentIndex(1)
            self.refresh_analysis_view()
        elif self._center_stack.currentIndex() == 1:
            self._center_stack.setCurrentIndex(0)

    def show_analysis_view(self) -> None:
        for i in range(self._right_tabs.count()):
            if self._right_tabs.tabText(i) == "Analysis":
                self._right_tabs.setCurrentIndex(i)
                return

    def refresh_analysis_view(self) -> None:
        if self._project_root is None:
            self._analysis_view.refresh(
                AnalysisReport([], [], [], "Open or create a workspace first.")
            )
            return
        try:
            report = build_analysis_report(self._project_root)
        except Exception as exc:
            self._analysis_view.refresh(
                AnalysisReport([], [], [], f"Could not load analysis data:\n{exc}")
            )
            return
        self._analysis_view.refresh(report)

    def _refresh_analysis_if_visible(self) -> None:
        if self._center_stack.currentIndex() == 1:
            self.refresh_analysis_view()

    def _set_tracking_settings_editable(self, editable: bool) -> None:
        widgets = getattr(self, "_tracking_setting_widgets", ())
        for widget in widgets:
            widget.setEnabled(editable)
        of_widgets = getattr(self, "_optical_flow_setting_widgets", ())
        for widget in of_widgets:
            widget.setEnabled(editable)

    def _sample_display_title(self, sample: Optional[dict[str, Any]] = None) -> str:
        sample = sample or self._current_sample
        if not sample:
            return ""
        group = str(sample.get("group", "")).strip()
        batch_num = int(sample.get("batch_number", 1) or 1)
        batch_name = str(sample.get("batch_name", "")).strip()
        sample_label = display_sample_label(batch_num, batch_name)
        if group:
            return f"{group} / {sample_label}"
        return sample_label

    def _tracking_result_group_title(self, sample_id: Optional[str] = None) -> str:
        if sample_id is None:
            return "Tracking / Motion Index Results: No sample selected"
        sample = self._sample_row_for_id(sample_id) or self._current_sample
        title = self._sample_display_title(sample)
        if title:
            return f"{title}'s Tracking Result"
        return f"{sample_id}'s Tracking Result"

    def _update_metric_analysis_button_visibility(self) -> None:
        show = (
            self._current_sample_id is not None
            and not self._metric_analysis_view_active
            and self._base_frame is not None
        )
        self.btn_metric_analysis.setVisible(show)

    def _clear_metric_preview_state(self) -> None:
        self._clear_sample_specific_metric_state()

    def _clear_sample_specific_metric_state(self) -> None:
        self._preview_pause()
        self._metric_debounce_timer.stop()
        self._metric_settings_timer.stop()
        self._cancel_pending_debounced_tracking()
        self._cropped_preview = None
        self._preview_frame_index = 0
        self._clear_of_flow_cache()
        self.canvas.clear_preview()
        self.lbl_cropped_frame.setText("—")
        self.lbl_frame_info.setText("—")

    def _ensure_metric_view_shell_visible(self) -> None:
        self._center_stack.setCurrentIndex(0)
        self._metric_analysis_view_active = True
        self._preview_mode = "cropped_tracking"
        self.canvas.set_interactive(False)
        self.btn_metric_analysis.hide()
        self._set_preview_controls_visible(True)
        self._set_metric_mode_widgets_visible(True)
        self._sync_metric_mode_combo()
        self._set_tracking_settings_editable(True)
        self._show_cropped_metric_settings_view()

    def _reload_metric_analysis_view_for_current_sample(
        self,
        *,
        resume_playback: bool = False,
    ) -> bool:
        self._ensure_metric_view_shell_visible()
        self.lbl_preview_mode.setText(f"{_METRIC_ANALYSIS_VIEW_LABEL} — loading…")
        self.update_tracking_result_panel()
        self._update_optical_flow_qc_readout()
        return self.enter_metric_analysis_view_for_current_sample(
            quiet=True,
            resume_playback=resume_playback,
        )

    def _set_active_sample(self, sample: Optional[dict[str, Any]]) -> None:
        self._cancel_pending_debounced_tracking()
        prev_sid = self._current_sample_id
        self._current_sample = sample
        sid = str(sample.get("sample_id", "")).strip() if sample else ""
        self._current_sample_id = sid or None
        if prev_sid and prev_sid != self._current_sample_id:
            self._of_flow_caches.pop(prev_sid, None)

    def _on_tracking_setting_changed(self, *_args: object) -> None:
        if self._current_sample_id:
            self._tracking_result_stale_by_sample[self._current_sample_id] = True
            self._optical_flow_stale_by_sample[self._current_sample_id] = True
            self.update_tracking_result_panel()
        if self._preview_mode == "cropped_tracking":
            self._schedule_metric_settings_refresh()

    def _on_optical_flow_setting_changed(self, *_args: object) -> None:
        if self._current_sample_id:
            self._optical_flow_stale_by_sample[self._current_sample_id] = True
            self._clear_of_flow_cache(self._current_sample_id)
            self._update_optical_flow_qc_readout()
            self.update_tracking_result_panel()
        if self._preview_mode == "cropped_tracking":
            self._schedule_metric_settings_refresh()

    @staticmethod
    def _status_after_roi_autosave(current_status: str) -> Optional[str]:
        current = str(current_status).strip()
        if current in _ADVANCED_SAMPLE_STATUSES:
            return None
        if current == STATUS_ROI_MARKED:
            return None
        if current in _ROI_STATUS_UPGRADE_FROM:
            return STATUS_ROI_MARKED
        if current in (STATUS_ROI_PROPAGATED, STATUS_ROI_APPROVED):
            return None
        return STATUS_ROI_MARKED

    def _cancel_pending_debounced_tracking(self) -> None:
        self._metric_debounce_timer.stop()
        self._metric_settings_timer.stop()
        self._tracking_run_token += 1
        self._optical_flow_run_token += 1
        self._pending_tracking_snapshot = None
        self._pending_optical_flow_snapshot = None

    def _capture_tracking_snapshot(self) -> Optional[_TrackingRunSnapshot]:
        if self._current_sample_id is None or self._current_sample is None:
            return None
        roi = self.canvas.rect_roi()
        if roi is None:
            return None
        path = self._sample_file_path()
        if path is None or not path.exists() or not is_supported_video_path(path):
            return None
        check = self._validate_current_roi()
        if not check.ok or check.roi_oriented is None:
            return None
        try:
            params = self._tracking_params_from_ui()
        except ValueError:
            return None
        return _TrackingRunSnapshot(
            sample_id=self._current_sample_id,
            roi_key=(roi.x, roi.y, roi.width, roi.height),
            params_key=tuple(sorted(asdict(params).items())),
            orientation_key=(
                float(self._orientation.rotation_angle_degrees),
                bool(self._orientation.mirror_y_axis),
                bool(self._orientation.flipped_180),
            ),
            video_path=str(path.resolve()),
            run_token=self._tracking_run_token,
        )

    def _snapshot_matches_current(self, snapshot: _TrackingRunSnapshot) -> bool:
        if snapshot.run_token != self._tracking_run_token:
            return False
        current = self._capture_tracking_snapshot()
        if current is None:
            return False
        return (
            current.sample_id == snapshot.sample_id
            and current.roi_key == snapshot.roi_key
            and current.params_key == snapshot.params_key
            and current.orientation_key == snapshot.orientation_key
            and current.video_path == snapshot.video_path
        )

    def _schedule_debounced_metrics(self, *, show_scheduled: bool = False) -> None:
        track_snap = self._capture_tracking_snapshot()
        of_snap = self._capture_optical_flow_snapshot()
        if track_snap is None and of_snap is None:
            return
        if track_snap is not None:
            self._pending_tracking_snapshot = track_snap
        if of_snap is not None:
            if self._current_sample_id:
                self._clear_of_flow_cache(self._current_sample_id)
            self._pending_optical_flow_snapshot = of_snap
        self._metric_debounce_timer.start()
        if show_scheduled:
            self._set_roi_save_status("Metric calculation scheduled", saved=True)

    def _schedule_metric_settings_refresh(self) -> None:
        if self._preview_mode != "cropped_tracking":
            return
        track_snap = self._capture_tracking_snapshot()
        of_snap = self._capture_optical_flow_snapshot()
        if track_snap is None and of_snap is None:
            return
        if track_snap is not None:
            self._pending_tracking_snapshot = track_snap
        if of_snap is not None:
            if self._current_sample_id:
                self._clear_of_flow_cache(self._current_sample_id)
            self._pending_optical_flow_snapshot = of_snap
        self._metric_settings_timer.start()

    def _on_metric_debounce_fired(self) -> None:
        track_snap = self._pending_tracking_snapshot
        of_snap = self._pending_optical_flow_snapshot
        if track_snap is not None:
            self._run_draft_tracking_for_snapshot(
                track_snap,
                update_cropped_preview=self._preview_mode == "cropped_tracking",
                quiet_skip=True,
            )
        if of_snap is not None:
            self._run_optical_flow_for_snapshot(of_snap, quiet_skip=True)

    def _on_metric_settings_debounce_fired(self) -> None:
        if self._preview_mode != "cropped_tracking":
            return
        self._on_metric_debounce_fired()

    def _optical_flow_settings_from_ui(self) -> OpticalFlowSettings:
        blur = int(self.combo_of_blur.currentData() or 0)
        return OpticalFlowSettings(
            mask_percentile=float(self.spin_of_mask_percentile.value()),
            gaussian_blur_kernel=blur,
            pyr_scale=float(self.spin_of_pyr_scale.value()),
            levels=int(self.spin_of_levels.value()),
            winsize=int(self.spin_of_winsize.value()),
            iterations=int(self.spin_of_iterations.value()),
            poly_n=int(self.spin_of_poly_n.value()),
            poly_sigma=float(self.spin_of_poly_sigma.value()),
            microns_per_pixel=float(self.spin_track_mpp.value()),
            seconds_per_frame=float(self.spin_track_spf.value()),
        )

    def _capture_optical_flow_snapshot(self) -> Optional[_OpticalFlowRunSnapshot]:
        if self._current_sample_id is None or self._current_sample is None:
            return None
        roi = self.canvas.rect_roi()
        if roi is None:
            return None
        path = self._sample_file_path()
        if path is None or not path.exists() or not is_supported_video_path(path):
            return None
        check = self._validate_current_roi()
        if not check.ok or check.roi_oriented is None:
            return None
        try:
            settings = self._optical_flow_settings_from_ui()
        except ValueError:
            return None
        return _OpticalFlowRunSnapshot(
            sample_id=self._current_sample_id,
            roi_key=(roi.x, roi.y, roi.width, roi.height),
            settings_key=tuple(sorted(asdict(settings).items())),
            orientation_key=(
                float(self._orientation.rotation_angle_degrees),
                bool(self._orientation.mirror_y_axis),
                bool(self._orientation.flipped_180),
            ),
            video_path=str(path.resolve()),
            run_token=self._optical_flow_run_token,
        )

    def _optical_flow_snapshot_matches_current(
        self, snapshot: _OpticalFlowRunSnapshot
    ) -> bool:
        if snapshot.run_token != self._optical_flow_run_token:
            return False
        current = self._capture_optical_flow_snapshot()
        if current is None:
            return False
        return (
            current.sample_id == snapshot.sample_id
            and current.roi_key == snapshot.roi_key
            and current.settings_key == snapshot.settings_key
            and current.orientation_key == snapshot.orientation_key
            and current.video_path == snapshot.video_path
        )

    def _draft_optical_flow_json_path(self, data_id: str) -> Path:
        assert self._project_root is not None
        from actintrack_app.schema_compat import draft_optical_flow_path

        return draft_optical_flow_path(self._project_root, data_id)

    def _run_optical_flow_for_snapshot(
            self,
        snapshot: _OpticalFlowRunSnapshot,
        *,
        quiet_skip: bool = True,
    ) -> bool:
        if self._optical_flow_job_running:
            return False
        if snapshot.sample_id != self._current_sample_id:
            return False
        if not self._optical_flow_snapshot_matches_current(snapshot):
            if not quiet_skip:
                self._set_roi_save_status("Optical flow skipped: ROI changed", saved=True)
            return False
        check = self._validate_current_roi()
        if not check.ok or check.roi_oriented is None:
            return False
        path = Path(snapshot.video_path)
        if not path.is_file() or not is_supported_video_path(path):
            return False
        try:
            settings = self._optical_flow_settings_from_ui()
        except ValueError:
            return False

        roi_bounds = (
            int(check.roi_oriented.x),
            int(check.roi_oriented.y),
            int(check.roi_oriented.width),
            int(check.roi_oriented.height),
        )
        self._optical_flow_job_running = True
        self._update_optical_flow_qc_readout()
        QApplication.processEvents()
        try:
            frames = load_cropped_frames_from_video(
                path, self._orientation, check.roi_oriented
            )
            fingerprint = build_optical_flow_fingerprint(
                sample_id=snapshot.sample_id,
                roi_bounds=roi_bounds,
                settings=settings,
                data_identity=str(path.resolve()),
                frame_count=len(frames),
            )
            result = compute_optical_flow_motion_index(
                frames,
                settings,
                sample_id=snapshot.sample_id,
                data_identity=str(path.resolve()),
                roi_bounds=roi_bounds,
                fingerprint=fingerprint,
            )
        except Exception:
            if not quiet_skip:
                self._set_roi_save_status("Optical flow failed", saved=False)
            return False
        finally:
            self._optical_flow_job_running = False

        if not self._optical_flow_snapshot_matches_current(snapshot):
            if not quiet_skip:
                self._set_roi_save_status("Optical flow skipped: settings changed", saved=True)
            return False

        self._clear_of_flow_cache(snapshot.sample_id)
        self._commit_optical_flow_result(snapshot.sample_id, result)
        if self._preview_mode == "cropped_tracking":
            self._show_cropped_preview_frame(self._preview_frame_index)
        return True

    def _save_draft_optical_flow_result(
        self, sample_id: str, result: OpticalFlowResult
    ) -> None:
        if self._project_root is None:
            return
        path = self._draft_optical_flow_json_path(sample_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result_to_dict(result), indent=2), encoding="utf-8")

    def _invalidate_optical_flow_for_sample(self, sample_id: str) -> None:
        self._optical_flow_results_by_sample.pop(sample_id, None)
        self._optical_flow_stale_by_sample.pop(sample_id, None)
        self._of_flow_caches.pop(sample_id, None)
        if self._project_root is not None:
            draft_path = self._draft_optical_flow_json_path(sample_id)
            if draft_path.is_file():
                try:
                    draft_path.unlink()
                except OSError:
                    pass

    def _clear_of_flow_cache(self, sample_id: Optional[str] = None) -> None:
        if sample_id is None:
            self._of_flow_caches.clear()
        else:
            self._of_flow_caches.pop(sample_id, None)

    def _optical_flow_viz_settings_from_ui(self) -> OpticalFlowVisualizationSettings:
        return OpticalFlowVisualizationSettings(
            arrow_spacing_px=int(self.spin_of_arrow_spacing.value()),
            arrow_scale=float(self.spin_of_arrow_scale.value()),
        )

    def _current_optical_flow_fingerprint(self) -> str:
        if self._current_sample_id is None or self._cropped_preview is None:
            return ""
        check = self._validate_current_roi()
        if not check.ok or check.roi_oriented is None:
            return ""
        path = self._sample_file_path()
        data_identity = str(path.resolve()) if path is not None else ""
        roi_bounds = (
            int(check.roi_oriented.x),
            int(check.roi_oriented.y),
            int(check.roi_oriented.width),
            int(check.roi_oriented.height),
        )
        try:
            settings = self._optical_flow_settings_from_ui()
        except ValueError:
            return ""
        return build_optical_flow_fingerprint(
            sample_id=self._current_sample_id,
            roi_bounds=roi_bounds,
            settings=settings,
            data_identity=data_identity,
            frame_count=len(self._cropped_preview.frames),
        )

    def _get_optical_flow_result_object(
        self, sample_id: str
    ) -> Optional[OpticalFlowResult]:
        cached = self._optical_flow_results_by_sample.get(sample_id)
        if cached is not None:
            return cached
        if self._project_root is not None:
            from actintrack_app.schema_compat import resolve_draft_optical_flow_path

            draft_path = resolve_draft_optical_flow_path(self._project_root, sample_id)
            if draft_path is not None:
                try:
                    data = json.loads(draft_path.read_text(encoding="utf-8"))
                    return result_from_dict(data)
                except (OSError, json.JSONDecodeError):
                    pass
        return None

    def _optical_flow_qc_status_for_sample(self, sample_id: str) -> str:
        result = self._get_optical_flow_result_object(sample_id)
        fingerprint = self._current_optical_flow_fingerprint() if sample_id == self._current_sample_id else ""
        return resolve_qc_status(
            result=result,
            is_computing=self._optical_flow_job_running and sample_id == self._current_sample_id,
            is_stale_flag=bool(self._optical_flow_stale_by_sample.get(sample_id)),
            current_fingerprint=fingerprint,
        )

    def _update_optical_flow_qc_readout(self) -> None:
        if not hasattr(self, "lbl_of_qc"):
            return
        sid = self._current_sample_id
        if sid is None:
            self.lbl_of_qc.setText("QC: —")
            return
        result = self._get_optical_flow_result_object(sid)
        status = self._optical_flow_qc_status_for_sample(sid)
        qc = format_optical_flow_qc(result)
        lines = [
            f"Status: {status}",
            f"General Movement: {qc['general_movement']} µm/s",
            f"Downward Motion: {qc['downward_motion']} µm/s",
            f"Net Y Velocity: {qc['net_y_velocity']} µm/s",
            f"Directionality Ratio: {qc['directionality_ratio']}",
            f"Valid Pixel Fraction: {qc['valid_pixel_fraction']}",
            f"Saturated Pixel Fraction: {qc['saturated_pixel_fraction']}",
            f"Frame pairs used: {qc['frame_pairs_used']}",
        ]
        self.lbl_of_qc.setText("\n".join(lines))

    def _ensure_of_flow_cache(self) -> Optional[OpticalFlowFlowCache]:
        if self._current_sample_id is None or self._cropped_preview is None:
            return None
        fingerprint = self._current_optical_flow_fingerprint()
        if not fingerprint:
            return None
        sid = self._current_sample_id
        existing = self._of_flow_caches.get(sid)
        if existing is not None and existing.fingerprint == fingerprint:
            return existing
        try:
            settings = self._optical_flow_settings_from_ui()
        except ValueError:
            return None
        cache = build_flow_cache(
            self._cropped_preview.frames,
            settings,
            sample_id=sid,
            fingerprint=fingerprint,
        )
        self._of_flow_caches[sid] = cache
        return cache

    def _get_overlay_arrows_for_frame(self, frame_index: int) -> list:
        cache = self._ensure_of_flow_cache()
        if cache is None or self._cropped_preview is None:
            return []
        return get_flow_arrows_for_frame(
            cache,
            frame_index,
            len(self._cropped_preview.frames),
            self._optical_flow_viz_settings_from_ui(),
        )

    def _on_show_of_overlay_changed(self, _checked: bool) -> None:
        if self._preview_mode == "cropped_tracking":
            self._show_cropped_preview_frame(self._preview_frame_index)

    def _on_of_viz_setting_changed(self, *_args: object) -> None:
        if self._preview_mode == "cropped_tracking":
            self._show_cropped_preview_frame(self._preview_frame_index)

    def _commit_optical_flow_result(
        self, sample_id: str, result: OpticalFlowResult
    ) -> None:
        if sample_id != self._current_sample_id:
            return
        self._optical_flow_results_by_sample[sample_id] = result
        self._optical_flow_stale_by_sample.pop(sample_id, None)
        self._clear_of_flow_cache(sample_id)
        self._save_draft_optical_flow_result(sample_id, result)
        self._update_optical_flow_qc_readout()
        self.update_tracking_result_panel(sample_id)
        self._refresh_analysis_if_visible()

    @staticmethod
    def _view_from_optical_flow_dict(data: dict[str, Any]) -> OpticalFlowResultView:
        if not data.get("has_valid_result"):
            reason = str(data.get("failure_reason", "")).strip()
            return OpticalFlowResultView(status="failed", failure_reason=reason)
        return OpticalFlowResultView(
            status="success",
            general_movement=_optional_gui_float(data.get("optical_flow_general_movement_um_s")),
            downward_motion=_optional_gui_float(data.get("optical_flow_downward_motion_um_s")),
            net_y_velocity=_optional_gui_float(data.get("optical_flow_net_y_velocity_um_s")),
            directionality_ratio=_optional_gui_float(data.get("optical_flow_directionality_ratio")),
            valid_pixel_fraction=_optional_gui_float(data.get("optical_flow_valid_pixel_fraction")),
            saturated_pixel_fraction=_optional_gui_float(
                data.get("optical_flow_saturated_pixel_fraction")
            ),
        )

    def _view_from_optical_flow_result(self, result: OpticalFlowResult) -> OpticalFlowResultView:
        if not result.has_valid_result:
            return OpticalFlowResultView(
                status="failed",
                failure_reason=result.failure_reason,
            )
        return OpticalFlowResultView(
            status="success",
            general_movement=result.optical_flow_general_movement_um_s,
            downward_motion=result.optical_flow_downward_motion_um_s,
            net_y_velocity=result.optical_flow_net_y_velocity_um_s,
            directionality_ratio=result.optical_flow_directionality_ratio,
            valid_pixel_fraction=result.optical_flow_valid_pixel_fraction,
            saturated_pixel_fraction=result.optical_flow_saturated_pixel_fraction,
        )

    def load_latest_optical_flow_result_for_sample(
        self, sample_id: str
    ) -> Optional[OpticalFlowResultView]:
        if self._project_root is not None:
            from actintrack_app.schema_compat import resolve_draft_optical_flow_path

            draft_path = resolve_draft_optical_flow_path(self._project_root, sample_id)
            if draft_path is not None:
                try:
                    data = json.loads(draft_path.read_text(encoding="utf-8"))
                    return self._view_from_optical_flow_dict(data)
                except (OSError, json.JSONDecodeError):
                    pass
        cached = self._optical_flow_results_by_sample.get(sample_id)
        if cached is not None:
            return self._view_from_optical_flow_result(cached)
        return None

    def _run_draft_tracking_for_snapshot(
        self,
        snapshot: _TrackingRunSnapshot,
        *,
        update_cropped_preview: bool,
        quiet_skip: bool = True,
    ) -> bool:
        if self._tracking_job_running:
            return False
        if snapshot.sample_id != self._current_sample_id:
            return False
        if not self._snapshot_matches_current(snapshot):
            if not quiet_skip:
                self._set_roi_save_status("Tracking skipped: ROI changed", saved=True)
            return False
        check = self._validate_current_roi()
        if not check.ok or check.roi_oriented is None:
            return False
        path = Path(snapshot.video_path)
        if not path.is_file() or not is_supported_video_path(path):
            return False
        try:
            params = self._tracking_params_from_ui()
        except ValueError:
            return False
        crop_w = int(check.roi_oriented.width)
        crop_h = int(check.roi_oriented.height)
        min_dim = params.template_patch_size_px + (2 * params.search_radius_px) + 2
        if min(crop_w, crop_h) < min_dim:
            return False

        self._tracking_job_running = True
        QApplication.processEvents()
        try:
            frames = load_cropped_frames_from_video(
                path, self._orientation, check.roi_oriented
            )
            analysis = analyze_cropped_preview(frames, params=params)
        except Exception:
            if not quiet_skip:
                self._set_roi_save_status("Tracking failed", saved=False)
            return False
        finally:
            self._tracking_job_running = False

        if not self._snapshot_matches_current(snapshot):
            if not quiet_skip:
                self._set_roi_save_status("Tracking skipped: ROI changed", saved=True)
            return False

        self._commit_tracking_result(snapshot.sample_id, analysis, params)
        if update_cropped_preview and self._preview_mode == "cropped_tracking":
            self._cropped_preview = analysis
            max_index = max(0, len(analysis.frames) - 1)
            self.slider_frame.setMaximum(max_index)
            self.spin_frame.setMaximum(max_index)
            self.slider_cropped_frame.setMaximum(max_index)
            frame_idx = min(self._preview_frame_index, max_index)
            self._show_cropped_preview_frame(frame_idx)
        return True

    def _update_sample_list_row_for_id(self, sample_id: str) -> None:
        for i in range(self.list_samples.count()):
            item = self.list_samples.item(i)
            data = self._list_item_meta(item)
            if not data or data.get("item_type") != "sample":
                continue
            if str(data.get("sample_id")) != str(sample_id):
                continue
            if (
                self._current_sample is not None
                and str(self._current_sample.get("sample_id")) == str(sample_id)
            ):
                data = dict(self._current_sample)
                data["item_type"] = "sample"
            status = str(data.get("processing_status", ""))
            export_name = str(
                data.get("final_export_name") or data.get("auto_export_name") or ""
            ).strip()
            if not export_name:
                export_name = str(data.get("sample_id", sample_id))
            original = str(data.get("original_filename", ""))
            item.setText(f"    [{status}] {export_name} — {original}")
            item.setData(Qt.ItemDataRole.UserRole, data)
            color = STATUS_COLORS.get(status)
            if color:
                item.setForeground(QBrush(color))
            return

    def _is_tracking_failed(self, analysis: CroppedPreviewAnalysis) -> bool:
        return analysis.num_tracks_with_valid_steps == 0

    def _draft_tracking_json_path(self, data_id: str) -> Path:
        assert self._project_root is not None
        from actintrack_app.schema_compat import draft_tracking_path

        return draft_tracking_path(self._project_root, data_id)

    def _sample_row_for_id(self, sample_id: str) -> Optional[dict[str, Any]]:
        if (
            self._current_sample is not None
            and str(self._current_sample.get("sample_id", "")) == sample_id
        ):
            return self._current_sample
        if self._project_root is None:
            return None
        df = load_samples_csv(self._project_root / METADATA_DIR / SAMPLES_CSV)
        rows = df[df["sample_id"].astype(str) == str(sample_id)]
        if rows.empty:
            return None
        return rows.iloc[0].to_dict()

    def _motion_index_json_path_for_sample(self, sample: dict[str, Any]) -> Optional[Path]:
        if self._project_root is None:
            return None
        group = str(sample.get("group", "")).strip()
        batch_name = str(sample.get("batch_name", "")).strip()
        final_name = str(sample.get("final_export_name", "")).strip()
        if not group or not batch_name or not final_name:
            return None
        batch_dir = get_processed_batch_dir(self._project_root, group, batch_name)
        path = motion_index_summary_json_path(batch_dir, final_name)
        return path if path.is_file() else None

    @staticmethod
    def _view_from_tracking_dict(data: dict[str, Any]) -> SampleTrackingResultView:
        tracks_used = int(data.get("num_tracks_with_valid_steps", 0) or 0)
        tracks_started = int(
            data.get("num_tracks_started", data.get("num_tracks_requested", tracks_used))
            or 0
        )
        if tracks_used <= 0:
            reason = str(
                data.get("tracking_warning")
                or data.get("track_preview_error")
                or data.get("failure_reason")
                or ""
            ).strip()
            return SampleTrackingResultView(status="failed", failure_reason=reason)
        return SampleTrackingResultView(
            status="success",
            downward_velocity=float(data.get("downward_velocity_index_um_per_s", 0.0)),
            general_movement=float(data.get("general_movement_index_um_per_s", 0.0)),
            tracks_used=tracks_used,
            tracks_requested=max(tracks_started, tracks_used),
            valid_steps=int(data.get("total_valid_steps", 0) or 0),
        )

    def _view_from_preview_analysis(
        self, analysis: CroppedPreviewAnalysis
    ) -> SampleTrackingResultView:
        if self._is_tracking_failed(analysis):
            return SampleTrackingResultView(
                status="failed",
                failure_reason=analysis.tracking_warning,
            )
        requested = len(analysis.starting_points)
        if analysis.params is not None:
            requested = max(requested, analysis.params.num_starting_points)
        return SampleTrackingResultView(
            status="success",
            downward_velocity=analysis.downward_velocity_index_um_per_s,
            general_movement=analysis.general_movement_index_um_per_s,
            tracks_used=analysis.num_tracks_with_valid_steps,
            tracks_requested=max(requested, analysis.num_tracks_started),
            valid_steps=analysis.total_valid_steps,
        )

    def load_latest_tracking_result_for_sample(
        self, sample_id: str
    ) -> Optional[SampleTrackingResultView]:
        sample = self._sample_row_for_id(sample_id)
        if self._project_root is not None:
            if sample is not None:
                summary_path = self._motion_index_json_path_for_sample(sample)
                if summary_path is not None:
                    try:
                        data = json.loads(summary_path.read_text(encoding="utf-8"))
                        return self._view_from_tracking_dict(data)
                    except (OSError, json.JSONDecodeError):
                        pass
            from actintrack_app.schema_compat import resolve_draft_tracking_path

            draft_path = resolve_draft_tracking_path(self._project_root, sample_id)
            if draft_path is not None:
                try:
                    data = json.loads(draft_path.read_text(encoding="utf-8"))
                    return self._view_from_tracking_dict(data)
                except (OSError, json.JSONDecodeError):
                    pass
        cached = self._tracking_results_by_sample.get(sample_id)
        if cached is not None:
            return self._view_from_preview_analysis(cached)
        if sample is not None:
            proc_status = str(sample.get("processing_status", ""))
            if proc_status == STATUS_MOTION_INDEX_FAILED:
                return SampleTrackingResultView(
                    status="failed",
                    failure_reason="Motion index generation failed.",
                )
        return None

    def _render_tracking_result_panel(
        self,
        template_view: Optional[SampleTrackingResultView],
        optical_flow_view: Optional[OpticalFlowResultView],
        *,
        template_stale: bool = False,
        optical_flow_stale: bool = False,
    ) -> None:
        lines: list[str] = []

        lines.append("Template Tracking Motion Index")
        if template_stale:
            lines.append("May not match current settings.")
        elif template_view is None or template_view.status == "none":
            lines.append("Not generated yet")
        elif template_view.status == "failed":
            lines.append("Failed")
            if template_view.failure_reason:
                lines.append(template_view.failure_reason)
        else:
            tracks_line = f"Tracks Used: {template_view.tracks_used}"
            if template_view.tracks_requested > template_view.tracks_used:
                tracks_line = (
                    f"Tracks Used: {template_view.tracks_used} / "
                    f"{template_view.tracks_requested}"
                )
            lines.extend(
                [
                    f"Downward Velocity: {template_view.downward_velocity:.4f} µm/s",
                    f"General Movement: {template_view.general_movement:.4f} µm/s",
                    tracks_line,
                    f"Valid Steps: {template_view.valid_steps}",
                ]
            )

        lines.append("")
        lines.append("Optical Flow Motion Index (Draft)")
        sid = self._current_sample_id
        of_status = self._optical_flow_qc_status_for_sample(sid) if sid else "Not computed"
        lines.append(f"Status: {of_status}")
        if optical_flow_stale:
            lines.append("May not match current settings.")
        elif optical_flow_view is None or optical_flow_view.status == "none":
            if of_status == "Not computed":
                lines.append("Not generated yet")
        elif optical_flow_view.status == "failed":
            lines.append("Failed")
            if optical_flow_view.failure_reason:
                lines.append(optical_flow_view.failure_reason)
        else:
            result_obj = self._get_optical_flow_result_object(sid) if sid else None
            frame_pairs = (
                str(result_obj.frame_pair_count)
                if result_obj is not None and result_obj.frame_pair_count
                else "—"
            )
            lines.extend(
                [
                    f"Frame pairs used: {frame_pairs}",
                    f"General Movement: {_fmt_optional_float(optical_flow_view.general_movement)} µm/s",
                    f"Downward Motion: {_fmt_optional_float(optical_flow_view.downward_motion)} µm/s",
                    f"Net Y Velocity: {_fmt_optional_float(optical_flow_view.net_y_velocity)} µm/s",
                    f"Directionality Ratio: {_fmt_optional_float(optical_flow_view.directionality_ratio)}",
                    f"Valid Pixel Fraction: {_fmt_optional_float(optical_flow_view.valid_pixel_fraction)}",
                ]
            )
            if optical_flow_view.saturated_pixel_fraction is not None:
                lines.append(
                    "Saturated Pixel Fraction: "
                    f"{_fmt_optional_float(optical_flow_view.saturated_pixel_fraction)}"
                )

        self.lbl_tracking_result.setText("\n".join(lines))

    def update_tracking_result_panel(self, sample_id: Optional[str] = None) -> None:
        sid = sample_id or self._current_sample_id
        if sid is None:
            self.grp_tracking_result.setTitle("Tracking Result: No sample selected")
            self.lbl_tracking_result.setText("")
            return
        if sid != self._current_sample_id:
            return
        self.grp_tracking_result.setTitle(self._tracking_result_group_title(sid))
        self._render_tracking_result_panel(
            self.load_latest_tracking_result_for_sample(sid),
            self.load_latest_optical_flow_result_for_sample(sid),
            template_stale=bool(self._tracking_result_stale_by_sample.get(sid)),
            optical_flow_stale=bool(self._optical_flow_stale_by_sample.get(sid)),
        )

    def _save_draft_tracking_result(
                self,
        sample_id: str,
        analysis: CroppedPreviewAnalysis,
        params: MotionIndexParams,
    ) -> None:
        if self._project_root is None:
            return
        path = self._draft_tracking_json_path(sample_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "data_id": sample_id,
            "sample_id": sample_id,
            "downward_velocity_index_um_per_s": analysis.downward_velocity_index_um_per_s,
            "general_movement_index_um_per_s": analysis.general_movement_index_um_per_s,
            "num_tracks_with_valid_steps": analysis.num_tracks_with_valid_steps,
            "num_tracks_started": analysis.num_tracks_started,
            "num_tracks_requested": params.num_starting_points,
            "total_valid_steps": analysis.total_valid_steps,
            "tracking_warning": analysis.tracking_warning,
            "parameters": asdict(params),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _invalidate_tracking_result_for_sample(self, sample_id: str) -> None:
        self._tracking_results_by_sample.pop(sample_id, None)
        self._tracking_result_stale_by_sample.pop(sample_id, None)
        if self._project_root is not None:
            draft_path = self._draft_tracking_json_path(sample_id)
            if draft_path.is_file():
                try:
                    draft_path.unlink()
                except OSError:
                    pass
        self._invalidate_optical_flow_for_sample(sample_id)

    def _commit_tracking_result(
        self,
        sample_id: str,
        analysis: CroppedPreviewAnalysis,
        params: MotionIndexParams,
    ) -> None:
        if sample_id != self._current_sample_id:
            return
        self._tracking_results_by_sample[sample_id] = analysis
        self._tracking_result_stale_by_sample.pop(sample_id, None)
        self._save_draft_tracking_result(sample_id, analysis, params)
        self.update_tracking_result_panel(sample_id)
        self._refresh_analysis_if_visible()

    def _update_orientation_label(self) -> None:
        self.chk_mirror_y.blockSignals(True)
        self.chk_mirror_y.setChecked(self._orientation.mirror_y_axis)
        self.chk_mirror_y.blockSignals(False)
        self.spin_custom_angle.blockSignals(True)
        self.spin_custom_angle.setValue(self._orientation.rotation_angle_degrees)
        self.spin_custom_angle.blockSignals(False)

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
        if keep_roi and roi is not None:
            self._autosave_roi(quiet=True)

    def _set_roi_save_status(self, text: str, *, saved: bool = True) -> None:
        color = "#9ad4c8" if saved else "#ccaa66"
        self.lbl_roi_save_status.setText(text)
        self.lbl_roi_save_status.setStyleSheet(
            f"color: {color}; font-size: 12px; padding: 2px 0;"
        )

    def _autosave_roi(self, *, quiet: bool = True) -> bool:
        if self._project_root is None or self._current_sample is None:
            return False
        if self.canvas.rect_roi() is None:
            self._set_roi_save_status("No ROI to save", saved=False)
            return False
        try:
            ann = self._current_annotation_dict(status=STATUS_ROI_MARKED)
        except ValueError as exc:
            self._set_roi_save_status("Unsaved changes", saved=False)
            if not quiet:
                QMessageBox.warning(self, "Save ROI", str(exc))
            return False

        sid = ann["sample_id"]
        current_status = str(self._current_sample.get("processing_status", ""))
        new_status = self._status_after_roi_autosave(current_status)
        try:
            crop_path = self._project_root / METADATA_DIR / CROP_METADATA_JSON
            save_sample_crop_annotation(crop_path, sid, ann)
            csv_update: dict[str, Any] = {
                "sample_id": sid,
                "notes": ann["notes"],
                "annotation_source": ann["annotation_source"],
                "review_status": ann.get("review_status", "approved"),
            }
            if new_status is not None:
                csv_update["processing_status"] = new_status
            update_samples_csv(
                self._project_root / METADATA_DIR / SAMPLES_CSV,
                csv_update,
            )
        except OSError as exc:
            self._set_roi_save_status(f"ROI autosave failed: {exc}", saved=False)
            self._status(f"ROI autosave failed: {exc}")
            if not quiet:
                QMessageBox.warning(self, "ROI Autosave", f"Could not save ROI:\n{exc}")
            return False

        if new_status is not None:
            self._current_sample["processing_status"] = new_status
            self._update_sample_list_row_for_id(sid)
        self._loaded_annotation_source = ann["annotation_source"]
        self._roi_user_adjusted = False
        self._roi_autosave_pending = False
        self._set_roi_save_status("ROI autosaved", saved=True)
        self._schedule_debounced_metrics(show_scheduled=True)
        return True

    def _on_apply_custom_angle(self) -> None:
        self._exit_cropped_preview_mode()
        self._orientation.rotation_angle_degrees = float(self.spin_custom_angle.value())
        self._orientation.manual_rotation_steps = []
        self._refresh_display()

    def _on_mirror_y_axis(self, checked: bool) -> None:
        self._exit_cropped_preview_mode()
        self._orientation.mirror_y_axis = bool(checked)
        self._orientation.manual_rotation_steps = []
        self._refresh_display()

    def _on_flip_180(self) -> None:
        self._exit_cropped_preview_mode()
        self._orientation.flipped_180 = not self._orientation.flipped_180
        self._orientation.manual_rotation_steps = []
        self._refresh_display()

    def _on_reset_orientation(self) -> None:
        self._exit_cropped_preview_mode()
        self._orientation = OrientationState()
        self._refresh_display(keep_roi=True)

    def on_roi_changed(self, roi: Optional[RectROI]) -> None:
        if roi is None:
            return
        self._roi_user_adjusted = True
        self._roi_autosave_pending = True
        self._set_roi_save_status("Unsaved changes", saved=False)
        if str(self._loaded_annotation_source) == "auto_suggested":
            self._loaded_annotation_source = "auto_suggested_adjusted"
        self._schedule_debounced_metrics(show_scheduled=False)

    def on_roi_edit_finished(self) -> None:
        self._autosave_roi(quiet=True)

    def _on_clear_roi(self) -> None:
        self._cancel_pending_debounced_tracking()
        self._exit_cropped_preview_mode()
        self.canvas.set_rect_roi(None)
        self._roi_user_adjusted = True
        self._roi_autosave_pending = False
        self._set_roi_save_status("ROI cleared", saved=False)

    def _tracking_params_from_ui(self) -> MotionIndexParams:
        patch = int(self.spin_track_patch.value())
        if patch % 2 == 0:
            raise ValueError("Template patch size must be an odd integer.")
        if patch < 3:
            raise ValueError("Template patch size must be at least 3 px.")
        search_radius = int(self.spin_track_search.value())
        if search_radius < 1:
            raise ValueError("Search radius must be at least 1 px.")
        min_spacing = int(self.spin_track_spacing.value())
        if min_spacing < 1:
            raise ValueError("Minimum point spacing must be at least 1 px.")
        return MotionIndexParams(
            num_starting_points=int(self.spin_track_points.value()),
            min_point_spacing_px=min_spacing,
            search_radius_px=search_radius,
            template_patch_size_px=patch,
            min_template_confidence=float(self.spin_track_confidence.value()),
            lookahead_frames=int(self.spin_track_lookahead.value()),
            microns_per_pixel=float(self.spin_track_mpp.value()),
            seconds_per_frame=float(self.spin_track_spf.value()),
            downward_direction="increasing_y",
        )

    def _on_show_metric_analysis_view(self) -> None:
        self.enter_metric_analysis_view_for_current_sample(quiet=False)

    def enter_metric_analysis_view_for_current_sample(
        self,
        *,
        quiet: bool = False,
        resume_playback: bool = False,
    ) -> bool:
        if self._project_root is None or self._current_sample is None:
            if not quiet:
                QMessageBox.warning(
                    self, _METRIC_ANALYSIS_VIEW_LABEL, "Select a data file first."
                )
            return False

        self._cancel_pending_debounced_tracking()
        self._autosave_roi(quiet=True)
        check = self._validate_current_roi()
        if not check.ok or check.roi_oriented is None:
            message = check.message or (
                "Metric Analysis View is unavailable because this Sample "
                "does not have a saved ROI."
            )
            if quiet:
                self._show_metric_analysis_placeholder(message)
            else:
                QMessageBox.warning(self, _METRIC_ANALYSIS_VIEW_LABEL, message)
            return False

        path = self._sample_file_path()
        if path is None or not path.exists():
            message = (
                "Metric Analysis View is unavailable because this Sample "
                "does not have valid Data."
            )
            if quiet:
                self._show_metric_analysis_placeholder(message)
            else:
                QMessageBox.warning(self, _METRIC_ANALYSIS_VIEW_LABEL, message)
            return False
        if not is_supported_video_path(path):
            message = (
                "Only AVI and MP4 data files are supported in the current 2D workflow."
            )
            if quiet:
                self._show_metric_analysis_placeholder(message)
            else:
                QMessageBox.information(self, "Unsupported", message)
            return False

        try:
            params = self._tracking_params_from_ui()
        except ValueError as exc:
            if quiet:
                self._show_metric_analysis_placeholder(str(exc))
            else:
                QMessageBox.warning(self, "Tracking Settings", str(exc))
            return False

        crop_w = int(check.roi_oriented.width)
        crop_h = int(check.roi_oriented.height)
        min_dim = params.template_patch_size_px + (2 * params.search_radius_px) + 2
        if min(crop_w, crop_h) < min_dim:
            message = (
                f"The ROI ({crop_w}×{crop_h} px) is too small for patch size "
                f"{params.template_patch_size_px} and search radius "
                f"{params.search_radius_px}."
            )
            if quiet:
                self._show_metric_analysis_placeholder(message)
            else:
                QMessageBox.warning(self, _METRIC_ANALYSIS_VIEW_LABEL, message)
            return False

        if not quiet:
            self._status("Building metric analysis preview…")
        QApplication.processEvents()
        try:
            frames = load_cropped_frames_from_video(
                path,
                self._orientation,
                check.roi_oriented,
            )
            analysis = analyze_cropped_preview(frames, params=params)
        except Exception as exc:
            if quiet:
                self._show_metric_analysis_placeholder(str(exc))
            else:
                QMessageBox.warning(self, _METRIC_ANALYSIS_VIEW_LABEL, str(exc))
            return False

        self._enter_cropped_preview_mode(analysis, params=params)
        if self._current_sample_id:
            of_settings = self._optical_flow_settings_from_ui()
            roi_bounds = (
                int(check.roi_oriented.x),
                int(check.roi_oriented.y),
                int(check.roi_oriented.width),
                int(check.roi_oriented.height),
            )
            fingerprint = build_optical_flow_fingerprint(
                sample_id=self._current_sample_id,
                roi_bounds=roi_bounds,
                settings=of_settings,
                data_identity=str(path.resolve()),
                frame_count=len(frames),
            )
            of_result = compute_optical_flow_motion_index(
                frames,
                of_settings,
                sample_id=self._current_sample_id,
                data_identity=str(path.resolve()),
                roi_bounds=roi_bounds,
                fingerprint=fingerprint,
            )
            self._commit_optical_flow_result(self._current_sample_id, of_result)
        if resume_playback:
            self._preview_play()
        return True

    def _show_metric_analysis_placeholder(self, message: str) -> None:
        self._metric_analysis_view_active = True
        self._preview_pause()
        self._cropped_preview = None
        self._preview_frame_index = 0
        self._center_stack.setCurrentIndex(0)
        self._preview_mode = "cropped_tracking"
        self.canvas.set_interactive(False)
        self.canvas.clear_preview()
        self.btn_metric_analysis.hide()
        self._set_preview_controls_visible(False)
        self._set_metric_mode_widgets_visible(True)
        self._sync_metric_mode_combo()
        self._set_tracking_settings_editable(True)
        self._show_cropped_metric_settings_view()
        self._update_optical_flow_qc_readout()
        self.update_tracking_result_panel()
        self.lbl_preview_mode.setText(f"{_METRIC_ANALYSIS_VIEW_LABEL} — {message}")
        self.lbl_cropped_frame.setText("—")
        self.lbl_frame_info.setText("—")
        self._update_metric_analysis_button_visibility()

    def _set_preview_controls_visible(self, visible: bool) -> None:
        for widget in self._preview_control_widgets:
            widget.setVisible(visible)

    def _enter_cropped_preview_mode(
            self,
        analysis: CroppedPreviewAnalysis,
        *,
        params: Optional[MotionIndexParams] = None,
    ) -> None:
        self._preview_pause()
        self._center_stack.setCurrentIndex(0)
        self._metric_analysis_view_active = True
        self._preview_mode = "cropped_tracking"
        self._cropped_preview = analysis
        self._preview_frame_index = 0
        self.canvas.set_interactive(False)
        self.btn_metric_analysis.hide()
        self._set_preview_controls_visible(True)
        self._set_metric_mode_widgets_visible(True)
        self._sync_metric_mode_combo()
        self._set_tracking_settings_editable(True)
        self._show_cropped_metric_settings_view()
        self._update_optical_flow_qc_readout()
        if self._current_sample_id:
            commit_params = params or analysis.params
            if commit_params is None:
                try:
                    commit_params = self._tracking_params_from_ui()
                except ValueError:
                    commit_params = MotionIndexParams()
            self._commit_tracking_result(
                self._current_sample_id, analysis, commit_params
            )
        self.lbl_preview_mode.setText(_METRIC_ANALYSIS_VIEW_LABEL)
        count = max(1, len(analysis.frames))
        max_index = max(0, count - 1)
        self.slider_frame.setMaximum(max_index)
        self.spin_frame.setMaximum(max_index)
        self.slider_cropped_frame.setMaximum(max_index)
        self._show_cropped_preview_frame(0)
        if analysis.tracking_warning:
            self._status(
                f"{_METRIC_ANALYSIS_VIEW_LABEL} ready. {analysis.tracking_warning}"
            )
        else:
            self._status(f"{_METRIC_ANALYSIS_VIEW_LABEL} ready. Press Play to loop.")
        self._update_metric_analysis_button_visibility()

    def _exit_cropped_preview_mode(self) -> None:
        if not self._metric_analysis_view_active:
            self._set_tracking_settings_editable(False)
            self._show_roi_controls_view()
            return
        self._metric_analysis_view_active = False
        self._set_tracking_settings_editable(False)
        self.reset_preview_state(clear_image=False, reset_roi_controls=True)
        self.lbl_preview_mode.setText(self._FULL_PREVIEW_HINT)
        self._update_metric_analysis_button_visibility()
        if self._base_frame is not None:
            self.slider_frame.setMaximum(max(0, self._total_frames - 1))
            self.spin_frame.setMaximum(max(0, self._total_frames - 1))
            self.slider_frame.setValue(self._frame_index)
            self.spin_frame.setValue(self._frame_index)
            self._refresh_display(keep_roi=True)

    def _preview_playback_interval_ms(self) -> int:
        speed_map = {
            "0.25×": 0.25,
            "0.5×": 0.5,
            "1×": 1.0,
            "1.5×": 1.5,
            "2×": 2.0,
        }
        mult = speed_map.get(self.combo_preview_speed.currentText(), 1.0)
        fps = max(1.0, 5.0 * mult)
        return max(20, int(1000.0 / fps))

    def _preview_play(self) -> None:
        if self._preview_mode != "cropped_tracking" or self._cropped_preview is None:
            return
        self._preview_playing = True
        self._update_preview_timer_interval()

    def _update_preview_timer_interval(self) -> None:
        if self._preview_playing:
            self._preview_timer.start(self._preview_playback_interval_ms())

    def _on_preview_speed_changed(self, _text: str) -> None:
        if self._preview_mode != "cropped_tracking":
            return
        self._update_preview_timer_interval()

    def _preview_pause(self) -> None:
        self._preview_playing = False
        self._preview_timer.stop()

    def _on_preview_timer_tick(self) -> None:
        if self._cropped_preview is None:
            self._preview_pause()
            return
        count = len(self._cropped_preview.frames)
        if count <= 1:
            self._preview_pause()
            return
        next_index = self._preview_frame_index + 1
        if next_index >= count:
            next_index = 0
        self._show_cropped_preview_frame(next_index)

    def _on_cropped_preview_frame_slider(self, value: int) -> None:
        if self._preview_mode != "cropped_tracking" or self._cropped_preview is None:
            return
        if self._preview_playing:
            self._preview_pause()
        self._show_cropped_preview_frame(value)

    def _show_cropped_preview_frame(self, index: int) -> None:
        if self._cropped_preview is None:
            return
        count = len(self._cropped_preview.frames)
        index = max(0, min(index, count - 1))
        if self._cropped_metric_mode == "optical_flow":
            frame = self._cropped_preview.frames[index].copy()
            if (
                hasattr(self, "chk_show_of_overlay")
                and self.chk_show_of_overlay.isChecked()
            ):
                arrows = self._get_overlay_arrows_for_frame(index)
                if arrows:
                    frame = render_optical_flow_overlay(frame, arrows)
        else:
            frame = render_cropped_tracking_frame(self._cropped_preview, index)
        self._preview_frame_index = index
        self.canvas.set_preview_frame(frame)
        self.slider_frame.blockSignals(True)
        self.spin_frame.blockSignals(True)
        self.slider_cropped_frame.blockSignals(True)
        self.slider_frame.setValue(index)
        self.spin_frame.setValue(index)
        self.slider_cropped_frame.setValue(index)
        self.slider_frame.blockSignals(False)
        self.spin_frame.blockSignals(False)
        self.slider_cropped_frame.blockSignals(False)
        h, w = frame.shape[:2]
        frame_text = f"Frame {index + 1} / {count}"
        self.lbl_cropped_frame.setText(frame_text)
        self.lbl_frame_info.setText(
            f"Cropped preview {frame_text} ({w}×{h} px)"
        )

    def _on_auto_suggest_roi(self) -> None:
        oriented = self._oriented_frame()
        if oriented is None:
            return
        try:
            crop = detect_tracking_crop(oriented)
            self.canvas.set_rect_roi(tracking_crop_to_rect(crop))
            self._loaded_annotation_source = "auto_suggested"
            self._roi_user_adjusted = False
            self._autosave_roi(quiet=True)
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
        if self._roi_user_adjusted:
            if src in ("auto_suggested", "auto_suggested_adjusted"):
                return "auto_suggested_adjusted"
            if src in ("propagated", "propagated_adjusted"):
                return "propagated_adjusted"
            if src != "manual":
                return "propagated_adjusted"
        return src if src else "manual"

    def _suggestion_method_for_save(self) -> str | None:
        src = self._annotation_source_for_save()
        if src.startswith("auto_suggested"):
            return "f_actin_signal"
        return None

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
        ann_src = self._annotation_source_for_save()
        review = str(self._current_sample.get("review_status", "approved"))
        requires_review = status == STATUS_ROI_PROPAGATED
        if status == STATUS_ROI_MARKED and ann_src.startswith("auto_suggested"):
            review = "pending"
            requires_review = True
        elif status == STATUS_ROI_MARKED and ann_src.startswith("propagated"):
            review = "pending"
            requires_review = True
        roi_method = (
            "f_actin_signal_suggestion"
            if ann_src.startswith("auto_suggested")
            else "manual_rectangle"
        )
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
            annotation_source=ann_src,
            suggestion_method=self._suggestion_method_for_save(),
            roi_method=roi_method,
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
        if not self._autosave_roi(quiet=False):
            return
        sid = str(self._current_sample["sample_id"])
        self._refresh_sample_list()
        self._status(f"Saved ROI for {sid}")

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
            "ROI Pending Review",
            "This ROI is marked pending review (e.g. propagated annotation). "
            "Export anyway?",
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
            QMessageBox.warning(self, "Export ROI", "Data file not found for this sample.")
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
                "Current sample has no sample label in metadata. Re-import or migrate project.",
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
            "Review and adjust each propagated ROI as needed.",
        )

    def _on_process_approved_batch(self) -> None:
        if self._project_root is None or self._current_sample is None:
            return
        group = str(self._current_sample["group"])
        batch_name = sanitize_batch_name(str(self._current_sample.get("batch_name", "")))
        sample_label = display_sample_label(
            int(self._current_sample.get("batch_number", 1) or 1),
            batch_name,
        )
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
                "Sample Export",
                f"No ROI-marked data ready in {group} / {sample_label}.\n"
                f"Skipped (not marked or missing ROI): {pre_skipped}",
            )
            return
        reply = QMessageBox.question(
            self,
            "Process Marked ROIs in Sample",
            f"Breed: {group}\n"
            f"Sample: {sample_label}\n\n"
            f"Samples to export: {len(approved)}\n"
            f"Samples skipped: {pre_skipped}\n\n"
            "Only ROI-marked samples will be exported. Continue?",
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
            "Sample Export Complete",
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
            saved_breed = get_last_import_breed(root)
            if saved_breed:
                self._last_import_breed = saved_breed
            add_recent(root, root)
            self._refresh_recent_menu()
            self.btn_refresh_samples.setEnabled(True)
            self._update_workspace_label()
            self._set_active_sample(None)
            self.reset_preview_state(
                clear_image=True,
                placeholder=self._SELECT_SAMPLE_HINT,
            )
            self._refresh_sample_list()
            self._status(f"{status_msg}: {root}")
        except OSError as e:
            QMessageBox.critical(self, "Project Error", str(e))

    def _set_last_import_breed(self, breed: str | None) -> None:
        if not breed or breed not in GROUPS:
            return
        self._last_import_breed = breed
        if self._project_root is not None:
            set_last_import_breed(self._project_root, breed)

    def _on_filter_group_changed(self) -> None:
        self._set_last_import_breed(self.combo_filter_group.currentText())
        self._metric_analysis_view_active = False
        self._set_active_sample(None)
        self.reset_preview_state(
            clear_image=True,
            placeholder=self._SELECT_SAMPLE_HINT,
        )
        self._refresh_sample_list()
        self.update_tracking_result_panel()

    def _after_import_refresh(
            self,
        *,
        group: str | None = None,
        batch_name: str | None = None,
    ) -> None:
        if group and group in GROUPS:
            self.combo_filter_group.setCurrentText(group)
            self._set_last_import_breed(group)
        self._refresh_sample_list()
        if group and batch_name:
            self._select_first_video_in_batch(group, batch_name)

    def _select_first_video_in_batch(self, group: str, batch_name: str) -> None:
        safe = sanitize_batch_name(batch_name)
        for i in range(self.list_samples.count()):
            item = self.list_samples.item(i)
            meta = self._list_item_meta(item)
            if not meta or meta.get("item_type") != "sample":
                continue
            if str(meta.get("group")) != group:
                continue
            if sanitize_batch_name(str(meta.get("batch_name", ""))) != safe:
                continue
            self.list_samples.setCurrentItem(item)
            break

    def _ensure_filter_group_valid(self) -> str:
        """Keep a valid breed selected; fall back to the first."""
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
        sample_label = display_sample_label(num, name)
        if sanitize_batch_name(name) == sanitize_batch_name(display_batch_name(num)):
            return f"──── {group} / {sample_label} ────"
        return f"──── {group} / {sample_label}: {name} ────"

    def _context_batch_name(self, group: str | None = None) -> str | None:
        """Sample name for menu actions: current data file's sample, or ask if ambiguous."""
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
            "Select Sample",
            f"Choose a sample in {group}:",
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
                self, "Rename Sample", "No samples exist for this breed."
            )
            return None
        labels = [self._batch_list_header_text(group, b) for b in batches]
        names = [str(b["batch_name"]) for b in batches]
        picked, ok = QInputDialog.getItem(
            self,
            "Rename Sample",
            f"Sample to rename in {group}:",
            labels,
            0,
            False,
        )
        if not ok or not picked:
            return None
        return names[labels.index(picked)]

    def _on_add_sample(self, group: str | None = None) -> None:
        if self._project_root is None:
            QMessageBox.warning(
                self,
                "Add Sample",
                "Open or create a workspace first.",
            )
            return
        breed = group or self.combo_filter_group.currentText()
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Add Sample",
            str(self._default_import_dir()),
            DATA_IMPORT_FILTER,
        )
        if not path_str:
            return
        source = Path(path_str)
        self._last_import_dir = source.parent
        try:
            batch, _row = create_sample_from_data(self._project_root, breed, source)
        except ValueError as exc:
            QMessageBox.warning(self, "Add Sample", str(exc))
            return
        except OSError as exc:
            QMessageBox.warning(self, "Add Sample", f"Import failed: {exc}")
            return
        self._set_last_import_breed(breed)
        if self.combo_filter_group.currentText() != breed:
            self.combo_filter_group.setCurrentText(breed)
        if self._preview_mode == "cropped_tracking":
            self.reset_preview_state(clear_image=True)
        self._after_import_refresh(group=breed, batch_name=str(batch["batch_name"]))
        self._refresh_analysis_if_visible()
        label = display_sample_label(
            int(batch.get("batch_number", 1) or 1),
            str(batch.get("batch_name", "")),
        )
        self._status(f"Added {label} from {source.name}")

    def _select_sample_header(self, group: str, batch_name: str) -> None:
        safe = sanitize_batch_name(batch_name)
        for i in range(self.list_samples.count()):
            item = self.list_samples.item(i)
            meta = self._list_item_meta(item)
            if not meta or meta.get("item_type") != "batch_header":
                continue
            if str(meta.get("group")) == group and sanitize_batch_name(
                str(meta.get("batch_name", ""))
            ) == safe:
                self.list_samples.setCurrentItem(item)
                break

    def _on_new_batch(self) -> None:
        self._on_add_sample()

    def _on_rename_batch(self) -> None:
        if self._project_root is None:
            return
        group = self._ensure_filter_group_valid()
        old = self._pick_batch_name_to_rename(group)
        if not old:
            return
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Sample",
            "New sample name:",
            text=old,
        )
        if not ok or not new_name.strip():
            return
        try:
            rename_batch(self._project_root, group, old, new_name.strip())
            self._refresh_sample_list()
        except (ValueError, OSError) as e:
            QMessageBox.critical(self, "Rename Sample", str(e))

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

    def _add_sample_list_empty_row(self, group: str, batch: dict[str, Any]) -> None:
        item = QListWidgetItem("    (incomplete — right-click Replace Data)")
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setForeground(QBrush(QColor("#666666")))
        item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "item_type": "batch_empty",
                "group": group,
                "batch_name": str(batch.get("batch_name", "")),
                "batch_number": int(batch.get("batch_number", 1) or 1),
            },
        )
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

        sync_registry_from_samples(self._project_root)
        batches = list_batches(self._project_root, group)

        if not batches and not group_df.empty:
            sync_registry_from_samples(self._project_root)
            batches = list_batches(self._project_root, group)

        if not batches and group_df.empty:
            self._add_sample_list_message(
                "No samples available for this breed. Right-click to Add Sample."
            )
            self._set_active_sample(None)
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
                self._add_sample_list_empty_row(group, batch)
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
                self._set_active_sample(None)
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

    def _clear_preview_pane(self) -> None:
        self.lbl_selected_file.setText("No data selected.")
        self.lbl_auto_export_name.setText("Auto name: —")
        self.edit_export_name.clear()
        self.reset_preview_state(
            clear_image=True,
            placeholder=self._SELECT_SAMPLE_HINT,
        )

    def _on_sample_selected(
        self,
        current: Optional[QListWidgetItem],
        _previous: Optional[QListWidgetItem],
    ) -> None:
        if current is None:
            self._metric_analysis_view_active = False
            self._set_active_sample(None)
            self.reset_preview_state(
                clear_image=True,
                placeholder=self._SELECT_SAMPLE_HINT,
            )
            self.update_tracking_result_panel()
            return
        data = self._list_item_meta(current)
        if not data or data.get("item_type") != "sample":
            return

        was_metric_analysis_view = self._metric_analysis_view_active
        resume_playback = self._preview_playing if was_metric_analysis_view else False

        self._set_active_sample(data)
        group = str(data.get("group", ""))
        if group and group in GROUPS and self.combo_filter_group.currentText() != group:
            self.combo_filter_group.blockSignals(True)
            idx = self.combo_filter_group.findText(group)
            if idx >= 0:
                self.combo_filter_group.setCurrentIndex(idx)
            self.combo_filter_group.blockSignals(False)
        if data.get("processing_status") == "missing_file":
            return

        sid = str(data.get("sample_id", ""))
        self._preview_page.setUpdatesEnabled(False)
        try:
            if was_metric_analysis_view:
                self._clear_sample_specific_metric_state()
                self._ensure_metric_view_shell_visible()
                self.lbl_preview_mode.setText(f"{_METRIC_ANALYSIS_VIEW_LABEL} — loading…")
                if not self._load_sample_data_context(render_full_preview=False):
                    self._show_metric_analysis_placeholder(
                        "Metric Analysis View is unavailable because this Sample "
                        "does not have valid Data."
                    )
                else:
                    self.update_tracking_result_panel(sid)
                    if not self._reload_metric_analysis_view_for_current_sample(
                        resume_playback=resume_playback,
                    ):
                        self._schedule_debounced_metrics(show_scheduled=False)
            else:
                self.reset_preview_state(clear_image=True)
                self.update_tracking_result_panel(sid)
                self._load_full_roi_preview_for_current_sample()
        finally:
            self._preview_page.setUpdatesEnabled(True)
            self._preview_page.update()

    def _sample_file_path(self) -> Optional[Path]:
        if self._project_root is None or self._current_sample is None:
            return None
        return self._project_root / str(self._current_sample["stored_path"])

    def _restore_annotation(
        self, ann: dict[str, Any], *, render_canvas: bool = True
    ) -> None:
        self._apply_annotation_from_dict(ann, render_canvas=render_canvas)

    def _apply_annotation_from_dict(
        self, ann: dict[str, Any], *, render_canvas: bool = True
    ) -> None:
        self._orientation, roi = annotation_from_legacy(ann)
        self._reference_frame_index = int(ann.get("reference_frame_index", 0))
        self.txt_notes.setPlainText(str(ann.get("notes", "")))
        if render_canvas:
            self._refresh_display(keep_roi=False)
            if roi is not None:
                oriented = self._oriented_frame()
                if oriented is not None:
                    self.canvas.set_rect_roi(
                        roi.clamp(oriented.shape[1], oriented.shape[0])
                    )
        elif roi is not None:
            oriented = self._oriented_frame()
            if oriented is not None:
                self.canvas.set_rect_roi(
                    roi.clamp(oriented.shape[1], oriented.shape[0])
                )
            else:
                self.canvas.set_rect_roi(roi)
        else:
            self.canvas.set_rect_roi(None)
        self._loaded_annotation_source = str(ann.get("annotation_source", "manual"))
        self._roi_user_adjusted = False
        self._update_orientation_label()
        if self.canvas.rect_roi() is not None:
            self._set_roi_save_status("ROI autosaved", saved=True)
            if render_canvas:
                self._schedule_debounced_metrics(show_scheduled=False)
        else:
            self._set_roi_save_status("No ROI saved yet", saved=False)

    def _apply_auto_suggested_roi(self, *, render_canvas: bool) -> None:
        oriented = self._oriented_frame()
        if oriented is None:
            return
        try:
            crop = detect_tracking_crop(oriented)
            if crop.confidence >= AUTO_APPLY_ROI_CONFIDENCE:
                self.canvas.set_rect_roi(tracking_crop_to_rect(crop))
                self._loaded_annotation_source = "auto_suggested"
                self._roi_user_adjusted = False
        except ValueError:
            pass

    def _update_current_sample_panel_fields(
        self, sid: str, frame: np.ndarray, idx: int, total: int
    ) -> None:
        assert self._current_sample is not None
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

    def _load_sample_data_context(self, *, render_full_preview: bool = True) -> bool:
        path = self._sample_file_path()
        if path is None or not path.exists():
            if render_full_preview:
                QMessageBox.warning(self, "Load", "File not found.")
            return False
        if self._project_root is None or self._current_sample is None:
            return False
        sid = str(self._current_sample["sample_id"])
        ann = get_sample_annotation(self._project_root, sid)
        ref_idx = int(ann.get("reference_frame_index", 0)) if ann else 0
        try:
            frame, idx, total = load_media_frame(path, ref_idx)
        except MediaLoadError as e:
            if render_full_preview:
                QMessageBox.critical(self, "Load", str(e))
            return False
        self._base_frame = frame
        self._frame_index = idx
        self._reference_frame_index = idx
        self._total_frames = total
        self._orientation = OrientationState()
        self._update_current_sample_panel_fields(sid, frame, idx, total)

        if ann:
            self._apply_annotation_from_dict(ann, render_canvas=render_full_preview)
        elif render_full_preview:
            self._refresh_display(keep_roi=False)
            self._apply_auto_suggested_roi(render_canvas=True)
        else:
            self.canvas.set_rect_roi(None)
            self._apply_auto_suggested_roi(render_canvas=False)

        if render_full_preview:
            self._preview_mode = "full"
            self.lbl_preview_mode.setText(self._FULL_PREVIEW_HINT)
            self.update_tracking_result_panel()
            self._update_metric_analysis_button_visibility()
        return True

    def _load_full_roi_preview_for_current_sample(self) -> None:
        self._load_sample_data_context(render_full_preview=True)

    def _load_sample_preview(self) -> None:
        self._load_full_roi_preview_for_current_sample()

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
        if self._preview_mode == "cropped_tracking" and self._cropped_preview is not None:
            if self._preview_playing:
                self._preview_pause()
            self._show_cropped_preview_frame(index)
            return
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
        self._refresh_sample_list()
        self._status("Workspace refreshed")

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
        if prefer_sample_id:
            row = self._sample_row_for_id(prefer_sample_id)
            self._set_active_sample(row or {"sample_id": prefer_sample_id})
        else:
            self._set_active_sample(None)
        self._refresh_sample_list()
        self.update_tracking_result_panel()

    def _ask_remove_workspace_raw(self, title: str, text: str) -> bool | None:
        """Return True to remove internal copy, False to keep, None if cancelled."""
        chk = QCheckBox("Also remove the project's internal data copy")
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

    def _confirm_delete_sample(
        self,
        breed: str,
        sample_name: str,
        *,
        has_internal_copy: bool,
        incomplete: bool = False,
    ) -> bool | None:
        """Return whether to remove the project's internal data copy, or None if cancelled."""
        box = QMessageBox(self)
        box.setWindowTitle("Delete Sample?")
        box.setText(f'Delete "{sample_name}" from this Breed?')
        if incomplete:
            box.setInformativeText(
                "This will remove the incomplete Sample from the project."
            )
        else:
            box.setInformativeText(
                "This will remove the Sample from the project, including its ROI, "
                "tracking results, notes, and analysis data. "
                "The original data file on your computer will not be deleted."
            )
        internal_copy_chk: QCheckBox | None = None
        if has_internal_copy:
            internal_copy_chk = QCheckBox(
                "Also remove the project's internal data copy"
            )
            internal_copy_chk.setChecked(False)
            box.setCheckBox(internal_copy_chk)
        delete_btn = box.addButton(
            "Delete Sample", QMessageBox.ButtonRole.DestructiveRole
        )
        cancel_btn = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel_btn)
        box.exec()
        if box.clickedButton() is not delete_btn:
            return None
        if internal_copy_chk is not None:
            return internal_copy_chk.isChecked()
        return False

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
            QMessageBox.warning(
                self,
                "Sample List",
                "Open or create a workspace first.",
            )
            return
        item = self.list_samples.itemAt(pos)
        menu = QMenu(self)
        meta = self._list_item_meta(item)

        if meta and meta.get("item_type") in (
            "batch_header",
            "batch_empty",
            "sample",
        ):
            group = str(meta.get("group", self._ensure_filter_group_valid()))
            batch_name = str(meta.get("batch_name", ""))
            menu.addAction(
                "Rename Sample",
                lambda g=group, b=batch_name: self._ctx_rename_batch(g, b),
            )
            menu.addAction(
                "Delete Sample",
                lambda g=group, b=batch_name: self._ctx_delete_batch(g, b),
            )
            menu.addSeparator()
            menu.addAction(
                "Replace Data",
                lambda g=group, b=batch_name: self._ctx_replace_sample_data(g, b),
            )
        else:
            breed = self._ensure_filter_group_valid()
            add_action = menu.addAction(
                "Add Sample",
                lambda: self._on_add_sample(breed),
            )
            if breed not in GROUPS:
                add_action.setEnabled(False)
                menu.addAction("Please select a breed first.").setEnabled(False)

        if not menu.isEmpty():
            menu.exec(self.list_samples.viewport().mapToGlobal(pos))

    def _ctx_replace_sample_data(self, group: str, batch_name: str) -> None:
        if self._project_root is None or not group or not batch_name:
            QMessageBox.warning(
                self,
                "Replace Data",
                "Could not determine the sample for data replacement.",
            )
            return
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Replace Data",
            str(self._default_import_dir()),
            DATA_IMPORT_FILTER,
        )
        if not path_str:
            return
        source = Path(path_str)
        self._last_import_dir = source.parent
        row = get_primary_data_row(self._project_root, group, batch_name)
        if row and sample_has_derived_state(self._project_root, str(row["sample_id"])):
            reply = QMessageBox.question(
                self,
                "Replace Data",
                "This sample has ROI, tracking, or processed outputs.\n\n"
                "Replacing the data file will clear those derived results. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        if self._preview_mode == "cropped_tracking":
            self.reset_preview_state(clear_image=True)
        try:
            updated = replace_sample_data(
                self._project_root, group, batch_name, source
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Replace Data", str(exc))
            return
        except OSError as exc:
            QMessageBox.warning(self, "Replace Data", f"Import failed: {exc}")
            return
        final_batch_name = str(updated.get("batch_name", batch_name))
        self._set_last_import_breed(group)
        self.reset_preview_state(clear_image=True)
        self._after_import_refresh(group=group, batch_name=final_batch_name)
        self._refresh_analysis_if_visible()
        self._status(f"Replaced data for {final_batch_name} with {source.name}")

    def _ctx_rename_batch(self, group: str, batch_name: str) -> None:
        if self._project_root is None:
            return
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Sample",
            "New sample name:",
            text=batch_name,
        )
        if not ok or not new_name.strip():
            return
        try:
            rename_batch(self._project_root, group, batch_name, new_name.strip())
            self._refresh_sample_list()
            self._select_sample_header(group, sanitize_batch_name(new_name))
        except (ValueError, OSError) as e:
            QMessageBox.critical(self, "Rename Sample", str(e))

    def _ctx_purge_file_annotations(self, sample_id: str) -> None:
        if self._project_root is None:
            return
        reply = QMessageBox.question(
            self,
            "Purge Data Annotations",
            "Clear annotations, previews, and processed outputs for this data file?\n\n"
            "The data entry and workspace raw copy will be kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            stats = purge_sample_annotations_only(self._project_root, sample_id)
            self._invalidate_tracking_result_for_sample(sample_id)
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
            "Purge Selected Data Completely",
            "Remove this data file from the app database and delete its annotations, "
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
            self._invalidate_tracking_result_for_sample(sample_id)
            self._set_active_sample(None)
            self._after_purge_refresh()
            self._show_purge_summary("Purge Complete", stats)
            if group and batch_name and not batch_has_samples(
                self._project_root, group, batch_name
            ):
                num = parse_batch_number_from_name(batch_name) or 1
                sample_label = display_sample_label(num, batch_name)
                if (
                    QMessageBox.question(
                        self,
                        "Empty Sample",
                        f"{sample_label} is now empty. Delete the sample label too?",
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
            "Delete Data from Sample",
            "Delete this data file from the sample? This will remove its metadata, "
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
            self._invalidate_tracking_result_for_sample(sample_id)
            self._set_active_sample(None)
            self._after_purge_refresh()
            self._status(f"Deleted {sample_id} from sample")
            if group and batch_name and not batch_has_samples(
                self._project_root, group, batch_name
            ):
                num = parse_batch_number_from_name(batch_name) or 1
                sample_label = display_sample_label(num, batch_name)
                if (
                    QMessageBox.question(
                        self,
                        "Empty Sample",
                        f"{sample_label} is now empty. Delete the sample label too?",
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
        num = parse_batch_number_from_name(batch_name) or 1
        sample_label = display_sample_label(num, batch_name)
        reply = QMessageBox.question(
            self,
            "Purge Sample Annotations",
            f"Clear annotations and processed outputs for {sample_label}?\n\n"
            "Data entries and workspace raw copies will be kept.",
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
            "Complete Sample Purge",
            "This will completely remove this sample from the workspace. It will delete "
            "the sample label, all data entries in the app database, all annotations, "
            "previews, and processed outputs for this sample. Workspace raw copies can "
            "also be deleted if you choose. Original external source files will not be "
            "touched. This cannot be undone.",
            "PURGE SAMPLE",
        ):
            QMessageBox.information(
                self, "Cancelled", 'Type exactly "PURGE SAMPLE" to run this action.'
            )
            return
        remove_raw = self._ask_remove_workspace_raw(
            "Workspace Raw Copies",
            "Also remove workspace raw copies for this sample?",
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
            self._show_purge_summary("Complete Sample Purge", stats)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Purge", str(e))

    def _current_selection_in_batch(self, group: str, batch_name: str) -> bool:
        if not self._current_sample:
            return False
        return (
            str(self._current_sample.get("group", "")) == group
            and sanitize_batch_name(str(self._current_sample.get("batch_name", "")))
            == sanitize_batch_name(batch_name)
        )

    def _clear_preview_before_sample_delete(
        self, group: str, batch_name: str
    ) -> None:
        if (
            self._current_selection_in_batch(group, batch_name)
            or self._preview_mode == "cropped_tracking"
        ):
            self.reset_preview_state(
                clear_image=True,
                placeholder=self._SELECT_SAMPLE_HINT,
            )

    def _ctx_delete_batch(self, group: str, batch_name: str) -> None:
        if self._project_root is None:
            return
        sample_name = sanitize_batch_name(batch_name)
        has_files = batch_has_samples(self._project_root, group, batch_name)
        remove_internal_copy = self._confirm_delete_sample(
            group,
            sample_name,
            has_internal_copy=has_files,
            incomplete=not has_files,
        )
        if remove_internal_copy is None:
            return
        try:
            if has_files:
                stats = delete_sample_and_artifacts(
                    self._project_root,
                    group,
                    batch_name,
                    remove_workspace_raw=remove_internal_copy,
                )
                self._clear_preview_before_sample_delete(group, batch_name)
                self._set_active_sample(None)
                self._after_purge_refresh()
                self._refresh_analysis_if_visible()
                self._show_purge_summary("Sample Deleted", stats)
            else:
                delete_empty_batch(self._project_root, group, batch_name)
                self._clear_preview_before_sample_delete(group, batch_name)
                self._set_active_sample(None)
                self._after_purge_refresh()
                self._refresh_analysis_if_visible()
                self._status(f'Deleted Sample "{sample_name}"')
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Delete Sample", str(e))

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
        num = parse_batch_number_from_name(batch_name) or 1
        sample_label = display_sample_label(num, batch_name)
        reply = QMessageBox.question(
                self,
            "Delete Empty Sample",
            f"Delete empty sample '{sample_label}' from {group}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_empty_batch(self._project_root, group, batch_name)
            self._after_purge_refresh()
            self._status(f"Deleted empty sample {sample_label}")
        except ValueError as e:
            QMessageBox.warning(self, "Delete Sample", str(e))

    def _menu_delete_file_from_batch(self) -> None:
        if self._project_root is None or self._current_sample is None:
            QMessageBox.warning(self, "Delete", "Select a data file in the sample list first.")
            return
        sid = str(self._current_sample["sample_id"])
        self._ctx_delete_file(sid, self._current_sample)

    def _menu_review_batch(self) -> None:
        self._refresh_sample_list()
        self._status(
            "Review propagated annotations and adjust each ROI as needed."
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
            "orientation, ROI annotation, and cropped export for actin cable analysis.\n\n"
            "Suggest ROI from F-actin Signal is a computer vision helper that looks for areas "
            "in the image where bright, filament-like F-actin signal is strongest or most "
            "structured. It proposes a rectangular ROI that may contain usable actin cables "
            "while avoiding low-signal or blurry regions. The suggested ROI is not guaranteed "
            "to be correct. Treat it as a draft annotation that you can move, resize, approve, "
            "or reject.",
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
