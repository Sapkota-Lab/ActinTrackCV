"""PyQt widgets for the read-only Analysis view."""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QGroupBox,
    QHeaderView,
    QLabel,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from actintrack_app.analysis_service import (
    AnalysisReport,
    BreedComparisonRow,
    BreedSummaryRow,
    SampleAnalysisRow,
)


def _fmt_float(value: Optional[float], *, places: int = 4) -> str:
    if value is None:
        return "—"
    return f"{value:.{places}f}"


def _fmt_int(value: Optional[int]) -> str:
    if value is None:
        return "—"
    return str(value)


def _set_table_cell(
    table: QTableWidget,
    row: int,
    col: int,
    text: str,
    *,
    sort_value: Any = None,
    numeric: bool = False,
) -> None:
    item = QTableWidgetItem(text)
    if numeric:
        item.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        if sort_value is not None:
            item.setData(Qt.ItemDataRole.UserRole, sort_value)
        else:
            item.setData(Qt.ItemDataRole.UserRole, float("-inf"))
    table.setItem(row, col, item)


class AnalysisViewWidget(QWidget):
    """Read-only tables for breed summaries, sample details, and breed comparison."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        intro = QLabel(
            "Tracking, motion-index, and optical-flow metrics aggregated by Breed and Sample. "
            "Results are read from saved sample data; opening this view does not "
            "re-run tracking."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #666; margin-bottom: 6px;")
        layout.addWidget(intro)

        self.lbl_empty = QLabel("")
        self.lbl_empty.setWordWrap(True)
        self.lbl_empty.setStyleSheet("color: #888; font-style: italic;")
        self.lbl_empty.hide()
        layout.addWidget(self.lbl_empty)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        body_layout = QVBoxLayout(body)

        self.tbl_breed_summary = self._make_table(
            [
                "Breed",
                "Samples",
                "Samples with Results",
                "Avg Absolute Velocity",
                "Avg Downward Velocity",
                "Avg Motion Index",
                "Std Dev Absolute Velocity",
                "Std Dev Downward Velocity",
                "OF General Movement (µm/s)",
                "OF Downward Motion (µm/s)",
                "OF Net Y Velocity (µm/s)",
                "OF Directionality Ratio",
                "OF Valid Pixel Fraction",
            ]
        )
        body_layout.addWidget(self._wrap_group("Breed Summary", self.tbl_breed_summary))

        self.tbl_sample_details = self._make_table(
            [
                "Breed",
                "Sample",
                "Status",
                "Data Status",
                "Absolute Velocity",
                "Downward Velocity",
                "Motion Index",
                "Valid Tracks",
                "Valid Steps",
                "Confidence",
                "Result Updated At",
                "OF General Movement (µm/s)",
                "OF Downward Motion (µm/s)",
                "OF Net Y Velocity (µm/s)",
                "OF Directionality Ratio",
                "OF Valid Pixel Fraction",
            ]
        )
        body_layout.addWidget(self._wrap_group("Sample Details", self.tbl_sample_details))

        self.tbl_comparison = self._make_table(
            [
                "Rank",
                "Breed",
                "Avg Absolute Velocity",
                "Avg Downward Velocity",
                "Avg Motion Index",
                "Valid Sample Count",
            ]
        )
        body_layout.addWidget(self._wrap_group("Breed Comparison", self.tbl_comparison))
        body_layout.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, stretch=1)

    @staticmethod
    def _wrap_group(title: str, table: QTableWidget) -> QGroupBox:
        box = QGroupBox(title)
        box_layout = QVBoxLayout(box)
        box_layout.addWidget(table)
        return box

    @staticmethod
    def _make_table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        return table

    def refresh(self, report: AnalysisReport) -> None:
        if report.empty_message:
            self.lbl_empty.setText(report.empty_message)
            self.lbl_empty.show()
        else:
            self.lbl_empty.hide()

        self._fill_breed_summary(report.breed_summaries)
        self._fill_sample_details(report.sample_details)
        self._fill_comparison(report.breed_comparisons)

    def _fill_breed_summary(self, rows: list[BreedSummaryRow]) -> None:
        table = self.tbl_breed_summary
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values: list[tuple[str, Any, bool]] = [
                (row.breed, row.breed, False),
                (str(row.sample_count), row.sample_count, True),
                (str(row.samples_with_results), row.samples_with_results, True),
                (_fmt_float(row.avg_general_movement), row.avg_general_movement, True),
                (_fmt_float(row.avg_downward_velocity), row.avg_downward_velocity, True),
                (_fmt_float(row.avg_motion_index), row.avg_motion_index, True),
                (_fmt_float(row.std_general_movement), row.std_general_movement, True),
                (_fmt_float(row.std_downward_velocity), row.std_downward_velocity, True),
                (_fmt_float(row.avg_of_general_movement), row.avg_of_general_movement, True),
                (_fmt_float(row.avg_of_downward_motion), row.avg_of_downward_motion, True),
                (_fmt_float(row.avg_of_net_y_velocity), row.avg_of_net_y_velocity, True),
                (_fmt_float(row.avg_of_directionality_ratio), row.avg_of_directionality_ratio, True),
                (_fmt_float(row.avg_of_valid_pixel_fraction), row.avg_of_valid_pixel_fraction, True),
            ]
            for c, (text, sort_value, numeric) in enumerate(values):
                _set_table_cell(table, r, c, text, sort_value=sort_value, numeric=numeric)
        table.setSortingEnabled(True)

    def _fill_sample_details(self, rows: list[SampleAnalysisRow]) -> None:
        table = self.tbl_sample_details
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            m = row.metrics
            tracks = f"{m.valid_tracks}" if m.valid_tracks is not None else "—"
            values: list[tuple[str, Any, bool]] = [
                (row.breed, row.breed, False),
                (row.sample_label, row.sample_label, False),
                (row.status, row.status, False),
                (row.data_status, row.data_status, False),
                (_fmt_float(m.general_movement), m.general_movement, True),
                (_fmt_float(m.downward_velocity), m.downward_velocity, True),
                (_fmt_float(m.motion_index), m.motion_index, True),
                (tracks, m.valid_tracks, True),
                (_fmt_int(m.valid_steps), m.valid_steps, True),
                (_fmt_float(m.confidence, places=2), m.confidence, True),
                (m.result_updated_at or "—", m.result_updated_at or "", False),
                (_fmt_float(m.of_general_movement), m.of_general_movement, True),
                (_fmt_float(m.of_downward_motion), m.of_downward_motion, True),
                (_fmt_float(m.of_net_y_velocity), m.of_net_y_velocity, True),
                (_fmt_float(m.of_directionality_ratio), m.of_directionality_ratio, True),
                (_fmt_float(m.of_valid_pixel_fraction), m.of_valid_pixel_fraction, True),
            ]
            for c, (text, sort_value, numeric) in enumerate(values):
                _set_table_cell(table, r, c, text, sort_value=sort_value, numeric=numeric)
        table.setSortingEnabled(True)

    def _fill_comparison(self, rows: list[BreedComparisonRow]) -> None:
        table = self.tbl_comparison
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values: list[tuple[str, Any, bool]] = [
                (str(row.rank), row.rank, True),
                (row.breed, row.breed, False),
                (_fmt_float(row.avg_general_movement), row.avg_general_movement, True),
                (_fmt_float(row.avg_downward_velocity), row.avg_downward_velocity, True),
                (_fmt_float(row.avg_motion_index), row.avg_motion_index, True),
                (str(row.valid_sample_count), row.valid_sample_count, True),
            ]
            for c, (text, sort_value, numeric) in enumerate(values):
                _set_table_cell(table, r, c, text, sort_value=sort_value, numeric=numeric)
        table.setSortingEnabled(True)
