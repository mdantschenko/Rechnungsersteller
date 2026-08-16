from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from invoicing.data_classes import Address
from invoicing.legacy.markdown_invoices import read_archive, read_document


def _folder_holding(directory: Path, name: str, text: str) -> Path:
    (directory / name).write_text(text, encoding="utf-8")
    return directory


def test_reads_every_invoice_in_one_document(archive: Path) -> None:
    invoices = list(read_document(archive / "collected.md"))

    assert [invoice.number for invoice in invoices] == [12, 13]


def test_reads_the_recipient_from_above_the_invoice_number(archive: Path) -> None:
    first, second = read_archive(archive).invoices

    assert first.recipient == Address(
        name="Anna Beispiel", street="Beispielweg 3", city="54321 Beispiel"
    )
    assert second.recipient.name == "Bernd Beispiel"


def test_reads_dates_and_period(archive: Path) -> None:
    first, _ = read_archive(archive).invoices

    assert first.issued_on == date(2025, 6, 2)
    assert first.printed_from == date(2025, 5, 1)
    assert first.printed_to == date(2025, 5, 31)


def test_reads_rows_whatever_shape_the_export_gave_them(archive: Path) -> None:
    first, _ = read_archive(archive).invoices

    assert [line.taught_on for line in first.lines] == [
        date(2025, 5, 5),
        date(2025, 5, 12),
    ]
    assert [line.quantity for line in first.lines] == [Decimal("1"), Decimal("2")]
    assert [line.total for line in first.lines] == [Decimal("25.00"), Decimal("50.00")]
    assert first.printed_total == Decimal("75.00")


def test_reads_the_label_of_the_extra_column(archive: Path) -> None:
    first, second = read_archive(archive).invoices

    assert first.extra_column_label == "Anfahrtskosten"
    assert second.extra_column_label == "Übungsaufgaben"


def test_keeps_the_placeholder_and_leaves_its_amount_empty(archive: Path) -> None:
    _, second = read_archive(archive).invoices
    with_amount, with_placeholder = second.lines

    assert with_amount.extra_printed == "20,00 €"
    assert with_amount.extra_amount == Decimal("20.00")
    assert with_placeholder.extra_printed == "/"
    assert with_placeholder.extra_amount is None


def test_reads_an_invoice_that_was_already_settled(archive: Path) -> None:
    _, second = read_archive(archive).invoices

    assert second.paid_on == date(2025, 7, 20)


def test_an_unsettled_invoice_has_no_payment_date(archive: Path) -> None:
    first, _ = read_archive(archive).invoices

    assert first.paid_on is None


def test_reports_a_document_that_contradicts_its_own_rows(
    tmp_path: Path, self_contradicting_document: str
) -> None:
    folder = _folder_holding(tmp_path, "wrong.md", self_contradicting_document)

    (invoice,) = read_archive(folder).invoices

    assert invoice.printed_total == Decimal("53.33")
    assert invoice.computed_total == Decimal("53.34")


def test_finds_lessons_outside_the_stated_period(
    tmp_path: Path, self_contradicting_document: str
) -> None:
    folder = _folder_holding(tmp_path, "wrong.md", self_contradicting_document)

    (invoice,) = read_archive(folder).invoices
    outside = invoice.lessons_outside_the_printed_period()

    assert [line.taught_on for line in outside] == [date(2024, 4, 7)]


def test_both_ends_of_the_stated_period_count_as_inside(archive: Path) -> None:
    _, second = read_archive(archive).invoices

    assert second.lessons_outside_the_printed_period() == ()


def test_the_same_invoice_in_two_files_is_kept_once(
    tmp_path: Path, collected_document: str
) -> None:
    _folder_holding(tmp_path, "collected.md", collected_document)
    _folder_holding(tmp_path, "single.md", collected_document)

    reading = read_archive(tmp_path)

    assert [invoice.number for invoice in reading.invoices] == [12, 13]
    assert reading.conflicts == ()


def test_the_same_number_read_differently_is_reported(
    tmp_path: Path, collected_document: str
) -> None:
    _folder_holding(tmp_path, "a_collected.md", collected_document)
    _folder_holding(
        tmp_path, "b_changed.md", collected_document.replace("75,00 €", "95,00 €")
    )

    reading = read_archive(tmp_path)

    assert [conflict.number for conflict in reading.conflicts] == [12]


def test_a_document_without_a_total_is_refused(
    tmp_path: Path, collected_document: str
) -> None:
    folder = _folder_holding(
        tmp_path, "broken.md", collected_document.replace("Gesamtbetrag", "Summe")
    )

    with pytest.raises(ValueError, match="unreadable invoice"):
        read_archive(folder)


def test_a_missing_address_line_is_refused(
    tmp_path: Path, collected_document: str
) -> None:
    folder = _folder_holding(
        tmp_path,
        "broken.md",
        collected_document.replace("|     Beispielweg 3    |     |     |\n", ""),
    )

    with pytest.raises(ValueError, match="address lines"):
        read_archive(folder)


def test_invoices_come_back_in_number_order(
    tmp_path: Path, collected_document: str
) -> None:
    folder = _folder_holding(
        tmp_path, "reversed.md", _swap_invoice_order(collected_document)
    )

    reading = read_archive(folder)

    assert [invoice.number for invoice in reading.invoices] == [12, 13]


def _swap_invoice_order(document: str) -> str:
    return (
        document.replace("Rechnung Nr. 12", "Rechnung Nr. 99")
        .replace("Rechnung Nr. 13", "Rechnung Nr. 12")
        .replace("Rechnung Nr. 99", "Rechnung Nr. 13")
    )
