"""Two interchangeable ways of turning HTML into a PDF file.

WeasyPrint is the lighter one and needs no browser, but on Windows it depends
on the GTK runtime. Chromium comes with Playwright and needs no system
packages, which makes it the working default on the development machine.

Both produce the same layout because the document carries its fonts and
measurements inside itself.
"""

from __future__ import annotations

import contextlib
import io
from functools import lru_cache
from pathlib import Path
from typing import Protocol

AUTOMATIC = "auto"


class PdfRenderer(Protocol):
    """Writes a self-contained HTML document to a PDF file."""

    def write(self, html: str, destination: Path) -> None: ...


class WeasyPrintRenderer:
    """Preferred on Linux and macOS: no browser process involved."""

    def write(self, html: str, destination: Path) -> None:
        from weasyprint import HTML

        HTML(string=html).write_pdf(str(destination))


class ChromiumRenderer:
    """Prints the page to PDF through Playwright, without system packages."""

    def write(self, html: str, destination: Path) -> None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                page.set_content(html, wait_until="load")
                page.pdf(
                    path=str(destination),
                    prefer_css_page_size=True,
                    print_background=True,
                )
            finally:
                browser.close()


def select_renderer(name: str = AUTOMATIC) -> PdfRenderer:
    """Pick a renderer by name, or the best one available for ``auto``."""
    if name == "weasyprint":
        return WeasyPrintRenderer()
    if name == "chromium":
        return ChromiumRenderer()
    return WeasyPrintRenderer() if _weasyprint_is_usable() else ChromiumRenderer()


@lru_cache(maxsize=1)
def _weasyprint_is_usable() -> bool:
    # WeasyPrint announces a failed import with a bare print(), so its notice
    # lands on stdout rather than on stderr.
    with (
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        try:
            import weasyprint  # noqa: F401
        except (ImportError, OSError):
            return False
    return True
