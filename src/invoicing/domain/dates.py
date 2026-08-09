"""Dates the way German letters write them.

Both the web pages and the printed invoice show the same date format; a
single function keeps the two from drifting apart.
"""

from __future__ import annotations

from datetime import date


def german_date(day: date) -> str:
    """Render a date the German way, for example ``17.03.2026``."""
    return f"{day:%d.%m.%Y}"
