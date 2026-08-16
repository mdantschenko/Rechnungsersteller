"""German number formatting for amounts and quantities.

Every amount in the system is a :class:`~decimal.Decimal` and passes through
:func:`invoicing.utils.round_to_cents`. Binary floating point cannot represent
0.10 exactly, and that error compounds across invoice lines into cent
mismatches the customer can see.
"""

from __future__ import annotations

from decimal import Decimal

from babel.numbers import format_currency, format_decimal

from invoicing.constant import GERMAN_LOCALE


def format_euro(amount: Decimal) -> str:
    """Render an amount the German way, for example ``33,33 €``."""
    return format_currency(amount, "EUR", locale=GERMAN_LOCALE)


def format_quantity(amount: Decimal) -> str:
    """Render a lesson count without trailing zeros: ``1``, ``0,5``, ``1,5``."""
    return format_decimal(_without_trailing_zeros(amount), locale=GERMAN_LOCALE)


def _without_trailing_zeros(amount: Decimal) -> Decimal:
    normalized = amount.normalize()
    is_whole_number = normalized == normalized.to_integral_value()
    # normalize() turns Decimal("20") into 2E+1, which Babel renders verbatim.
    return normalized.quantize(Decimal(1)) if is_whole_number else normalized
