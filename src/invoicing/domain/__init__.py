"""The business rules, and the public surface every other layer builds on.

Re-exported here so that callers depend on one domain interface instead of on
individual module paths, and so that the dependency graph shows the domain as
a whole. The dataclasses themselves live in :mod:`invoicing.data_classes`.
"""

from invoicing.constant import BillingCycle, TotalRule, ValueKind, ValueSource
from invoicing.domain.billing_period import (
    is_closing_day,
    next_closing_day,
    period_closing_on,
    period_containing,
)
from invoicing.domain.invoice import build_invoice, build_line_item
from invoicing.domain.invoice_numbers import NumberSequence
from invoicing.domain.money import format_euro, format_quantity

__all__ = [
    "BillingCycle",
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
]
