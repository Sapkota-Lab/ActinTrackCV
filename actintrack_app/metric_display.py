"""User-facing metric status and last-analyzed display text (GUI polish)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

MetricState = str


def format_local_datetime(dt: datetime) -> str:
    try:
        local = dt.astimezone()
    except ValueError:
        local = dt
    hour = local.hour % 12 or 12
    ampm = "AM" if local.hour < 12 else "PM"
    return f"{local.strftime('%b')} {local.day}, {local.year}, {hour}:{local.minute:02d} {ampm}"


def render_metric_status_text(state: MetricState) -> str:
    """Short metric workflow status (never includes a timestamp)."""
    mapping = {
        "unavailable_no_roi": "Not analyzed",
        "not_analyzed": "Not analyzed",
        "scheduled": "Scheduled",
        "running": "Analyzing",
        "error": "Error",
        "analyzed": "Analyzed",
        "stale": "Needs analysis",
    }
    label = mapping.get(state, "Not analyzed")
    return f"Metric status: {label}"


def render_last_analyzed_text(timestamp: Optional[datetime]) -> str:
    """Last successful analysis timestamp, separate from workflow status."""
    if timestamp is None:
        return "Last analyzed: —"
    return f"Last analyzed: {format_local_datetime(timestamp)}"


def render_metric_display_lines(
    state: MetricState,
    last_analyzed: Optional[datetime],
) -> tuple[str, str]:
    """Return (metric_status_line, last_analyzed_line) for the workbench."""
    return (
        render_metric_status_text(state),
        render_last_analyzed_text(last_analyzed),
    )
