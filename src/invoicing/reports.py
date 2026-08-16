"""Reading the stored invoices back as a summary, for the command line.

The web app's monthly view lives in :mod:`invoicing.web.earnings`; this file
answers the year-and-customer question the tax return asks.

Totals are added up in Python rather than by the database. Amounts are stored
as text so that no value ever passes through a float, which also means SQL
cannot sum them.

An invoice counts towards the year it was issued in. That is the date on the
document, mistakes included; the import report is where such mistakes surface.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from sqlmodel import Session, select

from invoicing.constant import REVENUE_CSV_HEADER, ZERO
from invoicing.data_classes import RevenueRow
from invoicing.german_formatter import german_formatter
from invoicing.storage.models import Customer, IssuedInvoice


class RevenueReport:
    """Summarises the stored invoices per year and customer."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def rows(self) -> tuple[RevenueRow, ...]:
        """Every year and customer that has invoices, oldest and A to Z first."""
        counts: dict[tuple[int, str], int] = {}
        totals: dict[tuple[int, str], Decimal] = {}
        for invoice, customer in self._session.exec(
            select(IssuedInvoice, Customer).where(
                IssuedInvoice.customer_id == Customer.id
            )
        ):
            key = (invoice.issued_on.year, customer.name)
            counts[key] = counts.get(key, 0) + 1
            totals[key] = totals.get(key, ZERO) + invoice.printed_total
        return tuple(
            RevenueRow(
                year=year,
                customer=name,
                invoice_count=counts[year, name],
                total=totals[year, name],
            )
            for year, name in sorted(counts)
        )

    @staticmethod
    def yearly_totals(rows: Sequence[RevenueRow]) -> dict[int, Decimal]:
        """The sum per year across all customers."""
        totals: dict[int, Decimal] = {}
        for row in rows:
            totals[row.year] = totals.get(row.year, ZERO) + row.total
        return totals

    @staticmethod
    def write_csv(rows: Sequence[RevenueRow], destination: Path) -> Path:
        """Write the summary as a semicolon separated file, as German Excel expects."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(REVENUE_CSV_HEADER)
            for row in rows:
                writer.writerow(
                    [
                        row.year,
                        row.customer,
                        row.invoice_count,
                        german_formatter.format_euro(row.total),
                    ]
                )
        return destination
