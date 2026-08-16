from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine
from sqlmodel import Session

from invoicing.datev_export import DatevBookingBatchExport
from invoicing.storage.models import Customer, CustomerStatus, IssuedInvoice

BOOKING_FIELD_COUNT = 125
FIRST_BOOKING_LINE = 2


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


@pytest.fixture
def booked(engine: Engine) -> Engine:
    """Two invoices from 2026 and one from the year before."""
    with Session(engine) as session:
        customer = Customer(
            name="Erika Müller-Groß",
            street="Beispielstraße 21",
            city="54321 Beispielstadt",
            status=CustomerStatus.ACTIVE,
        )
        session.add(customer)
        session.flush()
        _add_invoice(session, customer, 115, date(2026, 3, 5), "99.99")
        _add_invoice(session, customer, 116, date(2026, 12, 31), "1234.50")
        _add_invoice(session, customer, 114, date(2025, 11, 2), "50.00")
        session.commit()
    return engine


def test_the_first_line_is_the_extf_header(booked: Engine) -> None:
    with Session(booked) as session:
        rows = DatevBookingBatchExport(session).rows_for_year(2026)

    assert rows[0].startswith('"EXTF";700;21;"Buchungsstapel";13;')
    assert rows[0].count(";") == 30


def test_every_line_below_the_header_has_all_columns(booked: Engine) -> None:
    with Session(booked) as session:
        rows = DatevBookingBatchExport(session).rows_for_year(2026)

    for line in rows[1:]:
        assert line.count(";") == BOOKING_FIELD_COUNT - 1


def test_one_booking_row_per_invoice_of_that_year(booked: Engine) -> None:
    with Session(booked) as session:
        rows = DatevBookingBatchExport(session).rows_for_year(2026)

    assert len(rows) == FIRST_BOOKING_LINE + 2


def test_the_amount_is_positive_with_a_decimal_comma(booked: Engine) -> None:
    with Session(booked) as session:
        rows = DatevBookingBatchExport(session).rows_for_year(2026)

    assert rows[FIRST_BOOKING_LINE].startswith("99,99;")
    assert rows[FIRST_BOOKING_LINE + 1].startswith("1234,50;")


def test_the_debtor_stands_in_the_debit_column(booked: Engine) -> None:
    with Session(booked) as session:
        fields = (
            DatevBookingBatchExport(session)
            .rows_for_year(2026)[FIRST_BOOKING_LINE]
            .split(";")
        )

    assert fields[1] == '"S"'


def test_the_booking_uses_the_small_business_accounts(booked: Engine) -> None:
    with Session(booked) as session:
        fields = (
            DatevBookingBatchExport(session)
            .rows_for_year(2026)[FIRST_BOOKING_LINE]
            .split(";")
        )

    assert fields[6] == "10001"
    assert fields[7] == "8192"
    assert fields[8] == '""'


def test_the_voucher_date_is_day_and_month_only(booked: Engine) -> None:
    with Session(booked) as session:
        fields = (
            DatevBookingBatchExport(session)
            .rows_for_year(2026)[FIRST_BOOKING_LINE]
            .split(";")
        )

    assert fields[9] == "0503"


def test_the_invoice_number_is_the_open_item_key(booked: Engine) -> None:
    with Session(booked) as session:
        fields = (
            DatevBookingBatchExport(session)
            .rows_for_year(2026)[FIRST_BOOKING_LINE]
            .split(";")
        )

    assert fields[10] == '"115"'


def test_the_customer_stands_in_the_booking_text(booked: Engine) -> None:
    with Session(booked) as session:
        fields = (
            DatevBookingBatchExport(session)
            .rows_for_year(2026)[FIRST_BOOKING_LINE]
            .split(";")
        )

    assert fields[13] == '"Rechnung 115 Erika Müller-Groß"'


def test_the_batch_is_left_open_for_corrections(booked: Engine) -> None:
    with Session(booked) as session:
        fields = (
            DatevBookingBatchExport(session)
            .rows_for_year(2026)[FIRST_BOOKING_LINE]
            .split(";")
        )

    assert fields[113] == "0"


def test_the_file_is_cp1252_with_crlf_and_keeps_umlauts(booked: Engine) -> None:
    with Session(booked) as session:
        raw = DatevBookingBatchExport(session).csv_bytes(2026)

    text = raw.decode("cp1252")
    assert "Müller-Groß" in text
    assert text.endswith("\r\n")
    assert "\r\r" not in text


def test_a_year_without_invoices_still_carries_the_header(booked: Engine) -> None:
    with Session(booked) as session:
        rows = DatevBookingBatchExport(session).rows_for_year(2019)

    assert len(rows) == FIRST_BOOKING_LINE
    assert rows[0].startswith('"EXTF"')


def test_the_file_name_marks_the_batch_and_its_year() -> None:
    assert DatevBookingBatchExport.file_name(2026) == "EXTF_Buchungsstapel_2026.csv"
