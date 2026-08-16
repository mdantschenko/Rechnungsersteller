"""A stored PDF as sharp page images.

The browsers' embedded PDF viewers each lay the page out their own way —
letterboxed, shifted, zoomed. An image is the same everywhere, fills its
container exactly and lets the app own the zoom gesture.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pypdfium2 as pdfium

from invoicing.constant import PDF_PREVIEW_RENDER_SCALE


class PdfPreview:
    """Renders the pages of one stored PDF file as PNG images."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def page_count(self) -> int:
        with self._document() as document:
            return len(document)

    def page_png(self, index: int) -> bytes | None:
        """Page ``index`` rendered as PNG, or None when the page does not exist."""
        with self._document() as document:
            if index < 0 or index >= len(document):
                return None
            image = document[index].render(scale=PDF_PREVIEW_RENDER_SCALE).to_pil()
            buffer = io.BytesIO()
            image.save(buffer, "PNG")
            return buffer.getvalue()

    @contextmanager
    def _document(self) -> Iterator[pdfium.PdfDocument]:
        document = pdfium.PdfDocument(str(self._path))
        try:
            yield document
        finally:
            document.close()
