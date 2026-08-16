"""Laying out an invoice as an HTML document and writing it to PDF.

Fonts and stylesheet are embedded in the document rather than linked, so the
result does not depend on which fonts happen to be installed and both
renderers produce the same page.
"""

from __future__ import annotations

import base64
from functools import cached_property
from pathlib import Path
from tempfile import TemporaryDirectory

from jinja2 import Environment, FileSystemLoader, select_autoescape

from invoicing.constant import (
    INVOICE_DOCUMENT_FONT_FILES,
    INVOICE_DOCUMENT_FONTS_DIRECTORY,
    INVOICE_DOCUMENT_TEMPLATES_DIRECTORY,
    PDF_RENDERER_AUTOMATIC,
)
from invoicing.data_classes import Invoice
from invoicing.domain.extra_column_rules import ExtraColumnRules
from invoicing.german_formatter import german_formatter
from invoicing.german_template_filters import GermanTemplateFilters
from invoicing.pdf.renderer_selection import PdfRendererSelection


class InvoiceDocumentWriter:
    """Turns invoices into HTML documents, PDF files or PDF bytes."""

    def __init__(self, renderer_name: str = PDF_RENDERER_AUTOMATIC) -> None:
        self._renderer_name = renderer_name

    def to_html(self, invoice: Invoice) -> str:
        """Render the invoice as a self-contained HTML document."""
        template = self._jinja_environment.get_template("invoice.html.j2")
        return template.render(
            invoice=invoice,
            printed_column_values=self._printed_column_values(invoice),
            font_faces=self._font_face_rules,
            stylesheet=(INVOICE_DOCUMENT_TEMPLATES_DIRECTORY / "invoice.css").read_text(
                encoding="utf-8"
            ),
        )

    def write_pdf(self, invoice: Invoice, destination: Path) -> Path:
        """Write the invoice to ``destination`` and return that path."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        renderer = PdfRendererSelection().select(self._renderer_name)
        renderer.write(self.to_html(invoice), destination)
        return destination

    def pdf_bytes(self, invoice: Invoice) -> bytes:
        """The finished PDF in memory, for previews and mail attachments."""
        with TemporaryDirectory() as folder:
            return self.write_pdf(invoice, Path(folder) / "invoice.pdf").read_bytes()

    @staticmethod
    def _printed_column_values(invoice: Invoice) -> tuple[tuple[str, ...], ...]:
        """The extra column cells of every row, formatted so the template stays dumb."""
        rules = tuple(ExtraColumnRules(column) for column in invoice.columns)
        return tuple(
            tuple(
                rule.display(value)
                for rule, value in zip(rules, item.column_values, strict=True)
            )
            for item in invoice.line_items
        )

    @cached_property
    def _font_face_rules(self) -> str:
        rules = []
        for file_name, weight, style in INVOICE_DOCUMENT_FONT_FILES:
            encoded = base64.b64encode(
                (INVOICE_DOCUMENT_FONTS_DIRECTORY / file_name).read_bytes()
            ).decode("ascii")
            rules.append(
                "@font-face{font-family:'Open Sans';"
                f"font-weight:{weight};font-style:{style};"
                f"src:url(data:font/ttf;base64,{encoded}) format('truetype');}}"
            )
        return "".join(rules)

    @cached_property
    def _jinja_environment(self) -> Environment:
        environment = Environment(
            loader=FileSystemLoader(INVOICE_DOCUMENT_TEMPLATES_DIRECTORY),
            autoescape=select_autoescape(default_for_string=True, default=True),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        GermanTemplateFilters(german_formatter).install_into(environment)
        return environment
