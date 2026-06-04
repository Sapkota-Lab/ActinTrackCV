"""Preview canvas with draggable rectangular ROI."""

from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING, Optional

import cv2
import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QLabel

from actintrack_app.orientation import RectROI

if TYPE_CHECKING:
    from actintrack_app.gui import MainWindow


def numpy_bgr_to_qimage(frame: np.ndarray) -> QImage:
    h, w = frame.shape[:2]
    if frame.ndim == 2:
        bytes_per_line = w
        return QImage(
            frame.data, w, h, bytes_per_line, QImage.Format.Format_Grayscale8
        ).copy()
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    bytes_per_line = 3 * w
    return QImage(
        rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888
    ).copy()


class DragMode(Enum):
    NONE = auto()
    DRAW = auto()
    MOVE = auto()
    RESIZE = auto()


class ImageCanvas(QLabel):
    """Displays oriented frame with adjustable rectangular analysis ROI."""

    HANDLE_RADIUS = 8

    def __init__(self, main_window: MainWindow, parent=None):
        super().__init__(parent)
        self._main_window = main_window
        self.setMinimumSize(480, 360)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: #1e1e1e; border: 1px solid #444;")
        self._frame: Optional[np.ndarray] = None
        self._pixmap: Optional[QPixmap] = None
        self._roi: Optional[RectROI] = None
        self._scale = 1.0
        self._offset_x = 0
        self._offset_y = 0
        self._drag_mode = DragMode.NONE
        self._resize_handle: Optional[str] = None
        self._drag_start_img: Optional[tuple[int, int]] = None
        self._roi_at_drag_start: Optional[RectROI] = None
        self._cell_mask_overlay: Optional[np.ndarray] = None

    def clear_preview(self) -> None:
        self._frame = None
        self._pixmap = None
        self._roi = None
        self._cell_mask_overlay = None
        self.clear()

    def set_frame(self, frame: np.ndarray, *, keep_roi: bool = False) -> None:
        self._frame = frame
        if not keep_roi:
            self._roi = None
        elif self._roi is not None:
            self._roi = self._roi.clamp(frame.shape[1], frame.shape[0])
        self._update_pixmap()

    def set_cell_mask_overlay(self, mask: Optional[np.ndarray]) -> None:
        self._cell_mask_overlay = mask
        self._redraw()

    def set_rect_roi(self, roi: Optional[RectROI]) -> None:
        if self._frame is None:
            self._roi = roi
            return
        if roi is None:
            self._roi = None
        else:
            self._roi = roi.clamp(self._frame.shape[1], self._frame.shape[0])
        self._redraw()
        if roi is not None:
            self._main_window.on_roi_changed(self._roi)

    def rect_roi(self) -> Optional[RectROI]:
        return self._roi

    def _update_pixmap(self) -> None:
        if self._frame is None:
            self._pixmap = None
            self.clear()
            return
        display = self._frame.copy()
        if self._cell_mask_overlay is not None:
            contours, _ = cv2.findContours(
                (self._cell_mask_overlay > 0).astype(np.uint8),
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE,
            )
            cv2.drawContours(display, contours, -1, (255, 255, 0), 1)
        qimg = numpy_bgr_to_qimage(display)
        self._pixmap = QPixmap.fromImage(qimg)
        self._redraw()

    def _widget_to_image(self, wx: int, wy: int) -> Optional[tuple[int, int]]:
        if self._frame is None or self._pixmap is None:
            return None
        sx = wx - self._offset_x
        sy = wy - self._offset_y
        if sx < 0 or sy < 0:
            return None
        img_w, img_h = self._frame.shape[1], self._frame.shape[0]
        max_sx = int(img_w * self._scale)
        max_sy = int(img_h * self._scale)
        if sx > max_sx or sy > max_sy:
            return None
        ix = int(round(sx / self._scale))
        iy = int(round(sy / self._scale))
        return (
            max(0, min(ix, img_w - 1)),
            max(0, min(iy, img_h - 1)),
        )

    def _image_to_widget(self, ix: int, iy: int) -> tuple[int, int]:
        return (
            self._offset_x + int(ix * self._scale),
            self._offset_y + int(iy * self._scale),
        )

    def _handle_at(self, wx: int, wy: int) -> Optional[str]:
        if self._roi is None or self._frame is None:
            return None
        r = self._roi
        points = {
            "tl": (r.x, r.y),
            "tr": (r.x1, r.y),
            "bl": (r.x, r.y1),
            "br": (r.x1, r.y1),
            "tm": (r.x + r.width // 2, r.y),
            "bm": (r.x + r.width // 2, r.y1),
            "lm": (r.x, r.y + r.height // 2),
            "rm": (r.x1, r.y + r.height // 2),
        }
        hr = self.HANDLE_RADIUS
        for name, (ix, iy) in points.items():
            sx, sy = self._image_to_widget(ix, iy)
            if abs(wx - sx) <= hr and abs(wy - sy) <= hr:
                return name
        return None

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

        if self._roi is not None and self._frame is not None:
            r = self._roi
            x0, y0 = self._image_to_widget(r.x, r.y)
            x1, y1 = self._image_to_widget(r.x1, r.y1)
            pen = QPen(QColor(80, 220, 120), 2)
            painter.setPen(pen)
            painter.drawRect(x0, y0, x1 - x0, y1 - y0)
            painter.setFont(QFont("Helvetica", 9, QFont.Weight.Bold))
            painter.setPen(QColor(100, 220, 120))
            painter.drawText(x0 + 6, y0 + 16, "F-actin analysis ROI")
            for hx, hy in (
                (r.x, r.y),
                (r.x1, r.y),
                (r.x, r.y1),
                (r.x1, r.y1),
            ):
                sx, sy = self._image_to_widget(hx, hy)
                painter.setBrush(QBrush(QColor(80, 220, 120)))
                painter.drawEllipse(
                    sx - 4, sy - 4, 8, 8
                )

        painter.end()
        self.setPixmap(composite)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._redraw()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self._frame is None:
            return
        wx, wy = int(event.position().x()), int(event.position().y())
        img_pt = self._widget_to_image(wx, wy)
        if img_pt is None:
            return
        ix, iy = img_pt

        handle = self._handle_at(wx, wy)
        if handle and self._roi is not None:
            self._drag_mode = DragMode.RESIZE
            self._resize_handle = handle
            self._roi_at_drag_start = RectROI(
                self._roi.x, self._roi.y, self._roi.width, self._roi.height
            )
            self._drag_start_img = (ix, iy)
            return

        if self._roi is not None:
            r = self._roi
            if r.x <= ix < r.x1 and r.y <= iy < r.y1:
                self._drag_mode = DragMode.MOVE
                self._roi_at_drag_start = RectROI(r.x, r.y, r.width, r.height)
                self._drag_start_img = (ix, iy)
                return

        self._drag_mode = DragMode.DRAW
        self._drag_start_img = (ix, iy)
        self._roi = RectROI(ix, iy, 1, 1)
        self._redraw()

    def mouseMoveEvent(self, event):
        if self._drag_mode == DragMode.NONE or self._frame is None:
            return
        wx, wy = int(event.position().x()), int(event.position().y())
        img_pt = self._widget_to_image(wx, wy)
        if img_pt is None:
            return
        ix, iy = img_pt
        w_img, h_img = self._frame.shape[1], self._frame.shape[0]

        if self._drag_mode == DragMode.DRAW and self._drag_start_img is not None:
            x0, y0 = self._drag_start_img
            self._roi = RectROI.from_xyxy(x0, y0, ix, iy).clamp(w_img, h_img)
            self._redraw()
            self._main_window.on_roi_changed(self._roi)
            return

        if (
            self._drag_mode == DragMode.MOVE
            and self._roi_at_drag_start is not None
            and self._drag_start_img is not None
        ):
            dx = ix - self._drag_start_img[0]
            dy = iy - self._drag_start_img[1]
            r0 = self._roi_at_drag_start
            self._roi = RectROI(
                r0.x + dx, r0.y + dy, r0.width, r0.height
            ).clamp(w_img, h_img)
            self._redraw()
            self._main_window.on_roi_changed(self._roi)
            return

        if (
            self._drag_mode == DragMode.RESIZE
            and self._roi_at_drag_start is not None
            and self._resize_handle
        ):
            r0 = self._roi_at_drag_start
            x0, y0, x1, y1 = r0.x, r0.y, r0.x1, r0.y1
            if "l" in self._resize_handle:
                x0 = ix
            if "r" in self._resize_handle:
                x1 = ix
            if "t" in self._resize_handle:
                y0 = iy
            if "b" in self._resize_handle:
                y1 = iy
            self._roi = RectROI.from_xyxy(x0, y0, x1, y1).clamp(w_img, h_img)
            self._redraw()
            self._main_window.on_roi_changed(self._roi)

    def mouseReleaseEvent(self, event):
        self._drag_mode = DragMode.NONE
        self._resize_handle = None
        if self._roi is not None and self._roi.width < 4 and self._roi.height < 4:
            self._roi = None
            self._redraw()
