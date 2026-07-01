"""Explorer tree widget with internal Sample drag/drop between Condition Groups."""

from __future__ import annotations

from PyQt6.QtCore import QMimeData, Qt, pyqtSignal
from PyQt6.QtGui import QDrag, QColor, QFontMetrics, QPainter, QPixmap
from PyQt6.QtWidgets import QAbstractItemView, QTreeWidget, QTreeWidgetItem

from actintrack_app.explorer_sidebar import (
    EXPLORER_SAMPLE_MIME,
    is_draggable_sample_meta,
    is_valid_sample_drop_target_meta,
    sample_sidebar_display_label,
    tree_item_condition_group_id,
)


def _drag_pixmap_for_label(label: str, font_metrics: QFontMetrics) -> QPixmap:
    text = label.strip() or "Sample"
    padding_x = 12
    padding_y = 6
    width = max(64, font_metrics.horizontalAdvance(text) + padding_x * 2)
    height = font_metrics.height() + padding_y * 2
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor(45, 45, 48, 235))
    painter = QPainter(pixmap)
    painter.setPen(QColor(230, 230, 230))
    painter.drawText(padding_x, padding_y + font_metrics.ascent(), text)
    painter.end()
    return pixmap


class ExplorerTreeWidget(QTreeWidget):
    """QTreeWidget that drags one Sample at a time onto a Condition Group target."""

    sample_drop_requested = pyqtSignal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    @staticmethod
    def _item_meta(item: QTreeWidgetItem | None) -> dict | None:
        if item is None:
            return None
        data = item.data(0, Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else None

    def _drop_target_group_id(self, item: QTreeWidgetItem | None) -> str | None:
        meta = self._item_meta(item)
        if not is_valid_sample_drop_target_meta(meta):
            return None
        return tree_item_condition_group_id(meta)

    def startDrag(self, supportedActions) -> None:  # noqa: N802
        item = self.currentItem()
        meta = self._item_meta(item)
        if not is_draggable_sample_meta(meta):
            return
        sample_id = str(meta.get("sample_id", "")).strip()
        if not sample_id:
            return
        mime = QMimeData()
        mime.setData(EXPLORER_SAMPLE_MIME, sample_id.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        label = sample_sidebar_display_label(meta)
        pixmap = _drag_pixmap_for_label(label, QFontMetrics(self.font()))
        drag.setPixmap(pixmap)
        drag.setHotSpot(pixmap.rect().center())
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if not event.mimeData().hasFormat(EXPLORER_SAMPLE_MIME):
            event.ignore()
            return
        target_gid = self._drop_target_group_id(self.itemAt(event.position().toPoint()))
        if target_gid:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if not event.mimeData().hasFormat(EXPLORER_SAMPLE_MIME):
            event.ignore()
            return
        target_gid = self._drop_target_group_id(self.itemAt(event.position().toPoint()))
        if target_gid:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        if not event.mimeData().hasFormat(EXPLORER_SAMPLE_MIME):
            event.ignore()
            return
        sample_id = bytes(event.mimeData().data(EXPLORER_SAMPLE_MIME)).decode("utf-8")
        target_gid = self._drop_target_group_id(self.itemAt(event.position().toPoint()))
        if not sample_id or not target_gid:
            event.ignore()
            return
        self.sample_drop_requested.emit(sample_id, target_gid)
        event.acceptProposedAction()
