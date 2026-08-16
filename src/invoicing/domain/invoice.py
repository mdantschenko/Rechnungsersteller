"""Turning taught lessons into a finished invoice."""

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


class InvoiceBuilder:
    """Prices taught lessons under one set of invoice terms.

    Each row is rounded on its own and the rows are then summed, so the
    printed total is exactly what a customer gets by adding up the visible
    rows. Rounding the exact sum instead would occasionally differ by a cent
    from that addition.
    """

    def __init__(self, terms: InvoiceTerms) -> None:
        self.terms = terms

    def column_shares(
        self, lesson: TaughtLesson
    ) -> tuple[tuple[ExtraColumn, ExtraColumnValue, Decimal], ...]:
        """Each column with its resolved value and its share of the row total.

        This is the only place that pairs a column with what it costs; every
        other view of extra costs derives from it.
        """
        shares = []
        for column in self.terms.columns:
            rules = ExtraColumnRules(column)
            value = rules.value_for(lesson.column_values)
            shares.append((column, value, rules.contribution(value, lesson.quantity)))
        return tuple(shares)

    def build_line_item(self, lesson: TaughtLesson) -> LineItem:
        """Turn one taught lesson into a priced row."""
        shares = self.column_shares(lesson)
        return LineItem(
            taught_on=lesson.taught_on,
            quantity=lesson.quantity,
            unit=self.terms.unit,
            description=self.terms.description,
            unit_price=self.terms.unit_price,
            column_values=tuple(value for _, value, _ in shares),
            total=round_to_cents(lesson.quantity * self.terms.unit_price)
            + sum_of_cents(share for _, _, share in shares),
        )

    def build_invoice(
        self,
        *,
        number: int,
        issued_on: date,
        issuer: Issuer,
        recipient: Address,
        period: BillingPeriod,
        lessons: Sequence[TaughtLesson],
        paid_on: date | None = None,
    ) -> Invoice:
        """Build an invoice from every lesson that falls into ``period``.

        Lessons outside the period are ignored, and the rows come out in
        chronological order regardless of the order they are passed in.
        """
        line_items = tuple(
            self.build_line_item(lesson)
            for lesson in sorted(lessons, key=lambda lesson: lesson.taught_on)
            if period.covers(lesson.taught_on)
        )
        return Invoice(
            number=number,
            issued_on=issued_on,
            issuer=issuer,
            recipient=recipient,
            period=period,
            columns=tuple(self.terms.columns),
            line_items=line_items,
            total=sum_of_cents(item.total for item in line_items),
            paid_on=paid_on,
        )
