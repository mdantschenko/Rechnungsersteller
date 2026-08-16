"""Extra columns of the line item table, configured per customer.

Existing invoices show one such column in three shapes: a travel cost column
printing ``0 €`` on every row, the same column printing ``/`` for another
customer, and an exercise sheet column carrying a different amount per lesson.
All three are the same :class:`Column` and differ only in source, default value
and placeholder.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from invoicing.constant import (
    EXTRA_COLUMN_PLACEHOLDER,
    TotalRule,
    ValueKind,
    ValueSource,
)

ColumnValue = Decimal | str | None


@dataclass(frozen=True, slots=True)
class Column:
    """One configurable column between unit price and row total."""

    label: str
    source: ValueSource = ValueSource.FIXED
    kind: ValueKind = ValueKind.MONEY
    total_rule: TotalRule = TotalRule.EXCLUDED
    default_value: ColumnValue = None
    placeholder: str = EXTRA_COLUMN_PLACEHOLDER
