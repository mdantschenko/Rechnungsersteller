"""Monetary amounts and German number formatting.

Every amount in the system is a :class:`~decimal.Decimal` and passes through
:func:`round_to_cents`. Binary floating point cannot represent 0.10 exactly,
and that error compounds across invoice lines into cent mismatches the
customer can see.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from babel.numbers import format_currency, format_decimal

CENT = Decimal("0.01")
TEN_THOUSANDTH = Decimal("0.0001")
ZERO = Decimal("0.00")
GERMAN_LOCALE = "de_DE"


def round_to_cents(amount: Decimal | int | str) -> Decimal:
    """Round half up, the way invoices are rounded.

    Half up rather than Python's default banker's rounding, so that the
    customer reproduces every line with a pocket calculator.
    """
    return Decimal(amount).quantize(CENT, rounding=ROUND_HALF_UP)


def round_quantity(amount: Decimal) -> Decimal:
    """Round a count to four places: fine enough that a third of an hour
    times the rate still lands on the cent a calculator produces."""
    return amount.quantize(TEN_THOUSANDTH, rounding=ROUND_HALF_UP)


def parse_user_amount(value: str) -> Decimal | None:
    """Read an amount the way a person types it: ``20,00 €``, ``1.234,56``.

    None when nothing readable remains — the caller decides whether that
    means "empty" or "complain".
    """
    cleaned = value.replace("€", "").replace(" ", "").strip()
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


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
