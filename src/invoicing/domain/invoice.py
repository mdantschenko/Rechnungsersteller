"""Turning taught lessons into a finished invoice.

Each row is rounded on its own and the rows are then summed, so the printed
total is exactly what a customer gets by adding up the visible rows. Rounding
the exact sum instead would occasionally differ by a cent from that addition.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from invoicing.data_classes import (
    Address,
    BillingPeriod,
    ExtraColumn,
    ExtraColumnValue,
    Invoice,
    InvoiceTerms,
    Issuer,
    LineItem,
    TaughtLesson,
)
from invoicing.domain.extra_column_rules import ExtraColumnRules
from invoicing.utils import round_to_cents, sum_of_cents


def column_shares(
    template: InvoiceTerms, lesson: TaughtLesson
) -> tuple[tuple[ExtraColumn, ExtraColumnValue, Decimal], ...]:
    """Each column with its resolved value and its share of the row total.

    This is the only place that pairs a column with what it costs; every
    other view of extra costs derives from it.
    """
    shares = []
    for column in template.columns:
        rules = ExtraColumnRules(column)
        value = rules.value_for(lesson.column_values)
        shares.append((column, value, rules.contribution(value, lesson.quantity)))
    return tuple(shares)


def build_line_item(template: InvoiceTerms, lesson: TaughtLesson) -> LineItem:
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
        + sum_of_cents(share for _, _, share in shares),
    )


def build_invoice(
    *,
    number: int,
    issued_on: date,
    issuer: Issuer,
    recipient: Address,
    template: InvoiceTerms,
    period: BillingPeriod,
    lessons: Sequence[TaughtLesson],
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
        total=sum_of_cents(item.total for item in line_items),
        paid_on=paid_on,
    )
