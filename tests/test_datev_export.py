from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine
from sqlmodel import Session, select

from invoicing.constant import DATEV_BOOKING_COLUMN_HEADER_LINE_BY_FORMAT_VERSION
from invoicing.datev_export import DatevBookingBatchExport
from invoicing.datev_export_error import DatevExportError
from invoicing.storage.models import (
    AppSettings,
    Customer,
    CustomerStatus,
    IssuedInvoice,
)

BOOKING_FIELD_COUNT = 124
HEADER_FIELD_COUNT = 31
FIRST_BOOKING_LINE = 2
VOUCHER_NUMBER_COLUMN = 10


def _add_invoice(
    session: Session,
    customer: Customer,
    number: int,
    issued_on: date,
    total: str,
) -> None:
    session.add(
        IssuedInvoice(
            number=number,
            customer_id=customer.id or 0,
            issued_on=issued_on,
            period_printed_from=issued_on,
            period_printed_to=issued_on,
            printed_total=Decimal(total),
            computed_total=Decimal(total),
        )
    )


def _add_customer(session: Session, name: str) -> Customer:
    customer = Customer(
        name=name,
        street="Beispielstraße 21",
        city="54321 Beispielstadt",
        status=CustomerStatus.ACTIVE,
    )
    session.add(customer)
    session.flush()
    return customer


def _add_settings(session: Session) -> None:
    session.add(
        AppSettings(
            password_hash="egal",
            session_secret="egal",
            datev_advisor_number=12345,
            datev_client_number=678,
        )
    )


def _forget_datev_numbers(engine: Engine) -> None:
    with Session(engine) as session:
        settings = session.exec(select(AppSettings)).one()
        settings.datev_advisor_number = None
        session.add(settings)
        session.commit()


@pytest.fixture
def booked(engine: Engine) -> Engine:
    """Two invoices from 2026, one from 2025 and one from 2024."""
    with Session(engine) as session:
        _add_settings(session)
        customer = _add_customer(session, "Erika Müller-Groß")
        _add_invoice(session, customer, 115, date(2026, 3, 5), "99.99")
        _add_invoice(session, customer, 116, date(2026, 12, 31), "1234.50")
        _add_invoice(session, customer, 114, date(2025, 11, 2), "50.00")
        _add_invoice(session, customer, 113, date(2024, 6, 30), "40.00")
        session.commit()
    return engine


def _fields_of_first_booking(engine: Engine, year: int = 2026) -> list[str]:
    with Session(engine) as session:
        return (
            DatevBookingBatchExport(session)
            .rows_for_year(year)[FIRST_BOOKING_LINE]
            .split(";")
        )


def test_the_header_names_the_format_version_and_the_lexware_client(
    booked: Engine,
) -> None:
    with Session(booked) as session:
        header = DatevBookingBatchExport(session).rows_for_year(2026)[0]

    assert header.startswith('"EXTF";700;21;"Buchungsstapel";12;')
    assert ';12345;678;20260101;4;20260305;20261231;"Rechnungsausgang 2026"' in header


def test_the_column_line_belongs_to_the_declared_format_version(
    booked: Engine,
) -> None:
    with Session(booked) as session:
        rows = DatevBookingBatchExport(session).rows_for_year(2026)

    assert rows[1].split(";")[-1] == "EU-Steuersatz (Ursprung)"
    assert (
        rows[1] == DATEV_BOOKING_COLUMN_HEADER_LINE_BY_FORMAT_VERSION[12]
    ), "Formatversion 12 verlangt genau diese Spalten"


def test_every_line_carries_exactly_the_prescribed_field_count(
    booked: Engine,
) -> None:
    with Session(booked) as session:
        rows = DatevBookingBatchExport(session).rows_for_year(2026)

    assert rows[0].count(";") == HEADER_FIELD_COUNT - 1
    for line in rows[1:]:
        assert line.count(";") == BOOKING_FIELD_COUNT - 1


def test_the_stamp_carries_the_real_milliseconds(booked: Engine) -> None:
    with Session(booked) as session:
        header = DatevBookingBatchExport(
            session, datetime(2026, 3, 5, 14, 30, 15, 123456)
        ).rows_for_year(2026)[0]

    assert header.split(";")[5] == "20260305143015123"


