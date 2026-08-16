"""How one extra column resolves, prints and prices a row's value.

A value of ``None`` means "nothing to show here": the placeholder is printed
and the column adds nothing to the row total.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from invoicing.constant import ZERO, TotalRule, ValueKind, ValueSource
from invoicing.data_classes import ExtraColumn, ExtraColumnValue
from invoicing.domain.money import format_euro, format_quantity
from invoicing.utils import round_to_cents


class ExtraColumnRules:
    """The behaviour of one configured column, applied row by row."""

    def __init__(self, column: ExtraColumn) -> None:
        self.column = column

    def value_for(
        self, lesson_values: Mapping[str, ExtraColumnValue]
    ) -> ExtraColumnValue:
        """The value for one row; what the lesson carries beats the default."""
        if (
            self.column.source is ValueSource.PER_LESSON
            and self.column.label in lesson_values
        ):
            return lesson_values[self.column.label]
        return self.column.default_value

    def display(self, value: ExtraColumnValue) -> str:
        """The text printed in this column's cell."""
        if value is None:
            return self.column.placeholder
        if self.column.kind is ValueKind.MONEY:
            return format_euro(round_to_cents(value))
        if self.column.kind is ValueKind.QUANTITY:
            return format_quantity(Decimal(value))
        return str(value)

    def contribution(self, value: ExtraColumnValue, quantity: Decimal) -> Decimal:
        """What this column adds to the row total."""
        if value is None or self.column.kind is not ValueKind.MONEY:
            return ZERO
        if self.column.total_rule is TotalRule.ADD_PER_ROW:
            return round_to_cents(value)
        if self.column.total_rule is TotalRule.MULTIPLY_BY_QUANTITY:
            return round_to_cents(quantity * Decimal(value))
        return ZERO
