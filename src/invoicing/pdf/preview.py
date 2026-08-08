"""A stored PDF as sharp page images.

The browsers' embedded PDF viewers each lay the page out their own way —
letterboxed, shifted, zoomed. An image is the same everywhere, fills its
container exactly and lets the app own the zoom gesture.
"""

from __future__ import annotations

import io
from pathlib import Path

import pypdfium2 as pdfium

SCALE = 2


def page_count(path: Path) -> int:
    document = pdfium.PdfDocument(str(path))
    try:
        return len(document)
    finally:
        document.close()


def page_png(path: Path, index: int) -> bytes | None:
    """Page ``index`` rendered as PNG, or None when the page does not exist."""
    document = pdfium.PdfDocument(str(path))
    try:
        if index < 0 or index >= len(document):
            return None
        image = document[index].render(scale=SCALE).to_pil()
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return buffer.getvalue()
    finally:
        document.close()
