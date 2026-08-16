"""Turning taught lessons into a finished invoice.

Each row is rounded on its own and the rows are then summed, so the printed
total is exactly what a customer gets by adding up the visible rows. Rounding
the exact sum instead would occasionally differ by a cent from that addition.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from invoicing.constant import (
    DEFAULT_BILLING_UNIT,
    DEFAULT_LESSON_DESCRIPTION,
    ZERO,
)
from invoicing.domain.billing_period import BillingPeriod
from invoicing.domain.columns import Column, ColumnValue
from invoicing.domain.money import round_to_cents


@dataclass(frozen=True, slots=True)
class Address:
    """A postal address as it appears in the address field."""

    name: str
    street: str
    city: str


@dataclass(frozen=True, slots=True)
class Issuer:
    """Everything about the sender that appears on the letterhead and footer."""

    address: Address
    country: str
    bank: str
    iban: str
    bic: str
    tax_number: str
    email: str
    paypal: str

    @property
    def return_address_line(self) -> str:
        """The small underlined line above the recipient's address."""
        return f"{self.address.name} – {self.address.street} - {self.address.city}"


@dataclass(frozen=True, slots=True)
class Lesson:
    """A lesson that was taught and is therefore billable."""

    taught_on: date
    quantity: Decimal
    column_values: Mapping[str, ColumnValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BillingTemplate:
    """A customer's invoicing settings: price, wording and extra columns."""

    unit_price: Decimal
    unit: str = DEFAULT_BILLING_UNIT
    description: str = DEFAULT_LESSON_DESCRIPTION
    columns: Sequence[Column] = ()


@dataclass(frozen=True, slots=True)
class LineItem:
    """One row of the line item table, with its total already computed."""

    taught_on: date
    quantity: Decimal
    unit: str
    description: str
    unit_price: Decimal
    column_values: tuple[ColumnValue, ...]
    total: Decimal

    @property
    def label(self) -> str:
        """The text of the "Bezeichnung / Datum" column."""
        return f"{self.description} / {self.taught_on:%d.%m.%Y}"


@dataclass(frozen=True, slots=True)
class Invoice:
    """A fully computed invoice, ready to be rendered.

    Everything needed for the document is held here by value. Once released,
    an invoice must not change when the customer, template or lessons behind
    it are edited later.
    """

    number: int
    issued_on: date
    issuer: Issuer
    recipient: Address
    period: BillingPeriod
    columns: tuple[Column, ...]
    line_items: tuple[LineItem, ...]
    total: Decimal
    paid_on: date | None = None


def column_shares(
    template: BillingTemplate, lesson: Lesson
) -> tuple[tuple[Column, ColumnValue, Decimal], ...]:
    """Each column with its resolved value and its share of the row total.

    This is the only place that pairs a column with what it costs; every
    other view of extra costs derives from it.
    """
    shares = []
    for column in template.columns:
        value = column.value_for(lesson.column_values)
        shares.append((column, value, column.contribution(value, lesson.quantity)))
    return tuple(shares)


def build_line_item(template: BillingTemplate, lesson: Lesson) -> LineItem:
    """Turn one taught lesson into a priced row."""
    shares = column_shares(template, lesson)
    return LineItem(
        taught_on=lesson.taught_on,
        quantity=lesson.quantity,
        unit=template.unit,
        description=template.description,
        unit_price=template.unit_price,
        column_values=tuple(value for _, value, _ in shares),
        total=round_to_cents(lesson.quantity * template.unit_price)
        + sum((share for _, _, share in shares), start=ZERO),
    )


def build_invoice(
    *,
    number: int,
    issued_on: date,
    issuer: Issuer,
    recipient: Address,
    template: BillingTemplate,
    period: BillingPeriod,
    lessons: Sequence[Lesson],
    paid_on: date | None = None,
) -> Invoice:
    """Build an invoice from every lesson that falls into ``period``.

    Lessons outside the period are ignored, and the rows come out in
    chronological order regardless of the order they are passed in.
    """
    line_items = tuple(
        build_line_item(template, lesson)
        for lesson in sorted(lessons, key=lambda lesson: lesson.taught_on)
        if period.covers(lesson.taught_on)
    )
    return Invoice(
        number=number,
        issued_on=issued_on,
        issuer=issuer,
        recipient=recipient,
        period=period,
        columns=tuple(template.columns),
        line_items=line_items,
        total=sum((item.total for item in line_items), start=ZERO),
        paid_on=paid_on,
    )
