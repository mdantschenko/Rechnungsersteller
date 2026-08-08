"""Extra columns of the line item table, configured per customer.

Existing invoices show one such column in three shapes: a travel cost column
printing ``0 €`` on every row, the same column printing ``/`` for another
customer, and an exercise sheet column carrying a different amount per lesson.
All three are the same :class:`Column` and differ only in source, default value
and placeholder.

A value of ``None`` means "nothing to show here": the placeholder is printed
and the column adds nothing to the row total.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from invoicing.domain.money import ZERO, format_euro, format_quantity, round_to_cents

ColumnValue = Decimal | str | None


class ValueSource(StrEnum):
    """Where a column takes its value from."""

    FIXED = "fixed"
    PER_LESSON = "per_lesson"


class ValueKind(StrEnum):
    """How a value is rendered, and whether it can count towards a total."""

    MONEY = "money"
    QUANTITY = "quantity"
    TEXT = "text"


class TotalRule(StrEnum):
    """How a column enters the row total."""

    EXCLUDED = "excluded"
    ADD_PER_ROW = "add_per_row"
    MULTIPLY_BY_QUANTITY = "multiply_by_quantity"


@dataclass(frozen=True, slots=True)
class Column:
    """One configurable column between unit price and row total."""

    label: str
    source: ValueSource = ValueSource.FIXED
    kind: ValueKind = ValueKind.MONEY
    total_rule: TotalRule = TotalRule.EXCLUDED
    default_value: ColumnValue = None
    placeholder: str = "/"

    def value_for(self, lesson_values: Mapping[str, ColumnValue]) -> ColumnValue:
        """The value for one row; what the lesson carries beats the default."""
        if self.source is ValueSource.PER_LESSON and self.label in lesson_values:
            return lesson_values[self.label]
        return self.default_value

    def display(self, value: ColumnValue) -> str:
        """The text printed in this column's cell."""
        if value is None:
            return self.placeholder
        if self.kind is ValueKind.MONEY:
            return format_euro(round_to_cents(value))
        if self.kind is ValueKind.QUANTITY:
            return format_quantity(Decimal(value))
        return str(value)

    def contribution(self, value: ColumnValue, quantity: Decimal) -> Decimal:
        """What this column adds to the row total."""
        if value is None or self.kind is not ValueKind.MONEY:
            return ZERO
        if self.total_rule is TotalRule.ADD_PER_ROW:
            return round_to_cents(value)
        if self.total_rule is TotalRule.MULTIPLY_BY_QUANTITY:
            return round_to_cents(quantity * Decimal(value))
        return ZERO
