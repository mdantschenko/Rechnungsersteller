"""Pricing a stored lesson exactly as its invoice row will be priced."""

from __future__ import annotations

from decimal import Decimal

from invoicing.constant import ValueKind
from invoicing.data_classes import (
    ExtraColumn,
    ExtraColumnValue,
    InvoiceTerms,
    LineItem,
    TaughtLesson,
)
from invoicing.domain.invoice_builder import InvoiceBuilder
from invoicing.storage import models
from invoicing.utils import hours_per_unit, parse_german_amount, round_quantity


class StoredLessonPricer:
    """Turns one customer's stored billing template into priced lesson rows."""

    def __init__(self, terms: models.BillingTemplate) -> None:
        self.terms = terms

    def as_domain_terms(self) -> InvoiceTerms:
        """The customer's stored terms as the domain template that prices rows."""
        return InvoiceTerms(
            unit_price=self.terms.unit_price,
            unit=self.terms.unit,
            description=self.terms.description,
            columns=self.stored_columns(),
        )

    def as_domain_lesson(self, lesson: models.Lesson) -> TaughtLesson:
        """The stored lesson as the domain lesson an invoice row is built from."""
        columns = self.stored_columns()
        kinds = {column.label: column.kind for column in columns}
        return TaughtLesson(
            taught_on=lesson.taught_on,
            quantity=self.billable_quantity(lesson),
            column_values=self.typed_values(kinds, lesson.column_values),
        )

    def priced_line(self, lesson: models.Lesson) -> LineItem:
        """One stored lesson priced exactly as its invoice row will be.

        The earnings view and the invoice must never disagree about what a
        lesson is worth, so both go through this one method.
        """
        return InvoiceBuilder(self.as_domain_terms()).build_line_item(
            self.as_domain_lesson(lesson)
        )

    def priced_columns(
        self, lesson: models.Lesson
    ) -> tuple[tuple[ExtraColumn, ExtraColumnValue, Decimal], ...]:
        """Each extra column with its value and its share for this stored lesson."""
        return InvoiceBuilder(self.as_domain_terms()).column_shares(
            self.as_domain_lesson(lesson)
        )

    def billable_quantity(self, lesson: models.Lesson) -> Decimal:
        """The lesson measured in the template's unit.

        The unit is arithmetic: "h" prices per hour, "1,5h" prices per ninety
        minutes, so a ninety-minute lesson is exactly one unit then.
        """
        return round_quantity(lesson.quantity / hours_per_unit(self.terms.unit))

    def stored_columns(self) -> tuple[ExtraColumn, ...]:
        """The customer's extra columns as domain objects, defaults parsed."""
        return tuple(
            ExtraColumn(
                label=stored.label,
                source=stored.source,
                kind=stored.kind,
                total_rule=stored.total_rule,
                default_value=self._parsed_column_value(
                    stored.kind, stored.default_value
                ),
                placeholder=stored.placeholder,
            )
            for stored in self.terms.columns
        )

    def typed_values(
        self, kinds: dict[str, ValueKind], raw: dict[str, str | None]
    ) -> dict[str, ExtraColumnValue]:
        """The stored raw cell values, parsed to what each column's kind expects."""
        return {
            label: self._parsed_column_value(kinds[label], value)
            for label, value in raw.items()
            if label in kinds
        }

    def _parsed_column_value(
        self, kind: ValueKind, value: str | None
    ) -> ExtraColumnValue:
        if value is None:
            return None
        if kind is ValueKind.TEXT:
            return value
        # Stored values may carry a German comma or a stray currency sign from
        # older input; unreadable ones count as empty rather than crashing the
        # whole billing page.
        return parse_german_amount(value)
