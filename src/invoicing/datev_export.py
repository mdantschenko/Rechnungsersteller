"""One year of issued invoices as a DATEV booking batch, for Lexware.

Lexware has no interface of its own: the file goes in through
"Datei > DATEV-Schnittstelle > DATEV-Import". It is an EXTF booking batch,
interface version 700, category 21, format version 13 — a 31 field header,
then the 125 column names, then one row of 125 fields per invoice. Field
order, quoting and the date formats follow the DATEV format description:
https://developer.datev.de/de/file-format/details/datev-format/format-description/booking-batch
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal

from sqlmodel import Session, col, select

from invoicing.constant import (
    DATEV_ACCOUNTING_PURPOSE_INDEPENDENT,
    DATEV_ADVISOR_NUMBER,
    DATEV_AMOUNT_FORMAT,
    DATEV_BATCH_LABEL_PATTERN,
    DATEV_BOOKING_COLUMN_HEADER_LINE,
    DATEV_BOOKING_FIELD_COUNT,
    DATEV_BOOKING_TEXT_MAX_LENGTH,
    DATEV_BOOKING_TEXT_PATTERN,
    DATEV_BOOKING_TYPE_FINANCIAL_ACCOUNTING,
    DATEV_CHART_OF_ACCOUNTS_SKR03,
    DATEV_CLIENT_NUMBER,
    DATEV_COLLECTIVE_DEBTOR_ACCOUNT,
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
    DATEV_CREDIT_MARK,
    DATEV_CURRENCY,
    DATEV_DAY_FORMAT,
    DATEV_DEBIT_MARK,
    DATEV_DECIMAL_SEPARATOR,
    DATEV_EMPTY_FIELD,
    DATEV_EMPTY_TEXT_FIELD,
    DATEV_ENCODING,
    DATEV_EXPORTING_APPLICATION,
    DATEV_FIELD_SEPARATOR,
    DATEV_FILE_MARKER,
    DATEV_FILE_NAME_PATTERN,
    DATEV_FORMAT_CATEGORY_BOOKING_BATCH,
    DATEV_FORMAT_NAME_BOOKING_BATCH,
    DATEV_FORMAT_VERSION,
    DATEV_GENERAL_LEDGER_ACCOUNT_LENGTH,
    DATEV_INTERFACE_VERSION,
    DATEV_LINE_ENDING,
    DATEV_NOT_LOCKED,
    DATEV_ORIGIN_MARK,
    DATEV_SMALL_BUSINESS_REVENUE_ACCOUNT_SKR03,
    DATEV_UNENCODABLE_CHARACTER_HANDLING,
    DATEV_VOUCHER_DAY_FORMAT,
    DATEV_VOUCHER_NUMBER_FORBIDDEN_PATTERN,
    DATEV_VOUCHER_NUMBER_MAX_LENGTH,
    DATEV_VOUCHER_NUMBER_REPLACEMENT,
    ZERO,
)
from invoicing.storage.models import IssuedInvoice
from invoicing.utils import round_to_cents


class DatevBookingBatchExport:
    """Writes the invoices of one year as a DATEV booking batch file.

    Every invoice becomes one booking: the collective debtor against the
    small business revenue account, no tax key, because a small business
    charges no VAT. The voucher date carries only day and month, so a file
    holds exactly one year.
    """

    def __init__(self, session: Session, created_at: datetime | None = None) -> None:
        self._session = session
        self._created_at = created_at or datetime.now()

    def rows_for_year(self, year: int) -> tuple[str, ...]:
        """Every line of the file: the header, the column names, the bookings."""
        return (
            self._header_line(year),
            DATEV_BOOKING_COLUMN_HEADER_LINE,
            *(self._booking_line(record) for record in self._invoices_of(year)),
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

    def _invoices_of(self, year: int) -> Sequence[IssuedInvoice]:
        return self._session.exec(
            select(IssuedInvoice)
            .where(col(IssuedInvoice.issued_on) >= date(year, 1, 1))
            .where(col(IssuedInvoice.issued_on) <= date(year, 12, 31))
            .order_by(col(IssuedInvoice.number))
        ).all()

    def _header_line(self, year: int) -> str:
        first_day = date(year, 1, 1).strftime(DATEV_DAY_FORMAT)
        last_day = date(year, 12, 31).strftime(DATEV_DAY_FORMAT)
        return DATEV_FIELD_SEPARATOR.join(
            (
                self._quoted(DATEV_FILE_MARKER),
                str(DATEV_INTERFACE_VERSION),
                str(DATEV_FORMAT_CATEGORY_BOOKING_BATCH),
                self._quoted(DATEV_FORMAT_NAME_BOOKING_BATCH),
                str(DATEV_FORMAT_VERSION),
                self._created_at.strftime(DATEV_CREATED_AT_FORMAT),
                DATEV_EMPTY_FIELD,
                self._quoted(DATEV_ORIGIN_MARK),
                self._quoted(DATEV_EXPORTING_APPLICATION),
                DATEV_EMPTY_TEXT_FIELD,
                str(DATEV_ADVISOR_NUMBER),
                str(DATEV_CLIENT_NUMBER),
                first_day,
                str(DATEV_GENERAL_LEDGER_ACCOUNT_LENGTH),
                first_day,
                last_day,
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
        amount = record.printed_total
        fields = [DATEV_EMPTY_FIELD] * DATEV_BOOKING_FIELD_COUNT
        fields[DATEV_COLUMN_AMOUNT] = self._amount(abs(amount))
        fields[DATEV_COLUMN_DEBIT_CREDIT_MARK] = self._quoted(
            DATEV_CREDIT_MARK if amount < ZERO else DATEV_DEBIT_MARK
        )
        fields[DATEV_COLUMN_CURRENCY] = DATEV_EMPTY_TEXT_FIELD
        fields[DATEV_COLUMN_BASE_CURRENCY] = DATEV_EMPTY_TEXT_FIELD
        fields[DATEV_COLUMN_ACCOUNT] = str(DATEV_COLLECTIVE_DEBTOR_ACCOUNT)
        fields[DATEV_COLUMN_CONTRA_ACCOUNT] = str(
            DATEV_SMALL_BUSINESS_REVENUE_ACCOUNT_SKR03
        )
        fields[DATEV_COLUMN_TAX_KEY] = DATEV_EMPTY_TEXT_FIELD
        fields[DATEV_COLUMN_VOUCHER_DATE] = record.issued_on.strftime(
            DATEV_VOUCHER_DAY_FORMAT
        )
        fields[DATEV_COLUMN_VOUCHER_NUMBER] = self._quoted(
            self._voucher_number(record.number)
        )
        fields[DATEV_COLUMN_BOOKING_TEXT] = self._quoted(self._booking_text(record))
        fields[DATEV_COLUMN_LOCKED] = str(DATEV_NOT_LOCKED)
        return DATEV_FIELD_SEPARATOR.join(fields)

    @staticmethod
    def _amount(total: Decimal) -> str:
        """Always positive, always two places, always a decimal comma."""
        plain = format(round_to_cents(total), DATEV_AMOUNT_FORMAT)
        return plain.replace(".", DATEV_DECIMAL_SEPARATOR)

    @staticmethod
    def _voucher_number(number: int) -> str:
        """The invoice number as the open item matching field accepts it."""
        allowed = DATEV_VOUCHER_NUMBER_FORBIDDEN_PATTERN.sub(
            DATEV_VOUCHER_NUMBER_REPLACEMENT, str(number)
        )
        return allowed[:DATEV_VOUCHER_NUMBER_MAX_LENGTH]

    @staticmethod
    def _booking_text(record: IssuedInvoice) -> str:
        text = DATEV_BOOKING_TEXT_PATTERN.format(
            number=record.number, customer=record.customer.name
        )
        plain = DATEV_CONTROL_CHARACTER_PATTERN.sub(" ", text)
        return plain[:DATEV_BOOKING_TEXT_MAX_LENGTH]

    @staticmethod
    def _quoted(text: str) -> str:
        escaped = text.replace('"', '""')
        return f'"{escaped}"'
