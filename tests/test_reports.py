from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

from sqlmodel import Session

from invoicing.legacy.history_importer import HistoryImporter
from invoicing.reports import RevenueReport
from invoicing.storage.invoice_database import InvoiceDatabase


def _stored(tmp_path: Path, document: str) -> Session:
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "collected.md").write_text(document, encoding="utf-8")
    database = InvoiceDatabase(tmp_path / "invoicing.db")
    engine = database.open()
    with database.session() as session:
        HistoryImporter(session).import_from(archive)
    return Session(engine)


def test_sums_each_customer_within_each_year(
    tmp_path: Path, collected_document: str
) -> None:
    with _stored(tmp_path, collected_document) as session:
        rows = RevenueReport(session).rows()

    assert [(row.year, row.customer, row.total) for row in rows] == [
        (2025, "Anna Beispiel", Decimal("75.00")),
        (2025, "Bernd Beispiel", Decimal("86.68")),
    ]
    assert [row.invoice_count for row in rows] == [1, 1]


def test_uses_the_printed_total_even_when_the_rows_disagree(
    tmp_path: Path, self_contradicting_document: str
) -> None:
    with _stored(tmp_path, self_contradicting_document) as session:
        (row,) = RevenueReport(session).rows()

    assert row.total == Decimal("53.33")


def test_adds_the_years_up(tmp_path: Path, collected_document: str) -> None:
    with _stored(tmp_path, collected_document) as session:
        rows = RevenueReport(session).rows()

    assert RevenueReport.yearly_totals(rows) == {2025: Decimal("161.68")}


def test_an_empty_database_reports_nothing(tmp_path: Path) -> None:
    with Session(InvoiceDatabase(tmp_path / "invoicing.db").open()) as session:
        assert RevenueReport(session).rows() == ()


def test_writes_a_semicolon_separated_file_for_german_excel(
    tmp_path: Path, collected_document: str
) -> None:
    with _stored(tmp_path, collected_document) as session:
        rows = RevenueReport(session).rows()
    destination = RevenueReport.write_csv(rows, tmp_path / "reports" / "revenue.csv")

    with destination.open(encoding="utf-8-sig", newline="") as handle:
        written = list(csv.reader(handle, delimiter=";"))

    assert written[0] == ["Jahr", "Kunde", "Rechnungen", "Summe"]
    assert written[1] == ["2025", "Anna Beispiel", "1", "75,00\xa0€"]
