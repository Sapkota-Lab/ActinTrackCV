"""Tests for separated metric status vs last-analyzed display."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from actintrack_app.metric_display import (
    format_local_datetime,
    render_last_analyzed_text,
    render_metric_display_lines,
    render_metric_status_text,
)


class MetricDisplayTests(unittest.TestCase):
    def test_status_never_includes_timestamp(self) -> None:
        ts = datetime(2026, 3, 1, 15, 30, tzinfo=timezone.utc)
        status, last = render_metric_display_lines("scheduled", ts)
        self.assertEqual(status, "Metric status: Scheduled")
        self.assertNotIn("Mar", status)
        self.assertTrue(last.startswith("Last analyzed:"))

    def test_scheduled_shows_prior_timestamp(self) -> None:
        ts = datetime(2026, 3, 1, 15, 30, tzinfo=timezone.utc)
        _, last = render_metric_display_lines("scheduled", ts)
        self.assertIn("2026", last)
        self.assertNotIn("Scheduled", last)

    def test_never_analyzed_last_line_is_dash(self) -> None:
        self.assertEqual(render_last_analyzed_text(None), "Last analyzed: —")
        status, last = render_metric_display_lines("not_analyzed", None)
        self.assertEqual(status, "Metric status: Not analyzed")
        self.assertEqual(last, "Last analyzed: —")

    def test_analyzed_status_and_timestamp_separate(self) -> None:
        ts = datetime(2026, 7, 1, 9, 5, tzinfo=timezone.utc)
        status, last = render_metric_display_lines("analyzed", ts)
        self.assertEqual(status, "Metric status: Analyzed")
        self.assertIn("2026", last)

    def test_stale_needs_analysis_status(self) -> None:
        ts = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(
            render_metric_status_text("stale"),
            "Metric status: Needs analysis",
        )
        self.assertIn("2026", render_last_analyzed_text(ts))

    def test_format_local_datetime_readable(self) -> None:
        ts = datetime(2026, 3, 1, 15, 30, tzinfo=timezone.utc)
        text = format_local_datetime(ts)
        self.assertIn("Mar", text)
        self.assertIn("2026", text)


if __name__ == "__main__":
    unittest.main()
