"""One year of issued invoices as a DATEV booking batch, for Lexware.

Lexware has no interface of its own: the file goes in through
"Datei > DATEV-Schnittstelle > DATEV-Import". It is an EXTF booking batch,
interface version 700, category 21 — a 31 field header, then the column
names, then one row per invoice. Format version and column count belong
together (12 means 124 columns, 13 means 125), so both are read from the same
table and can never drift apart. Field order, quoting and the date formats
follow the DATEV format description:
https://developer.datev.de/de/file-format/details/datev-format/format-description/booking-batch
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal

from sqlmodel import Session, col, select

from invoicing.constant import (
    DATEV_ACCOUNTING_PURPOSE_INDEPENDENT,
    DATEV_AMOUNT_FORMAT,
    DATEV_BATCH_LABEL_PATTERN,
    DATEV_BOOKING_COLUMN_HEADER_LINE_BY_FORMAT_VERSION,
    DATEV_BOOKING_TEXT_MAX_LENGTH,
    DATEV_BOOKING_TEXT_PATTERN,
    DATEV_BOOKING_TYPE_FINANCIAL_ACCOUNTING,
    DATEV_CHART_OF_ACCOUNTS_SKR03,
    DATEV_COLUMN_ACCOUNT,
    DATEV_COLUMN_AMOUNT,
    DATEV_COLUMN_BASE_CURRENCY,
    DATEV_COLUMN_BOOKING_TEXT,
    DATEV_COLUMN_CONTRA_ACCOUNT,
    DATEV_COLUMN_CURRENCY,
    DATEV_COLUMN_DEBIT_CREDIT_MARK,
    DATEV_COLUMN_LOCKED,
    DATEV_COLUMN_TAX_KEY,
    DATEV_COLUMN_VOUCHER_DATE,
    DATEV_COLUMN_VOUCHER_NUMBER,
    DATEV_CONTROL_CHARACTER_PATTERN,
    DATEV_CREATED_AT_FORMAT,
    DATEV_CURRENCY,
    DATEV_DAY_FORMAT,
    DATEV_DEBIT_MARK,
    DATEV_DECIMAL_SEPARATOR,
    DATEV_EMPTY_FIELD,
    DATEV_EMPTY_TEXT_FIELD,
    DATEV_ENCODING,
    DATEV_EXPORTING_APPLICATION,
    DATEV_FIELD_COUNT_MESSAGE,
    DATEV_FIELD_SEPARATOR,
    DATEV_FILE_MARKER,
    DATEV_FILE_NAME_PATTERN,
    DATEV_FORMAT_CATEGORY_BOOKING_BATCH,
    DATEV_FORMAT_NAME_BOOKING_BATCH,
    DATEV_FORMAT_VERSION,
    DATEV_GENERAL_LEDGER_ACCOUNT_LENGTH,
    DATEV_HEADER_FIELD_COUNT,
    DATEV_INTERFACE_VERSION,
    DATEV_LINE_ENDING,
    DATEV_MILLISECOND_FORMAT,
    DATEV_NO_INVOICES_MESSAGE,
    DATEV_NON_POSITIVE_AMOUNT_MESSAGE,
    DATEV_NOT_LOCKED,
    DATEV_NUMBERS_MISSING_MESSAGE,
    DATEV_ORIGIN_MARK,
    DATEV_RECEIVABLE_ACCOUNT_SKR03,
    DATEV_SMALL_BUSINESS_REVENUE_ACCOUNT_BEFORE_2025,
    DATEV_SMALL_BUSINESS_REVENUE_ACCOUNT_CHANGE_YEAR,
    DATEV_SMALL_BUSINESS_REVENUE_ACCOUNT_SINCE_2025,
    DATEV_TEXT_SEPARATOR_REPLACEMENT,
    DATEV_UNENCODABLE_CHARACTER_HANDLING,
    DATEV_VOUCHER_DAY_FORMAT,
    MICROSECONDS_PER_MILLISECOND,
    ZERO,
)
from invoicing.datev_export_error import DatevExportError
from invoicing.storage.models import AppSettings, IssuedInvoice
from invoicing.utils import round_to_cents


class DatevBookingBatchExport:
    """Writes the invoices of one year as a DATEV booking batch file.

    The year is the year of the invoice date, because the batch is the
    outgoing invoice ledger. The tax office ZIP goes by the payment date
    instead, so the two can hold different invoices for the same year.

    Every invoice becomes one booking: the receivables account against the
    small business revenue account, no tax key, because a small business
    charges no VAT. Every booking stands in the debit column — the
    application cannot issue credit notes, and DATEV takes positive amounts
    only. The voucher date carries only day and month, so a file holds
    exactly one year.

    Raises:
        DatevExportError: when the file would not be importable — no advisor
            or client number, no invoice in that year, or an invoice whose
            amount is not above zero.
    """

    def __init__(self, session: Session, created_at: datetime | None = None) -> None:
        self._session = session
        self._settings = session.exec(select(AppSettings)).first()
        self._created_at = created_at or datetime.now()

    def rows_for_year(self, year: int) -> tuple[str, ...]:
        """Every line of the file: the header, the column names, the bookings."""
        records = self._invoices_of(year)
        field_count = self._booking_field_count()
        return (
            self._with_exact_fields(
                self._header_line(year, records), DATEV_HEADER_FIELD_COUNT
            ),
            self._with_exact_fields(self._column_header_line(), field_count),
            *(
                self._with_exact_fields(self._booking_line(record), field_count)
                for record in records
            ),
        )

    def csv_bytes(self, year: int) -> bytes:
        """The file as DATEV reads it: CP1252, every line closed by CR/LF."""
        text = "".join(
            f"{line}{DATEV_LINE_ENDING}" for line in self.rows_for_year(year)
        )
        return text.encode(DATEV_ENCODING, errors=DATEV_UNENCODABLE_CHARACTER_HANDLING)

    @staticmethod
    def file_name(year: int) -> str:
        """The name the import dialog looks for: it must start with ``EXTF_``."""
        return DATEV_FILE_NAME_PATTERN.format(year=year)

    @staticmethod
    def _column_header_line() -> str:
        return DATEV_BOOKING_COLUMN_HEADER_LINE_BY_FORMAT_VERSION[DATEV_FORMAT_VERSION]

    @classmethod
    def _booking_field_count(cls) -> int:
        return cls._column_header_line().count(DATEV_FIELD_SEPARATOR) + 1

    def _invoices_of(self, year: int) -> Sequence[IssuedInvoice]:
        records = self._session.exec(
            select(IssuedInvoice)
            .where(col(IssuedInvoice.issued_on) >= date(year, 1, 1))
            .where(col(IssuedInvoice.issued_on) <= date(year, 12, 31))
            .order_by(col(IssuedInvoice.number))
        ).all()
        if not records:
            raise DatevExportError(DATEV_NO_INVOICES_MESSAGE.format(year=year))
        return records

    def _header_line(self, year: int, records: Sequence[IssuedInvoice]) -> str:
        advisor_number, client_number = self._advisor_and_client_number()
        first_day_of_year = date(year, 1, 1).strftime(DATEV_DAY_FORMAT)
        first_voucher_day = min(record.issued_on for record in records)
        last_voucher_day = max(record.issued_on for record in records)
        return DATEV_FIELD_SEPARATOR.join(
            (
                self._quoted(DATEV_FILE_MARKER),
                str(DATEV_INTERFACE_VERSION),
                str(DATEV_FORMAT_CATEGORY_BOOKING_BATCH),
                self._quoted(DATEV_FORMAT_NAME_BOOKING_BATCH),
                str(DATEV_FORMAT_VERSION),
                self._created_at_stamp(),
                DATEV_EMPTY_FIELD,
                self._quoted(DATEV_ORIGIN_MARK),
                self._quoted(DATEV_EXPORTING_APPLICATION),
                DATEV_EMPTY_TEXT_FIELD,
                str(advisor_number),
                str(client_number),
                first_day_of_year,
                str(DATEV_GENERAL_LEDGER_ACCOUNT_LENGTH),
                first_voucher_day.strftime(DATEV_DAY_FORMAT),
                last_voucher_day.strftime(DATEV_DAY_FORMAT),
                self._quoted(DATEV_BATCH_LABEL_PATTERN.format(year=year)),
                DATEV_EMPTY_TEXT_FIELD,
                str(DATEV_BOOKING_TYPE_FINANCIAL_ACCOUNTING),
                str(DATEV_ACCOUNTING_PURPOSE_INDEPENDENT),
                str(DATEV_NOT_LOCKED),
                self._quoted(DATEV_CURRENCY),
                DATEV_EMPTY_FIELD,
                DATEV_EMPTY_TEXT_FIELD,
                DATEV_EMPTY_FIELD,
                DATEV_EMPTY_FIELD,
                self._quoted(DATEV_CHART_OF_ACCOUNTS_SKR03),
                DATEV_EMPTY_FIELD,
                DATEV_EMPTY_FIELD,
                DATEV_EMPTY_TEXT_FIELD,
                DATEV_EMPTY_TEXT_FIELD,
            )
        )

    def _booking_line(self, record: IssuedInvoice) -> str:
        fields = [DATEV_EMPTY_FIELD] * self._booking_field_count()
        fields[DATEV_COLUMN_AMOUNT] = self._amount(self._positive_total(record))
        fields[DATEV_COLUMN_DEBIT_CREDIT_MARK] = self._quoted(DATEV_DEBIT_MARK)
        fields[DATEV_COLUMN_CURRENCY] = DATEV_EMPTY_TEXT_FIELD
        fields[DATEV_COLUMN_BASE_CURRENCY] = DATEV_EMPTY_TEXT_FIELD
        fields[DATEV_COLUMN_ACCOUNT] = str(DATEV_RECEIVABLE_ACCOUNT_SKR03)
        fields[DATEV_COLUMN_CONTRA_ACCOUNT] = str(
            self._revenue_account(record.issued_on.year)
        )
        fields[DATEV_COLUMN_TAX_KEY] = DATEV_EMPTY_TEXT_FIELD
        fields[DATEV_COLUMN_VOUCHER_DATE] = record.issued_on.strftime(
            DATEV_VOUCHER_DAY_FORMAT
        )
        fields[DATEV_COLUMN_VOUCHER_NUMBER] = self._quoted(str(record.number))
        fields[DATEV_COLUMN_BOOKING_TEXT] = self._quoted(self._booking_text(record))
        fields[DATEV_COLUMN_LOCKED] = str(DATEV_NOT_LOCKED)
        return DATEV_FIELD_SEPARATOR.join(fields)

    def _advisor_and_client_number(self) -> tuple[int, int]:
        settings = self._settings
        advisor_number = settings.datev_advisor_number if settings else None
        client_number = settings.datev_client_number if settings else None
        if not advisor_number or not client_number:
            raise DatevExportError(DATEV_NUMBERS_MISSING_MESSAGE)
        return advisor_number, client_number

    def _created_at_stamp(self) -> str:
        milliseconds = self._created_at.microsecond // MICROSECONDS_PER_MILLISECOND
        return self._created_at.strftime(
            DATEV_CREATED_AT_FORMAT
        ) + DATEV_MILLISECOND_FORMAT.format(milliseconds)

    @staticmethod
    def _revenue_account(voucher_year: int) -> int:
        """SKR03 carries the small business revenue on 8195 up to the 2024 books
        and on 8192 from the 2025 books on."""
        if voucher_year < DATEV_SMALL_BUSINESS_REVENUE_ACCOUNT_CHANGE_YEAR:
            return DATEV_SMALL_BUSINESS_REVENUE_ACCOUNT_BEFORE_2025
        return DATEV_SMALL_BUSINESS_REVENUE_ACCOUNT_SINCE_2025

    @classmethod
    def _positive_total(cls, record: IssuedInvoice) -> Decimal:
        total = round_to_cents(record.printed_total)
        if total <= ZERO:
            raise DatevExportError(
                DATEV_NON_POSITIVE_AMOUNT_MESSAGE.format(
                    number=record.number, amount=cls._amount(total)
                )
            )
        return total

    @staticmethod
    def _with_exact_fields(line: str, expected: int) -> str:
        counted = line.count(DATEV_FIELD_SEPARATOR) + 1
        if counted != expected:
            raise DatevExportError(
                DATEV_FIELD_COUNT_MESSAGE.format(counted=counted, expected=expected)
            )
        return line

    @staticmethod
    def _amount(total: Decimal) -> str:
        """Always two places, always a decimal comma."""
        plain = format(total, DATEV_AMOUNT_FORMAT)
        return plain.replace(".", DATEV_DECIMAL_SEPARATOR)

    @staticmethod
    def _booking_text(record: IssuedInvoice) -> str:
        text = DATEV_BOOKING_TEXT_PATTERN.format(
            number=record.number, customer=record.customer.name
        )
        plain = DATEV_CONTROL_CHARACTER_PATTERN.sub(" ", text)
        without_separator = plain.replace(
            DATEV_FIELD_SEPARATOR, DATEV_TEXT_SEPARATOR_REPLACEMENT
        )
        return without_separator[:DATEV_BOOKING_TEXT_MAX_LENGTH]

    @staticmethod
    def _quoted(text: str) -> str:
        escaped = text.replace('"', '""')
        return f'"{escaped}"'
