from __future__ import annotations

from pathlib import Path

import pdfplumber
import pytest

from invoicing.constant import PDF_RENDERER_AUTOMATIC
from invoicing.pdf import (
    ChromiumRenderer,
    InvoiceDocumentWriter,
    PdfRendererSelection,
    WeasyPrintRenderer,
)
from invoicing.sample import SampleInvoice

PDF_MAGIC_BYTES = b"%PDF"


def test_chromium_writes_a_single_page_pdf(tmp_path: Path) -> None:
    destination = tmp_path / "chromium.pdf"

    html = InvoiceDocumentWriter().to_html(SampleInvoice.build())
    ChromiumRenderer().write(html, destination)

    assert destination.read_bytes().startswith(PDF_MAGIC_BYTES)
    with pdfplumber.open(destination) as document:
        assert len(document.pages) == 1


def test_weasyprint_writes_a_single_page_pdf(tmp_path: Path) -> None:
    destination = tmp_path / "weasyprint.pdf"
    html = InvoiceDocumentWriter().to_html(SampleInvoice.build())
    try:
        WeasyPrintRenderer().write(html, destination)
    except OSError as missing_libraries:
        pytest.skip(f"WeasyPrint needs the GTK runtime: {missing_libraries}")

    assert destination.read_bytes().startswith(PDF_MAGIC_BYTES)
    with pdfplumber.open(destination) as document:
        assert len(document.pages) == 1


@pytest.mark.parametrize(
    ("name", "expected"),
    [("weasyprint", WeasyPrintRenderer), ("chromium", ChromiumRenderer)],
)
def test_a_named_renderer_is_honoured(name: str, expected: type) -> None:
    assert isinstance(PdfRendererSelection().select(name), expected)


def test_automatic_falls_back_to_a_usable_renderer() -> None:
    assert isinstance(
        PdfRendererSelection().select(PDF_RENDERER_AUTOMATIC),
        WeasyPrintRenderer | ChromiumRenderer,
    )
