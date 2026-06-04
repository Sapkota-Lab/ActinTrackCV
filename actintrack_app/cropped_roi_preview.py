"""Live cropped ROI preview (video playback and image sequences) — preview only, no disk writes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import cv2
import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from actintrack_app.batch_manager import sanitize_batch_name
from actintrack_app.gui_canvas import numpy_bgr_to_qimage
from actintrack_app.orientation import (
    OrientationState,
    RectROI,
    apply_orientation,
    crop_rect_roi,
)
from actintrack_app.roi_workflow import (
    RoiValidationResult,
    is_wip_sample_path,
    validate_roi_for_sample,
)
from actintrack_app.sample_processor import get_video_fps
from actintrack_app.utils import METADATA_DIR, SAMPLES_CSV, VIDEO_EXTENSIONS
from actintrack_app.video_processing import MediaLoadError, get_video_frame_count

if TYPE_CHECKING:
    from actintrack_app.gui import MainWindow

DEFAULT_PLAYBACK_FPS = 6.0
FRAME_CACHE_MAX = 8


@dataclass
class CroppedPreviewContext:
    """Everything needed to scrub/play cropped ROI frames (read-only)."""

    mode: str  # "video" | "sequence" | "single_image"
    orientation: OrientationState
    roi_oriented: RectROI
    frame_count: int
    sample_id: str
    annotation_source: str
    review_status: str
    requires_review: bool
    video_path: Path | None = None
    image_paths: list[Path] | None = None
    playback_fps: float = DEFAULT_PLAYBACK_FPS


def validate_roi_for_frame(
    roi: RectROI | None,
    frame_width: int,
    frame_height: int,
    *,
    label: str = "ROI",
) -> RoiValidationResult:
    """Validate ROI against oriented frame dimensions (alias for roi_workflow.validate_roi)."""
    from actintrack_app.roi_workflow import validate_roi

    return validate_roi(roi, frame_width=frame_width, frame_height=frame_height, label=label)


def crop_frame_to_roi(frame: np.ndarray, roi: RectROI) -> np.ndarray:
    """Crop one BGR frame using ROI in the same coordinate space as the frame."""
    h, w = frame.shape[:2]
    return crop_rect_roi(frame, roi.clamp(w, h))


def load_video_frame_at(video_path: Path, frame_index: int) -> np.ndarray:
    """Load one video frame using OpenCV seek (does not load whole video into RAM)."""
    path = Path(video_path)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        cap.release()
        raise MediaLoadError(f"Cannot open video: {path}")
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        idx = max(0, int(frame_index))
        if total > 0 and idx >= total:
            raise MediaLoadError(
                f"Frame index {idx} out of range (0–{total - 1}) for {path.name}"
            )
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok or frame is None:
            raise MediaLoadError(f"Cannot read frame {idx} from {path.name}")
        return frame
    finally:
        cap.release()


def get_cropped_video_frame(
    video_path: Path,
    frame_index: int,
    orientation: OrientationState,
    roi_oriented: RectROI,
) -> np.ndarray:
    """Load one video frame, apply orientation, return cropped ROI region."""
    frame = load_video_frame_at(video_path, frame_index)
    oriented = apply_orientation(frame, orientation)
    return crop_frame_to_roi(oriented, roi_oriented)


def get_cropped_image_sequence_frame(
    image_paths: list[Path],
    index: int,
    orientation: OrientationState,
    roi_oriented: RectROI,
) -> np.ndarray:
    """Load one image from a sorted sequence and return cropped ROI."""
    if not image_paths:
        raise MediaLoadError("Image sequence is empty.")
    idx = max(0, min(int(index), len(image_paths) - 1))
    path = image_paths[idx]
    if not path.is_file():
        raise MediaLoadError(f"Image not found: {path}")
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise MediaLoadError(f"Cannot read image: {path.name}")
    oriented = apply_orientation(img, orientation)
    return crop_frame_to_roi(oriented, roi_oriented)


def list_batch_image_paths(
    root: Path,
    group: str,
    batch_name: str,
) -> list[Path]:
    """
    Still images in the same biological batch, ordered for sequence preview.

    Order: numeric frame_number from metadata when present, else filename sort.
    """
    import pandas as pd

    root = Path(root).resolve()
    df = pd.read_csv(root / METADATA_DIR / SAMPLES_CSV, dtype=str, keep_default_na=False)
    safe = sanitize_batch_name(batch_name)
    sub = df[
        (df["group"] == group)
        & (df["batch_name"].astype(str).apply(sanitize_batch_name) == safe)
    ]
    rows: list[tuple[int, str, Path]] = []
    for _, row in sub.iterrows():
        is_vid = str(row.get("is_video", "")).lower() == "true"
        if is_vid or str(row.get("file_type", "")) == "video":
            continue
        stored = str(row.get("stored_path", "")).strip()
        if not stored:
            continue
        path = root / stored
        if not path.is_file():
            continue
        try:
            fn = int(row.get("frame_number", 0) or 0)
        except ValueError:
            fn = 0
        rows.append((fn, str(row.get("original_filename", path.name)), path))
    if not rows:
        return []
    # Stable order: frame_number, then filename (explicit fallback when metadata sparse).
    rows.sort(key=lambda t: (t[0], t[1].lower()))
    return [p for _, _, p in rows]


def build_preview_context(
    *,
    root: Path,
    sample_row: dict,
    source_path: Path,
    orientation: OrientationState,
    roi_oriented: RectROI,
    reference_frame_index: int = 0,
    annotation: dict | None = None,
) -> CroppedPreviewContext:
    """Build playback context for video or batch image sequence."""
    root = Path(root).resolve()
    path = Path(source_path)
    ext = path.suffix.lower()
    is_video = ext in VIDEO_EXTENSIONS or str(sample_row.get("is_video", "")).lower() == "true"
    group = str(sample_row.get("group", ""))
    batch_name = str(sample_row.get("batch_name", ""))
    ann_src = str(sample_row.get("annotation_source", "manual"))
    review = str(sample_row.get("review_status", "approved"))
    requires = review == "pending"
    if annotation:
        ann_src = str(annotation.get("annotation_source", ann_src))
        review = str(annotation.get("review_status", review))
        requires = bool(annotation.get("requires_review")) or review == "pending"

    if is_video:
        count = get_video_frame_count(path)
        fps = get_video_fps(path)
        return CroppedPreviewContext(
            mode="video",
            orientation=orientation,
            roi_oriented=roi_oriented,
            frame_count=max(1, count),
            sample_id=str(sample_row.get("sample_id", "")),
            annotation_source=ann_src,
            review_status=review,
            requires_review=requires,
            video_path=path,
            playback_fps=fps,
        )

    image_paths = list_batch_image_paths(root, group, batch_name)
    if not image_paths:
        image_paths = [path]
        mode = "single_image"
    else:
        mode = "sequence" if len(image_paths) > 1 else "single_image"

    return CroppedPreviewContext(
        mode=mode,
        orientation=orientation,
        roi_oriented=roi_oriented,
        frame_count=len(image_paths),
        sample_id=str(sample_row.get("sample_id", "")),
        annotation_source=ann_src,
        review_status=review,
        requires_review=requires,
        image_paths=image_paths,
        playback_fps=DEFAULT_PLAYBACK_FPS,
    )


class CroppedROIPreviewDialog(QDialog):
    """
    Modal dialog for playing or scrubbing through cropped ROI frames.

    Reads raw files on demand; does not write processed outputs.
    """

    def __init__(
        self,
        parent: QWidget,
        context: CroppedPreviewContext,
        *,
        on_approve: Callable[[], None] | None = None,
        on_reject: Callable[[], None] | None = None,
        on_adjust: Callable[[], None] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Cropped ROI Preview")
        self.resize(720, 560)
        self._ctx = context
        self._on_approve = on_approve
        self._on_reject = on_reject
        self._on_adjust = on_adjust
        self._index = 0
        self._playing = False
        self._cache: dict[int, np.ndarray] = {}
        self._video_cap: cv2.VideoCapture | None = None

        layout = QVBoxLayout(self)

        self.lbl_warning = QLabel()
        self.lbl_warning.setWordWrap(True)
        self.lbl_warning.setStyleSheet("color: #cc8844; font-weight: bold;")
        if context.requires_review or context.review_status == "pending":
            self.lbl_warning.setText(
                "ROI is propagated and pending review. "
                "Preview is allowed; export still requires approval."
            )
            layout.addWidget(self.lbl_warning)
        elif context.annotation_source.startswith("propagated"):
            self.lbl_warning.setText(f"Annotation source: {context.annotation_source}")
            layout.addWidget(self.lbl_warning)

        self.lbl_image = QLabel("Loading…")
        self.lbl_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_image.setMinimumSize(480, 360)
        self.lbl_image.setStyleSheet("background-color: #1e1e1e; border: 1px solid #444;")
        layout.addWidget(self.lbl_image, stretch=1)

        self.lbl_frame = QLabel()
        layout.addWidget(self.lbl_frame)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(max(0, context.frame_count - 1))
        self.slider.valueChanged.connect(self._on_slider)
        layout.addWidget(self.slider)

        controls = QHBoxLayout()
        self.btn_play = QPushButton("Play")
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.clicked.connect(self._pause)
        self.combo_speed = QComboBox()
        self.combo_speed.addItems(["0.25×", "0.5×", "1×", "1.5×", "2×"])
        self.combo_speed.setCurrentText("1×")
        controls.addWidget(self.btn_play)
        controls.addWidget(self.btn_pause)
        controls.addWidget(QLabel("Speed:"))
        controls.addWidget(self.combo_speed)
        controls.addStretch()
        layout.addLayout(controls)

        review_row = QHBoxLayout()
        self.btn_approve = QPushButton("Approve ROI")
        self.btn_approve.clicked.connect(self._approve)
        self.btn_reject = QPushButton("Reject ROI")
        self.btn_reject.clicked.connect(self._reject)
        self.btn_adjust = QPushButton("Adjust ROI")
        self.btn_adjust.clicked.connect(self._adjust)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.accept)
        review_row.addWidget(self.btn_approve)
        review_row.addWidget(self.btn_reject)
        review_row.addWidget(self.btn_adjust)
        review_row.addStretch()
        review_row.addWidget(self.btn_close)
        layout.addLayout(review_row)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance_frame)

        if context.mode == "video" and context.video_path:
            self._video_cap = cv2.VideoCapture(str(context.video_path))
            if not self._video_cap.isOpened():
                self._video_cap.release()
                self._video_cap = None
                raise MediaLoadError(f"Cannot open video: {context.video_path}")

        self._show_frame(0)

    def closeEvent(self, event) -> None:
        self._release_video()
        super().closeEvent(event)

    def reject(self) -> None:
        self._release_video()
        super().reject()

    def accept(self) -> None:
        self._release_video()
        super().accept()

    def _release_video(self) -> None:
        self._timer.stop()
        if self._video_cap is not None:
            self._video_cap.release()
            self._video_cap = None

    def _playback_interval_ms(self) -> int:
        speed_map = {"0.25×": 0.25, "0.5×": 0.5, "1×": 1.0, "1.5×": 1.5, "2×": 2.0}
        mult = speed_map.get(self.combo_speed.currentText(), 1.0)
        fps = max(0.5, self._ctx.playback_fps * mult)
        return max(20, int(1000.0 / fps))

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
        if self._index >= self._ctx.frame_count - 1:
            self._pause()
            return
        self._show_frame(self._index + 1, from_timer=True)

    def _on_slider(self, value: int) -> None:
        if self._playing:
            self._pause()
        self._show_frame(value)

    def _load_cropped(self, index: int) -> np.ndarray:
        if index in self._cache:
            return self._cache[index]

        if self._ctx.mode == "video" and self._video_cap is not None:
            self._video_cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = self._video_cap.read()
            if not ok or frame is None:
                raise MediaLoadError(f"Cannot read video frame {index}")
            oriented = apply_orientation(frame, self._ctx.orientation)
            cropped = crop_frame_to_roi(oriented, self._ctx.roi_oriented)
        elif self._ctx.image_paths:
            cropped = get_cropped_image_sequence_frame(
                self._ctx.image_paths,
                index,
                self._ctx.orientation,
                self._ctx.roi_oriented,
            )
        else:
            raise MediaLoadError("No preview source configured.")

        if len(self._cache) >= FRAME_CACHE_MAX:
            self._cache.pop(next(iter(self._cache)))
        self._cache[index] = cropped
        return cropped

    def _show_frame(self, index: int, *, from_timer: bool = False) -> None:
        index = max(0, min(index, self._ctx.frame_count - 1))
        try:
            cropped = self._load_cropped(index)
        except MediaLoadError as e:
            QMessageBox.warning(self, "Preview", str(e))
            self._pause()
            return

        self._index = index
        self.slider.blockSignals(True)
        self.slider.setValue(index)
        self.slider.blockSignals(False)

        h, w = cropped.shape[:2]
        qimg = numpy_bgr_to_qimage(cropped)
        pix = QPixmap.fromImage(qimg)
        target = self.lbl_image.size()
        scaled = pix.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.lbl_image.setPixmap(scaled)
        mode_lbl = {
            "video": "Video",
            "sequence": "Image sequence",
            "single_image": "Still image",
        }.get(self._ctx.mode, "Preview")
        self.lbl_frame.setText(
            f"{mode_lbl} — frame {index + 1} / {self._ctx.frame_count}  "
            f"(cropped {w}×{h} px)"
        )

    def _approve(self) -> None:
        if self._on_approve:
            self._on_approve()
        self.accept()

    def _reject(self) -> None:
        if self._on_reject:
            self._on_reject()
        self.accept()

    def _adjust(self) -> None:
        if self._on_adjust:
            self._on_adjust()
        self.reject()


def open_cropped_roi_preview(
    main_window: "MainWindow",
    *,
    sample_row: dict,
    source_path: Path,
    orientation: OrientationState,
    roi_validation: RoiValidationResult,
    annotation: dict | None = None,
) -> None:
    """Validate and open live cropped ROI preview (no file writes)."""
    if roi_validation.roi_oriented is None:
        QMessageBox.warning(
            main_window,
            "Preview Cropped ROI",
            "Please draw or load a rectangular ROI before previewing the cropped region.",
        )
        return

    try:
        ctx = build_preview_context(
            root=main_window._project_root,
            sample_row=sample_row,
            source_path=source_path,
            orientation=orientation,
            roi_oriented=roi_validation.roi_oriented,
            annotation=annotation,
        )
    except MediaLoadError as e:
        QMessageBox.critical(main_window, "Preview Cropped ROI", str(e))
        return

    dlg = CroppedROIPreviewDialog(
        main_window,
        ctx,
        on_approve=lambda: main_window._on_approve_roi(),
        on_reject=lambda: main_window._on_reject_roi(),
        on_adjust=lambda: None,
    )
    dlg.exec()
