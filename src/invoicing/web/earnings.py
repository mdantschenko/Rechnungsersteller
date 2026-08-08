"""What came in, month by month.

Two kinds of money: what invoices say, and what the reminder-only pupils —
the ones deliberately billed on paper nowhere — brought in, computed from
their ticked-off lessons times their price. The screen shows both, so the
invoiced figure stays honest on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlmodel import Session, col, select

from invoicing.billing import billable_quantity, stored_columns, typed_values
from invoicing.domain.money import round_to_cents
from invoicing.storage.models import (
    BillingTemplate,
    Customer,
    InvoiceDelivery,
    IssuedInvoice,
    Lesson,
    LessonStatus,
)
from invoicing.web.page import month_name

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class EarningsRow:
    """One month's take, split by whether an invoice exists for it."""

    label: str
    invoiced: Decimal
    uninvoiced: Decimal

    @property
    def total(self) -> Decimal:
        return self.invoiced + self.uninvoiced


def monthly_earnings(
    session: Session, customer: Customer | None = None
) -> tuple[list[EarningsRow], EarningsRow]:
    """The per-month rows, newest first, and the overall total.

    With a ``customer``, only their money; without, everyone's.
    """
    invoiced = _invoiced_by_month(session, customer)
    uninvoiced = _uninvoiced_by_month(session, customer)
    keys = sorted(set(invoiced) | set(uninvoiced), reverse=True)
    rows = [
        EarningsRow(
            label=f"{month_name(date(year, month, 1))} {year}",
            invoiced=invoiced.get((year, month), ZERO),
            uninvoiced=uninvoiced.get((year, month), ZERO),
        )
        for year, month in keys
    ]
    total = EarningsRow(
        label="Gesamt",
        invoiced=sum((row.invoiced for row in rows), ZERO),
        uninvoiced=sum((row.uninvoiced for row in rows), ZERO),
    )
    return rows, total


def _invoiced_by_month(
    session: Session, customer: Customer | None
) -> dict[tuple[int, int], Decimal]:
    statement = select(IssuedInvoice)
    if customer is not None:
        statement = statement.where(IssuedInvoice.customer_id == customer.id)
    found: dict[tuple[int, int], Decimal] = {}
    for record in session.exec(statement).all():
        key = (record.issued_on.year, record.issued_on.month)
        found[key] = found.get(key, ZERO) + record.printed_total
    return found


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
    templates = _templates(session, quiet_ids)
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
        found[key] = found.get(key, ZERO) + _lesson_value(terms, lesson)
    return found


def _lesson_value(terms: BillingTemplate, lesson: Lesson) -> Decimal:
    """One lesson priced the way an invoice row would price it:
    hours times rate — or the flat rate — plus the extra columns."""
    columns = stored_columns(terms)
    kinds = {column.label: column.kind for column in columns}
    values = typed_values(kinds, lesson.column_values)
    quantity = billable_quantity(terms, lesson)
    amount = round_to_cents(quantity * terms.unit_price)
    for column in columns:
        amount += column.contribution(column.value_for(values), quantity)
    return amount


def _templates(session: Session, customer_ids: list[int]) -> dict[int, BillingTemplate]:
    return {
        terms.customer_id: terms
        for terms in session.exec(
            select(BillingTemplate).where(
                col(BillingTemplate.customer_id).in_(customer_ids)
            )
        ).all()
    }
