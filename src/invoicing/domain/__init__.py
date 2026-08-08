"""The business rules, and the public surface every other layer builds on.

Re-exported here so that callers depend on one domain interface instead of on
individual module paths, and so that the dependency graph shows the domain as
a whole.
"""

from invoicing.domain.billing_period import (
    BillingCycle,
    BillingPeriod,
    is_closing_day,
    next_closing_day,
    period_closing_on,
    period_containing,
)
from invoicing.domain.columns import (
    Column,
    ColumnValue,
    TotalRule,
    ValueKind,
    ValueSource,
)
from invoicing.domain.invoice import (
    Address,
    BillingTemplate,
    Invoice,
    Issuer,
    Lesson,
    LineItem,
    build_invoice,
    build_line_item,
)
from invoicing.domain.invoice_numbers import NumberSequence
from invoicing.domain.money import format_euro, format_quantity, round_to_cents

__all__ = [
    "Address",
    "BillingCycle",
    "BillingPeriod",
    "BillingTemplate",
    "Column",
    "ColumnValue",
    "Invoice",
    "Issuer",
    "Lesson",
    "LineItem",
    "NumberSequence",
    "TotalRule",
    "ValueKind",
    "ValueSource",
    "build_invoice",
    "build_line_item",
    "format_euro",
    "format_quantity",
    "is_closing_day",
    "next_closing_day",
    "period_closing_on",
    "period_containing",
    "round_to_cents",
]
