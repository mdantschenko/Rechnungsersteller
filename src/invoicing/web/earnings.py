"""What actually came in, month by month.

Three pots of money. An invoice counts as income only once "Geld erhalten"
was pressed; until then its amount is merely expected and says so. Beside
both stands what the reminder-only pupils — the ones deliberately billed on
paper nowhere — brought in, computed from their ticked-off lessons times
their price.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlmodel import Session, col, select

from invoicing.billing import priced_line
from invoicing.constant import ZERO
from invoicing.data_classes import EarningsRow
from invoicing.storage.models import (
    Customer,
    InvoiceDelivery,
    IssuedInvoice,
    Lesson,
    LessonStatus,
)
from invoicing.utils import billing_templates_by_customer, sum_of_cents
from invoicing.web.page import month_name


def monthly_earnings(
    session: Session, customer: Customer | None = None
) -> tuple[list[EarningsRow], EarningsRow]:
    """The per-month rows, newest first, and the overall total.

    With a ``customer``, only their money; without, everyone's.
    """
    received, outstanding = _invoices_by_month(session, customer)
    uninvoiced = _uninvoiced_by_month(session, customer)
    keys = sorted(set(received) | set(outstanding) | set(uninvoiced), reverse=True)
    rows = [
        EarningsRow(
            label=f"{month_name(date(year, month, 1))} {year}",
            received=received.get((year, month), ZERO),
            outstanding=outstanding.get((year, month), ZERO),
            uninvoiced=uninvoiced.get((year, month), ZERO),
        )
        for year, month in keys
    ]
    total = EarningsRow(
        label="Gesamt",
        received=sum_of_cents(row.received for row in rows),
        outstanding=sum_of_cents(row.outstanding for row in rows),
        uninvoiced=sum_of_cents(row.uninvoiced for row in rows),
    )
    return rows, total


def _invoices_by_month(
    session: Session, customer: Customer | None
) -> tuple[dict[tuple[int, int], Decimal], dict[tuple[int, int], Decimal]]:
    """Paid invoices land in the first pot, unpaid ones wait in the second."""
    statement = select(IssuedInvoice)
    if customer is not None:
        statement = statement.where(IssuedInvoice.customer_id == customer.id)
    received: dict[tuple[int, int], Decimal] = {}
    outstanding: dict[tuple[int, int], Decimal] = {}
    for record in session.exec(statement).all():
        key = (record.issued_on.year, record.issued_on.month)
        pot = received if record.paid_on is not None else outstanding
        pot[key] = pot.get(key, ZERO) + record.printed_total
    return received, outstanding


def _uninvoiced_by_month(
    session: Session, customer: Customer | None
) -> dict[tuple[int, int], Decimal]:
    """The ticked-off lessons of reminder-only customers, priced."""
    if customer is not None:
        if customer.delivery is not InvoiceDelivery.NONE:
            return {}
        quiet = [customer]
    else:
        quiet = list(
            session.exec(
                select(Customer).where(Customer.delivery == InvoiceDelivery.NONE)
            ).all()
        )
    if not quiet:
        return {}
    quiet_ids = [entry.id or 0 for entry in quiet]
    templates = billing_templates_by_customer(session, quiet_ids)
    found: dict[tuple[int, int], Decimal] = {}
    for lesson in session.exec(
        select(Lesson)
        .where(col(Lesson.customer_id).in_(quiet_ids))
        .where(Lesson.status == LessonStatus.DONE)
    ).all():
        terms = templates.get(lesson.customer_id)
        if terms is None:
            continue
        key = (lesson.taught_on.year, lesson.taught_on.month)
        found[key] = found.get(key, ZERO) + priced_line(terms, lesson).total
    return found
