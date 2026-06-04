"""Application menu bar and purge/cleanup dialogs."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from actintrack_app.utils import GROUPS

if TYPE_CHECKING:
    from actintrack_app.gui import MainWindow


class PurgeFilteredDialog(QDialog):
    def __init__(self, parent: QWidget, root: Path):
        super().__init__(parent)
        self.setWindowTitle("Filtered Purge — Preview")
        self._root = Path(root).resolve()
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.combo_group = QComboBox()
        self.combo_group.addItem("(any condition)", "")
        for g in GROUPS:
            self.combo_group.addItem(g, g)
        self.edit_batch = QLineEdit()
        self.edit_batch.setPlaceholderText("Batch name or number (optional)")
        self.combo_status = QComboBox()
        self.combo_status.addItem("(any status)", "")
        for s in (
            "raw_imported",
            "unannotated",
            "imported",
            "roi_marked",
            "roi_propagated_needs_review",
            "roi_approved",
            "processed",
            "failed",
            "missing_file",
        ):
            self.combo_status.addItem(s, s)
        self.combo_file_type = QComboBox()
        self.combo_file_type.addItems(["(any)", "video", "image", "tiff"])
        self.combo_annotation = QComboBox()
        self.combo_annotation.addItems(
            ["(any)", "manual", "propagated", "automatic"]
        )
        self.combo_review = QComboBox()
        self.combo_review.addItems(["(any)", "pending", "approved", "rejected"])
        form.addRow("Condition group:", self.combo_group)
        form.addRow("Batch name/number:", self.edit_batch)
        form.addRow("Processing status:", self.combo_status)
        form.addRow("File type:", self.combo_file_type)
        form.addRow("Annotation source:", self.combo_annotation)
        form.addRow("Review status:", self.combo_review)
        layout.addLayout(form)

        self.list_preview = QListWidget()
        layout.addWidget(QLabel("Affected samples (annotations/processed will be purged):"))
        layout.addWidget(self.list_preview)

        btn_row = QHBoxLayout()
        self.btn_refresh = QPushButton("Update Preview")
        self.btn_refresh.clicked.connect(self._update_preview)
        btn_row.addWidget(self.btn_refresh)
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_preview()

    def _filters(self) -> dict:
        from actintrack_app.batch_manager import sanitize_batch_name

        group = self.combo_group.currentData() or None
        batch_text = self.edit_batch.text().strip()
        batch_name = None
        batch_number = None
        if batch_text:
            if batch_text.isdigit():
                batch_number = int(batch_text)
            else:
                batch_name = batch_text
        status = self.combo_status.currentData() or None
        if status == "":
            status = None
        ft = self.combo_file_type.currentText()
        file_type = None if ft.startswith("(") else ft
        ann = self.combo_annotation.currentText()
        annotation_source = None if ann.startswith("(") else ann
        rev = self.combo_review.currentText()
        review_status = None if rev.startswith("(") else rev
        return {
            "group": group or None,
            "batch_name": batch_name,
            "batch_number": batch_number,
            "processing_status": status,
            "file_type": file_type,
            "annotation_source": annotation_source,
            "review_status": review_status,
        }

    def _update_preview(self) -> None:
        from actintrack_app.purge_manager import filter_samples_for_purge

        self.list_preview.clear()
        df = filter_samples_for_purge(self._root, **self._filters())
        for _, row in df.iterrows():
            self.list_preview.addItem(
                f"{row['sample_id']}  {row.get('final_export_name', '')}  "
                f"[{row.get('processing_status', '')}]  {row.get('original_filename', '')}"
            )
        if df.empty:
            self.list_preview.addItem("(no samples match filters)")

    def selected_sample_ids(self) -> list[str]:
        from actintrack_app.purge_manager import filter_samples_for_purge

        df = filter_samples_for_purge(self._root, **self._filters())
        return df["sample_id"].astype(str).tolist()


class GlobalPurgeConfirmDialog(QDialog):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("Purge All Annotated/Processed Data")
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "This will delete all annotations, ROI selections, previews, "
                "processed outputs, and exported cropped files across the workspace. "
                "Raw files will be kept. This cannot be undone."
            )
        )
        layout.addWidget(QLabel("Type PURGE to confirm:"))
        self.edit_confirm = QLineEdit()
        layout.addWidget(self.edit_confirm)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._try_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _try_accept(self) -> None:
        if self.edit_confirm.text().strip() == "PURGE":
            self.accept()
        else:
            QMessageBox.warning(
                self,
                "Confirmation Required",
                'You must type exactly "PURGE" to continue.',
            )


def setup_application_menus(window: "MainWindow") -> None:
    """File / Workspace / Batch / Help — native menu bar on macOS and Windows."""
    mb = window.menuBar()

    file_menu = mb.addMenu("&File")
    act_new = QAction("&New Workspace…", window)
    act_new.triggered.connect(window._menu_new_workspace)
    file_menu.addAction(act_new)

    act_open = QAction("&Open Workspace…", window)
    act_open.triggered.connect(window._on_select_project)
    file_menu.addAction(act_open)

    window._recent_menu = file_menu.addMenu("Recent &Workspaces")
    window._refresh_recent_menu()

    file_menu.addSeparator()
    act_import = QAction("Import &Data…", window)
    act_import.triggered.connect(window._menu_import_data)
    file_menu.addAction(act_import)

    file_menu.addSeparator()
    act_exit = QAction("E&xit", window)
    act_exit.triggered.connect(window.close)
    file_menu.addAction(act_exit)

    ws_menu = mb.addMenu("&Workspace")
    act_refresh = QAction("&Refresh Workspace", window)
    act_refresh.triggered.connect(window._menu_refresh_workspace)
    ws_menu.addAction(act_refresh)

    act_open_folder = QAction("Open Workspace &Folder", window)
    act_open_folder.triggered.connect(window._menu_open_workspace_folder)
    ws_menu.addAction(act_open_folder)

    act_remove_missing = QAction("Remove Missing Files…", window)
    act_remove_missing.setToolTip(
        "Remove samples whose raw files are missing from workspace metadata."
    )
    act_remove_missing.triggered.connect(window._on_remove_missing_samples)
    ws_menu.addAction(act_remove_missing)

    ws_menu.addSeparator()
    from actintrack_app.purge_cleanup_dialog import open_purge_cleanup_dialog

    act_purge_cleanup = QAction("Purge / &Cleanup…", window)
    act_purge_cleanup.triggered.connect(lambda: open_purge_cleanup_dialog(window))
    ws_menu.addAction(act_purge_cleanup)

    act_purge_filtered = QAction("Filtered Purge (advanced)…", window)
    act_purge_filtered.triggered.connect(window._menu_purge_filtered)
    ws_menu.addAction(act_purge_filtered)

    batch_menu = mb.addMenu("&Batch")
    act_create = QAction("&Create Batch…", window)
    act_create.triggered.connect(window._on_new_batch)
    batch_menu.addAction(act_create)

    act_rename = QAction("&Rename Batch…", window)
    act_rename.triggered.connect(window._on_rename_batch)
    batch_menu.addAction(act_rename)

    act_delete_empty = QAction("Delete &Empty Batch…", window)
    act_delete_empty.triggered.connect(window._menu_delete_empty_batch)
    batch_menu.addAction(act_delete_empty)

    batch_menu.addSeparator()
    act_propagate = QAction("Apply Annotation to &Batch…", window)
    act_propagate.triggered.connect(window._on_propagate_batch)
    batch_menu.addAction(act_propagate)

    act_process_batch = QAction("Process Approved Samples in &Batch…", window)
    act_process_batch.triggered.connect(window._on_process_approved_batch)
    batch_menu.addAction(act_process_batch)

    act_delete_file = QAction("Delete Selected File from &Batch…", window)
    act_delete_file.triggered.connect(window._menu_delete_file_from_batch)
    batch_menu.addAction(act_delete_file)

    act_review = QAction("Review Batch Annotations", window)
    act_review.triggered.connect(window._menu_review_batch)
    batch_menu.addAction(act_review)

    help_menu = mb.addMenu("&Help")
    act_how = QAction("How to Run App", window)
    act_how.triggered.connect(window._menu_how_to_run)
    help_menu.addAction(act_how)

    act_about = QAction("About ActinTrackCV", window)
    act_about.triggered.connect(window._menu_about)
    help_menu.addAction(act_about)


def refresh_recent_workspaces_menu(window: "MainWindow") -> None:
    from actintrack_app.recent_workspaces import load_recent

    window._recent_menu.clear()
    if window._project_root is None:
        empty = window._recent_menu.addAction("(none)")
        empty.setEnabled(False)
        return
    paths = load_recent(window._project_root)
    if not paths:
        empty = window._recent_menu.addAction("(none)")
        empty.setEnabled(False)
        return
    for p in paths:
        act = QAction(p, window)
        act.triggered.connect(
            lambda checked=False, path=p: window._load_project(
                Path(path), "Recent workspace"
            )
        )
        window._recent_menu.addAction(act)
