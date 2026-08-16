"""Layout checks against reference invoice no. 114.

The expected coordinates were measured on that original PDF with pdfplumber
and are given in millimetres from the top left of the page. They exist so that
a change to the stylesheet cannot silently move the layout away from the
document customers have been receiving for years.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pdfplumber
import pytest
from pdfplumber.page import Page

from invoicing.data_classes import Address
from invoicing.pdf.invoice_document import to_html, write_pdf
from invoicing.sample import SampleInvoice

MILLIMETRE = 72 / 25.4
TOLERANCE_MM = 0.5

EXPECTED_BASELINES_MM = {
    "Musterstraße 19 B - 12345": 38.8,
    "Erika Beispiel": 51.7,
    "Datum: 18.06.2026": 80.5,
    "Rechnung Nr. 114": 86.3,
    "Berechnung für den Zeitraum": 96.9,
    "Bezeichnung / Datum": 108.6,
    "20.05.2026": 116.7,
    "05.06.2026": 124.4,
    "Gesamtbetrag": 132.1,
    "Gemäß § 19": 145.3,
    "Zahlungsbedingungen": 156.9,
    "Bitte überweisen": 166.5,
    "angegebene Konto": 171.3,
    "Ich danke": 180.9,
    "Mit freundlichen Grüßen": 195.3,
    "Musterbank": 263.8,
    "IBAN": 267.7,
    "BIC": 271.5,
    "PayPal:": 275.4,
}

EXPECTED_SHADED_BLOCKS_MM = [(30.8, 69.2), (252.5, 279.3)]
EXPECTED_TABLE_RULES_MM = [110.9, 118.7, 126.4]
EXPECTED_COLUMN_EDGES_MM = [25.0, 41.1, 59.8, 113.0, 136.0, 165.0, 191.6]

TABLE_TOP_MM = 100.0
TABLE_BOTTOM_MM = 140.0


@pytest.fixture(scope="module")
def rendered_page(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Page]:
    destination = tmp_path_factory.mktemp("pdf") / "invoice.pdf"
    write_pdf(SampleInvoice.build(), destination)
    with pdfplumber.open(destination) as document:
        assert len(document.pages) == 1
        yield document.pages[0]


def test_page_is_a4(rendered_page: Page) -> None:
    assert rendered_page.width / MILLIMETRE == pytest.approx(210, abs=TOLERANCE_MM)
    assert rendered_page.height / MILLIMETRE == pytest.approx(297, abs=TOLERANCE_MM)


@pytest.mark.parametrize(("needle", "expected"), EXPECTED_BASELINES_MM.items())
def test_every_line_sits_where_the_original_has_it(
    rendered_page: Page, needle: str, expected: float
) -> None:
    assert _baseline_of(rendered_page, needle) == pytest.approx(
        expected, abs=TOLERANCE_MM
    )


def test_the_two_shaded_blocks_keep_their_extent(
    rendered_page: Page,
) -> None:
    blocks = [
        (rect["top"] / MILLIMETRE, rect["bottom"] / MILLIMETRE)
        for rect in rendered_page.rects
        if rect["x1"] - rect["x0"] > 150 * MILLIMETRE
        and rect["bottom"] - rect["top"] > 10 * MILLIMETRE
    ]

    assert len(blocks) == len(EXPECTED_SHADED_BLOCKS_MM)
    for (top, bottom), (expected_top, expected_bottom) in zip(
        sorted(blocks), EXPECTED_SHADED_BLOCKS_MM, strict=True
    ):
        assert top == pytest.approx(expected_top, abs=TOLERANCE_MM)
        assert bottom == pytest.approx(expected_bottom, abs=TOLERANCE_MM)


def test_the_table_keeps_its_three_horizontal_rules(
    rendered_page: Page,
) -> None:
    rules = sorted(
        {
            round((rect["top"] + rect["bottom"]) / 2 / MILLIMETRE, 1)
            for rect in _thin_table_rects(rendered_page)
        }
    )

    assert rules == pytest.approx(EXPECTED_TABLE_RULES_MM, abs=TOLERANCE_MM)


def test_the_columns_keep_their_edges(rendered_page: Page) -> None:
    edges = sorted(
        {
            round(edge / MILLIMETRE, 1)
            for rect in _thin_table_rects(rendered_page)
            for edge in (rect["x0"], rect["x1"])
        }
    )
    merged = _merged_within_tolerance(edges)

    assert merged == pytest.approx(EXPECTED_COLUMN_EDGES_MM, abs=TOLERANCE_MM)


def test_a_settled_invoice_replaces_the_payment_terms() -> None:
    settled = replace(SampleInvoice.build(), paid_on=date(2026, 6, 20))

    html = to_html(settled)

    assert "wurde bereits am 20.06.2026 dankend erhalten" in html
    assert "Zahlungsbedingungen" not in html


def test_recipient_details_cannot_inject_markup() -> None:
    hostile = replace(
        SampleInvoice.build(),
        recipient=Address(name="<script>alert(1)</script>", street="a & b", city="X"),
    )

    html = to_html(hostile)

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "a &amp; b" in html


def test_the_document_carries_its_fonts_and_styles_inside_itself() -> None:
    html = to_html(SampleInvoice.build())

    assert "data:font/ttf;base64," in html
    assert "<link" not in html


def test_writing_creates_missing_directories(tmp_path: Path) -> None:
    destination = tmp_path / "does" / "not" / "exist" / "invoice.pdf"

    written = write_pdf(SampleInvoice.build(), destination)

    assert written.exists()


def _baseline_of(page: Page, needle: str) -> float:
    matches = [baseline for baseline, text in _lines(page) if needle in text]
    assert len(matches) == 1, f"{needle!r} matched {len(matches)} lines, expected one"
    return matches[0]


def _lines(page: Page) -> list[tuple[float, str]]:
    by_baseline: dict[int, list[dict[str, Any]]] = {}
    for character in page.chars:
        tenth_of_a_millimetre = round(character["bottom"] / MILLIMETRE * 10)
        by_baseline.setdefault(tenth_of_a_millimetre, []).append(character)
    return [
        (
            baseline / 10,
            "".join(
                character["text"]
                for character in sorted(by_baseline[baseline], key=lambda c: c["x0"])
            ),
        )
        for baseline in sorted(by_baseline)
    ]


def _thin_table_rects(page: Page) -> list[dict[str, Any]]:
    return [
        rect
        for rect in page.rects
        if rect["bottom"] - rect["top"] < 0.5 * MILLIMETRE
        and TABLE_TOP_MM * MILLIMETRE < rect["top"] < TABLE_BOTTOM_MM * MILLIMETRE
    ]


def _merged_within_tolerance(values: list[float]) -> list[float]:
    merged: list[float] = []
    for value in values:
        if not merged or value - merged[-1] > TOLERANCE_MM:
            merged.append(value)
    return merged