def test_the_receivable_is_booked_against_the_small_business_revenue(
    booked: Engine,
) -> None:
    fields = _fields_of_first_booking(booked)

    assert fields[1] == '"S"'
    assert fields[6] == "1410"
    assert fields[7] == "8192"
    assert fields[8] == '""'


def test_the_revenue_account_follows_the_voucher_year(booked: Engine) -> None:
    assert _fields_of_first_booking(booked, 2024)[7] == "8195"
    assert _fields_of_first_booking(booked, 2025)[7] == "8192"


def test_the_booking_names_the_amount_the_day_and_the_invoice(
    booked: Engine,
) -> None:
    fields = _fields_of_first_booking(booked)

    assert fields[0] == "99,99"
    assert fields[9] == "0503"
    assert fields[VOUCHER_NUMBER_COLUMN] == '"115"'
    assert fields[13] == '"Rechnung 115 Erika Müller-Groß"'


def test_the_year_ends_on_the_last_day_of_december(booked: Engine) -> None:
    with Session(booked) as session:
        _add_invoice(
            session,
            _add_customer(session, "Silvester Beispiel"),
            117,
            date(2027, 1, 1),
            "10.00",
        )
        session.commit()
        rows = DatevBookingBatchExport(session).rows_for_year(2026)

    booked_numbers = [
        line.split(";")[VOUCHER_NUMBER_COLUMN] for line in rows[FIRST_BOOKING_LINE:]
    ]
    assert booked_numbers == ['"115"', '"116"']


def test_a_semicolon_in_the_name_does_not_open_a_new_field(engine: Engine) -> None:
    with Session(engine) as session:
        _add_settings(session)
        customer = _add_customer(session, "Meier; Sohn GbR")
        _add_invoice(session, customer, 200, date(2026, 4, 1), "20.00")
        session.commit()
        line = DatevBookingBatchExport(session).rows_for_year(2026)[FIRST_BOOKING_LINE]

    assert line.count(";") == BOOKING_FIELD_COUNT - 1
    assert line.split(";")[13] == '"Rechnung 200 Meier  Sohn GbR"'


def test_a_name_outside_cp1252_still_yields_a_readable_file(engine: Engine) -> None:
    with Session(engine) as session:
        _add_settings(session)
        customer = _add_customer(session, "Erika Müller ✓ Ω")
        _add_invoice(session, customer, 201, date(2026, 4, 1), "20.00")
        session.commit()
        raw = DatevBookingBatchExport(session).csv_bytes(2026)

    lines = raw.decode("cp1252").rstrip("\r\n").split("\r\n")
    assert "Erika Müller ?" in lines[FIRST_BOOKING_LINE]
    for line in lines[1:]:
        assert line.count(";") == BOOKING_FIELD_COUNT - 1


def test_an_invoice_over_nothing_stops_the_export_by_name(engine: Engine) -> None:
    with Session(engine) as session:
        _add_settings(session)
        customer = _add_customer(session, "Gratis Beispiel")
        _add_invoice(session, customer, 202, date(2026, 4, 1), "0.00")
        session.commit()

        with pytest.raises(DatevExportError) as raised:
            DatevBookingBatchExport(session).rows_for_year(2026)

    assert "Rechnung Nr. 202" in str(raised.value)
    assert "0,00" in str(raised.value)


def test_without_the_lexware_numbers_there_is_no_file(booked: Engine) -> None:
    _forget_datev_numbers(booked)

    with Session(booked) as session, pytest.raises(DatevExportError) as raised:
        DatevBookingBatchExport(session).rows_for_year(2026)

    assert "Berater- und Mandantennummer" in str(raised.value)
    assert "Einstellungen" in str(raised.value)


def test_a_year_without_invoices_says_so_instead_of_writing_a_file(
    booked: Engine,
) -> None:
    with Session(booked) as session, pytest.raises(DatevExportError) as raised:
        DatevBookingBatchExport(session).rows_for_year(2019)

    assert "2019" in str(raised.value)


def test_the_file_is_cp1252_with_crlf_and_keeps_umlauts(booked: Engine) -> None:
    with Session(booked) as session:
        raw = DatevBookingBatchExport(session).csv_bytes(2026)

    text = raw.decode("cp1252")
    assert "Müller-Groß" in text
    assert text.endswith("\r\n")
    assert "\r\r" not in text


def test_the_file_name_marks_the_batch_and_its_year() -> None:
    assert DatevBookingBatchExport.file_name(2026) == "EXTF_Buchungsstapel_2026.csv"
