"""Laying out an invoice as an HTML document and writing it to PDF.

Fonts and stylesheet are embedded in the document rather than linked, so the
result does not depend on which fonts happen to be installed and both
renderers produce the same page.
"""

from __future__ import annotations

import base64
from datetime import date
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from invoicing.domain.invoice import Invoice
from invoicing.domain.money import format_euro, format_quantity
from invoicing.pdf.renderers import AUTOMATIC, select_renderer

DOCUMENTS = Path(__file__).parent / "documents"
FONTS = Path(__file__).parent / "fonts"

FONT_FILES = (
    ("OpenSans-Regular.ttf", 400, "normal"),
    ("OpenSans-Italic.ttf", 400, "italic"),
    ("OpenSans-Bold.ttf", 700, "normal"),
)


def to_html(invoice: Invoice) -> str:
    """Render the invoice as a self-contained HTML document."""
    template = _jinja_environment().get_template("invoice.html.j2")
    return template.render(
        invoice=invoice,
        font_faces=_font_face_rules(),
        stylesheet=(DOCUMENTS / "invoice.css").read_text(encoding="utf-8"),
    )


def write_pdf(invoice: Invoice, destination: Path, renderer: str = AUTOMATIC) -> Path:
    """Write the invoice to ``destination`` and return that path."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    select_renderer(renderer).write(to_html(invoice), destination)
    return destination


def _german_date(day: date) -> str:
    return f"{day:%d.%m.%Y}"


@lru_cache(maxsize=1)
def _font_face_rules() -> str:
    rules = []
    for file_name, weight, style in FONT_FILES:
        encoded = base64.b64encode((FONTS / file_name).read_bytes()).decode("ascii")
        rules.append(
            "@font-face{font-family:'Open Sans';"
            f"font-weight:{weight};font-style:{style};"
            f"src:url(data:font/ttf;base64,{encoded}) format('truetype');}}"
        )
    return "".join(rules)


@lru_cache(maxsize=1)
def _jinja_environment() -> Environment:
    environment = Environment(
        loader=FileSystemLoader(DOCUMENTS),
        autoescape=select_autoescape(default_for_string=True, default=True),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters["euro"] = format_euro
    environment.filters["quantity"] = format_quantity
    environment.filters["german_date"] = _german_date
    return environment
