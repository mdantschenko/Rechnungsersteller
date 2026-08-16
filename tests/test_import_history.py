from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlmodel import Session, col, select

from invoicing.legacy.history_importer import HistoryImporter
from invoicing.storage.invoice_database import InvoiceDatabase
from invoicing.storage.models import (
    Customer,
    CustomerStatus,
    IssuedInvoice,
    NumberState,
)


def _imported(tmp_path: Path, document: str, name: str = "collected.md") -> Session:
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / name).write_text(document, encoding="utf-8")
    database = InvoiceDatabase(tmp_path / "invoicing.db")
    engine = database.open()
    with database.session() as session:
        HistoryImporter(session).import_from(archive)
    return Session(engine)


def test_stores_every_invoice_it_reads(tmp_path: Path, collected_document: str) -> None:
    with _imported(tmp_path, collected_document) as session:
        numbers = session.exec(
            select(IssuedInvoice.number).order_by(col(IssuedInvoice.number))
        )

        assert list(numbers) == [12, 13]


def test_creates_each_customer_once_and_archived(
    tmp_path: Path, collected_document: str
) -> None:
    with _imported(tmp_path, collected_document) as session:
        customers = session.exec(select(Customer).order_by(col(Customer.name))).all()

        assert [customer.name for customer in customers] == [
            "Anna Beispiel",
            "Bernd Beispiel",
        ]
        assert {customer.status for customer in customers} == {CustomerStatus.ARCHIVED}


def test_keeps_the_rows_in_the_order_they_were_printed(
    tmp_path: Path, collected_document: str
) -> None:
    with _imported(tmp_path, collected_document) as session:
        invoice = session.exec(
            select(IssuedInvoice).where(IssuedInvoice.number == 13)
        ).one()

        assert [line.taught_on for line in invoice.lines] == [
            date(2025, 6, 16),
            date(2025, 7, 15),
        ]
        assert [line.ordinal for line in invoice.lines] == [0, 1]


def test_keeps_both_the_printed_and_the_recomputed_total(
    tmp_path: Path, self_contradicting_document: str
) -> None:
    with _imported(tmp_path, self_contradicting_document, "wrong.md") as session:
        invoice = session.exec(select(IssuedInvoice)).one()

        assert invoice.printed_total == Decimal("53.33")
        assert invoice.computed_total == Decimal("53.34")
        assert invoice.totals_disagree


def test_stores_the_period_exactly_as_printed(
    tmp_path: Path, collected_document: str
) -> None:
    with _imported(tmp_path, collected_document) as session:
        invoice = session.exec(
            select(IssuedInvoice).where(IssuedInvoice.number == 13)
        ).one()

        assert invoice.period_printed_from == date(2025, 6, 15)
        assert invoice.period_printed_to == date(2025, 7, 15)


def test_running_the_import_twice_changes_nothing(
    tmp_path: Path, collected_document: str
) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "collected.md").write_text(collected_document, encoding="utf-8")
    database = InvoiceDatabase(tmp_path / "invoicing.db")
    engine = database.open()

    with database.session() as session:
        first = HistoryImporter(session).import_from(archive)
    with database.session() as session:
        second = HistoryImporter(session).import_from(archive)

    assert first.imported == 2
    assert second.imported == 0
    assert second.already_known == 2
    with Session(engine) as session:
        assert len(session.exec(select(IssuedInvoice)).all()) == 2


def test_reports_what_does_not_add_up(
    tmp_path: Path, self_contradicting_document: str
) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "wrong.md").write_text(self_contradicting_document, encoding="utf-8")

    with InvoiceDatabase(tmp_path / "invoicing.db").session() as session:
        report = HistoryImporter(session).import_from(archive)

    descriptions = " | ".join(anomaly.description for anomaly in report.anomalies)
    assert "printed total 53.33" in descriptions
    assert "07.04.2024" in descriptions
    assert "before its period ended" in descriptions


def test_a_sound_document_produces_no_anomalies(
    tmp_path: Path, collected_document: str
) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "collected.md").write_text(collected_document, encoding="utf-8")

    with InvoiceDatabase(tmp_path / "invoicing.db").session() as session:
        report = HistoryImporter(session).import_from(archive)

    assert report.anomalies == ()
    assert report.lowest_number == 12
    assert report.highest_number == 13


def test_numbering_continues_past_the_highest_number_found(
    tmp_path: Path, collected_document: str
) -> None:
    with _imported(tmp_path, collected_document) as session:
        state = session.exec(select(NumberState)).one()

        assert state.last_assigned == 13
        assert state.start == 14


def test_the_caller_can_say_where_numbering_continues(
    tmp_path: Path, collected_document: str
) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "collected.md").write_text(collected_document, encoding="utf-8")
    database = InvoiceDatabase(tmp_path / "invoicing.db")
    engine = database.open()

    with database.session() as session:
        HistoryImporter(session).import_from(archive, next_number=115)

    with Session(engine) as session:
        assert session.exec(select(NumberState)).one().start == 115
