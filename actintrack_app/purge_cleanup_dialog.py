"""Workspace Purge / Cleanup dialog with tiered purge actions."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QVBoxLayout,
)

from actintrack_app.batch_manager import list_batches, list_empty_batches
from actintrack_app.purge_manager import (
    complete_batch_purge,
    complete_condition_purge,
    complete_workspace_purge,
    purge_all_annotations_only,
    purge_batch_annotations,
    purge_condition_annotations,
    purge_sample_annotations_only,
    purge_sample_completely,
)
from actintrack_app.utils import GROUPS

if TYPE_CHECKING:
    from actintrack_app.gui import MainWindow

PURGE_ACTIONS: list[tuple[str, str, str | None]] = [
    (
        "purge_annotations_file",
        "1. Purge Annotations Only (selected file)",
        None,
    ),
    (
        "purge_complete_file",
        "2. Purge Selected File Completely",
        None,
    ),
    (
        "purge_annotations_batch",
        "3. Purge Batch Annotations Only",
        None,
    ),
    (
        "purge_complete_batch",
        "4. Complete Batch Purge",
        "PURGE BATCH",
    ),
    (
        "purge_annotations_condition",
        "5. Purge Condition Annotations Only",
        None,
    ),
    (
        "purge_complete_condition",
        "6. Complete Condition Purge",
        "PURGE CONDITION",
    ),
    (
        "purge_annotations_workspace",
        "7. Purge All Annotations Only (workspace)",
        None,
    ),
    (
        "purge_complete_workspace",
        "8. Complete Workspace Purge",
        "PURGE WORKSPACE",
    ),
]

ACTION_DESCRIPTIONS = {
    "purge_annotations_file": (
        "Removes ROI annotations, crop metadata, previews, and processed outputs "
        "for the selected file. Keeps the file entry, batch, and workspace raw copy."
    ),
    "purge_complete_file": (
        "Removes the selected file from the app database plus all annotations, "
        "previews, and processed outputs. Workspace raw copy can be removed if you "
        "check the option below. Original external files are never deleted."
    ),
    "purge_annotations_batch": (
        "Clears annotations and processed outputs for every file in the chosen batch. "
        "Keeps batch label, file entries, and workspace raw copies."
    ),
    "purge_complete_batch": (
        "Completely removes the batch from the workspace: batch label, all file "
        "entries (including unannotated), annotations, previews, and processed outputs. "
        "Workspace raw copies optional. Original external files are not touched."
    ),
    "purge_annotations_condition": (
        "Clears annotations and processed outputs for all batches in the selected "
        "condition group. Keeps batches and imported file entries."
    ),
    "purge_complete_condition": (
        "Removes all batches and file entries for the selected condition group from "
        "the app database, plus all annotations and processed outputs."
    ),
    "purge_annotations_workspace": (
        "Clears all annotations and processed outputs across the workspace. "
        "Keeps all batches and imported file entries."
    ),
    "purge_complete_workspace": (
        "Removes all workspace metadata: every condition, batch, file entry, "
        "annotation, preview, and processed output."
    ),
}


class PurgeCleanupDialog(QDialog):
    def __init__(
        self,
        parent: "MainWindow",
        root: Path,
        *,
        default_group: str,
        current_sample_id: str | None,
        current_batch_name: str | None,
    ):
        super().__init__(parent)
        self._window = parent
        self._root = Path(root).resolve()
        self._default_group = default_group
        self._current_sample_id = current_sample_id
        self._current_batch_name = current_batch_name

        self.setWindowTitle("Purge / Cleanup")
        self.resize(520, 480)
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Choose a cleanup level. “Annotations only” keeps files and batches in the "
            "database. “Complete” removes file or batch entries from the app. "
            "Original files outside the workspace are never deleted."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.list_actions = QListWidget()
        for _key, label, _confirm in PURGE_ACTIONS:
            self.list_actions.addItem(label)
        self.list_actions.currentRowChanged.connect(self._on_action_changed)
        layout.addWidget(self.list_actions)

        self.lbl_description = QLabel("")
        self.lbl_description.setWordWrap(True)
        self.lbl_description.setStyleSheet("color: #666;")
        layout.addWidget(self.lbl_description)

        scope_box = QGroupBox("Scope")
        scope_layout = QFormLayout(scope_box)
        self.combo_group = QComboBox()
        self.combo_group.addItems(list(GROUPS))
        idx = self.combo_group.findText(default_group)
        if idx >= 0:
            self.combo_group.setCurrentIndex(idx)
        self.combo_batch = QComboBox()
        self._refresh_batch_combo()
        scope_layout.addRow("Condition group:", self.combo_group)
        scope_layout.addRow("Batch:", self.combo_batch)
        layout.addWidget(scope_box)

        self.chk_remove_raw = QCheckBox(
            "Also remove workspace raw copies in raw/ (default: keep raw copies)"
        )
        self.chk_remove_raw.setChecked(False)
        layout.addWidget(self.chk_remove_raw)

        confirm_box = QGroupBox("Confirmation")
        confirm_layout = QVBoxLayout(confirm_box)
        self.lbl_confirm_hint = QLabel("")
        self.lbl_confirm_hint.setWordWrap(True)
        self.edit_confirm = QLineEdit()
        self.edit_confirm.setPlaceholderText("Type required phrase here")
        confirm_layout.addWidget(self.lbl_confirm_hint)
        confirm_layout.addWidget(self.edit_confirm)
        layout.addWidget(confirm_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_run)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.combo_group.currentTextChanged.connect(self._refresh_batch_combo)
        self.list_actions.setCurrentRow(0)
        self._on_action_changed(0)

    def _action_key(self) -> str:
        row = self.list_actions.currentRow()
        if row < 0:
            row = 0
        return PURGE_ACTIONS[row][0]

    def _confirm_phrase(self) -> str | None:
        row = self.list_actions.currentRow()
        if row < 0:
            return None
        return PURGE_ACTIONS[row][2]

    def _on_action_changed(self, row: int) -> None:
        if row < 0:
            return
        key = PURGE_ACTIONS[row][0]
        self.lbl_description.setText(ACTION_DESCRIPTIONS.get(key, ""))
        phrase = PURGE_ACTIONS[row][2]
        needs_batch = key in (
            "purge_annotations_batch",
            "purge_complete_batch",
        )
        needs_file = key in (
            "purge_annotations_file",
            "purge_complete_file",
        )
        self.combo_batch.setEnabled(needs_batch)
        if phrase:
            self.lbl_confirm_hint.setText(f'Type exactly "{phrase}" to continue:')
            self.edit_confirm.setEnabled(True)
        else:
            self.lbl_confirm_hint.setText("No typed confirmation required for this action.")
            self.edit_confirm.clear()
            self.edit_confirm.setEnabled(False)

    def _refresh_batch_combo(self) -> None:
        group = self.combo_group.currentText()
        batches = list_batches(self._root, group)
        self.combo_batch.clear()
        for batch in batches:
            self.combo_batch.addItem(str(batch["batch_name"]), batch)
        if self._current_batch_name:
            idx = self.combo_batch.findText(self._current_batch_name)
            if idx >= 0:
                self.combo_batch.setCurrentIndex(idx)

    def _on_run(self) -> None:
        key = self._action_key()
        phrase = self._confirm_phrase()
        if phrase and self.edit_confirm.text().strip() != phrase:
            QMessageBox.warning(
                self,
                "Confirmation Required",
                f'You must type exactly "{phrase}" to run this action.',
            )
            return

        group = self.combo_group.currentText()
        batch_name = self.combo_batch.currentText().strip()
        remove_raw = self.chk_remove_raw.isChecked()

        try:
            stats = self._execute(key, group, batch_name, remove_raw)
        except ValueError as e:
            QMessageBox.warning(self, "Purge", str(e))
            return
        except OSError as e:
            QMessageBox.critical(self, "Purge Failed", f"File operation failed:\n{e}")
            return
        except Exception as e:
            QMessageBox.critical(self, "Purge Failed", str(e))
            return

        summary = "\n".join(f"  • {k}: {v}" for k, v in stats.items())
        QMessageBox.information(self, "Purge Complete", f"Operation finished.\n\n{summary}")
        self.accept()

    def _execute(
        self,
        key: str,
        group: str,
        batch_name: str,
        remove_raw: bool,
    ) -> dict[str, Any]:
        if key == "purge_annotations_file":
            sid = self._require_sample_id()
            return purge_sample_annotations_only(self._root, sid)
        if key == "purge_complete_file":
            sid = self._require_sample_id()
            return purge_sample_completely(
                self._root, sid, remove_workspace_raw=remove_raw
            )
        if key == "purge_annotations_batch":
            batch = self._require_batch_name(group, batch_name)
            return purge_batch_annotations(self._root, group, batch)
        if key == "purge_complete_batch":
            batch = self._require_batch_name(group, batch_name)
            return complete_batch_purge(
                self._root, group, batch, remove_workspace_raw=remove_raw
            )
        if key == "purge_annotations_condition":
            return purge_condition_annotations(self._root, group)
        if key == "purge_complete_condition":
            return complete_condition_purge(
                self._root, group, remove_workspace_raw=remove_raw
            )
        if key == "purge_annotations_workspace":
            return purge_all_annotations_only(self._root)
        if key == "purge_complete_workspace":
            return complete_workspace_purge(self._root, remove_workspace_raw=remove_raw)
        raise ValueError(f"Unknown purge action: {key}")

    def _require_sample_id(self) -> str:
        if self._current_sample_id:
            return self._current_sample_id
        raise ValueError("Select a file in the sample list first.")

    def _require_batch_name(self, group: str, batch_name: str) -> str:
        if batch_name:
            return batch_name
        raise ValueError("Select a batch in the Scope section.")


def open_purge_cleanup_dialog(window: "MainWindow") -> None:
    if window._project_root is None:
        QMessageBox.warning(window, "Purge", "Open a workspace first.")
        return
    sid = None
    batch = None
    if window._current_sample:
        sid = str(window._current_sample.get("sample_id", ""))
        batch = str(window._current_sample.get("batch_name", ""))
    dlg = PurgeCleanupDialog(
        window,
        window._project_root,
        default_group=window._ensure_filter_group_valid(),
        current_sample_id=sid or None,
        current_batch_name=batch or None,
    )
    if dlg.exec() == QDialog.DialogCode.Accepted:
        window._after_purge_refresh()


def pick_empty_batch_name(parent: "MainWindow", root: Path, group: str) -> str | None:
    """List all empty batches in a condition group (fixes biased batch picker)."""
    empty = list_empty_batches(root, group)
    if not empty:
        QMessageBox.information(
            parent,
            "Delete Empty Batch",
            "No empty batches in this condition group.",
        )
        return None
    labels = [parent._batch_list_header_text(group, b) for b in empty]
    names = [str(b["batch_name"]) for b in empty]
    picked, ok = QInputDialog.getItem(
        parent,
        "Delete Empty Batch",
        f"Empty batches in {group} (select one to delete):",
        labels,
        0,
        False,
    )
    if not ok or not picked:
        return None
    try:
        return names[labels.index(picked)]
    except ValueError:
        return None
