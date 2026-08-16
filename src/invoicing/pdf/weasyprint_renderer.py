"""Turning HTML into PDF with WeasyPrint, which needs no browser.

WeasyPrint is an optional dependency: on Windows it needs the GTK runtime,
so its import waits until a document is actually written.
"""

from __future__ import annotations

from pathlib import Path


class WeasyPrintRenderer:
    """Preferred on Linux and macOS: no browser process involved."""

    def write(self, html: str, destination: Path) -> None:
        from weasyprint import HTML

        HTML(string=html).write_pdf(str(destination))
