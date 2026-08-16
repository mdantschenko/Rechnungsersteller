"""Choosing between the two interchangeable PDF renderers.

WeasyPrint is the lighter one and needs no browser, but on Windows it depends
on the GTK runtime. Chromium comes with Playwright and needs no system
packages, which makes it the working default on the development machine.
"""

from __future__ import annotations

import contextlib
import io
from functools import cache

from invoicing.constant import PDF_RENDERER_AUTOMATIC
from invoicing.pdf.chromium_renderer import ChromiumRenderer
from invoicing.pdf.pdf_renderer import PdfRenderer
from invoicing.pdf.weasyprint_renderer import WeasyPrintRenderer


class PdfRendererSelection:
    """Resolves a renderer name to a ready renderer."""

    def select(self, name: str = PDF_RENDERER_AUTOMATIC) -> PdfRenderer:
        """Pick a renderer by name, or the best one available for ``auto``."""
        if name == "weasyprint":
            return WeasyPrintRenderer()
        if name == "chromium":
            return ChromiumRenderer()
        return WeasyPrintRenderer() if _weasyprint_is_usable() else ChromiumRenderer()


@cache
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
