"""How the application writes German: amounts, counts, dates and clock times.

Web pages and printed invoices format through the shared
:data:`german_formatter` instance, so a page and the PDF it previews can
never disagree. Amounts stay :class:`~decimal.Decimal` throughout; binary
floats cannot represent 0.10 exactly, and that error compounds across
invoice lines into cent mismatches the customer can see.
"""

from __future__ import annotations

from datetime import date, time, timedelta
from decimal import Decimal

from babel.dates import format_date
from babel.numbers import format_currency, format_decimal

from invoicing.constant import GERMAN_LOCALE
from invoicing.utils import round_to_cents


class GermanFormatter:
    """Renders amounts, quantities, dates and clock times the German way."""

    def __init__(self, locale: str = GERMAN_LOCALE) -> None:
        self.locale = locale

    def format_euro(self, amount: Decimal) -> str:
        """An amount as German letters print it, for example ``33,33 €``."""
        return format_currency(amount, "EUR", locale=self.locale)

    def euro_rounded(self, amount: Decimal | int | str) -> str:
        """The amount rounded to whole cents first, then rendered as euro."""
        return self.format_euro(round_to_cents(amount))

    def format_quantity(self, amount: Decimal) -> str:
        """A lesson count without trailing zeros: ``1``, ``0,5``, ``1,5``."""
        return format_decimal(self._without_trailing_zeros(amount), locale=self.locale)

    def format_german_date(self, day: date) -> str:
        """A date as German letters write it, for example ``17.03.2026``."""
        return f"{day:%d.%m.%Y}"

    def short_date(self, day: date) -> str:
        """A day for tight lists: ``Mo. 4.3.``."""
        return format_date(day, "EE d.M.", locale=self.locale)

    def long_weekday(self, day: date) -> str:
        """A day with its full weekday and month: ``Montag, 4. März``."""
        return format_date(day, "EEEE, d. MMMM", locale=self.locale)

    def month_name(self, day: date) -> str:
        """The German name of the day's month: ``März``."""
        return format_date(day, "LLLL", locale=self.locale)

    def clock(self, moment: time) -> str:
        """A clock time the way the calendar prints it: ``14:30``."""
        return f"{moment:%H:%M}"

    def week_heading(self, monday: date, sunday: date) -> str:
        """The heading over one calendar week, month names only where needed."""
        if monday.month == sunday.month:
            return f"{monday.day}.–{sunday.day}. {self.month_name(monday)}"
        return (
            f"{format_date(monday, 'd. MMM', self.locale)} – "
            f"{format_date(sunday, 'd. MMM y', self.locale)}"
        )

    def weekday_names(self) -> list[str]:
        """The short weekday names of a calendar header, Monday first."""
        monday = date(2024, 1, 1)
        return [
            format_date(monday + timedelta(days=offset), "EEEEEE", locale=self.locale)
            for offset in range(7)
        ]

    def _without_trailing_zeros(self, amount: Decimal) -> Decimal:
        """The amount normalized so Babel prints it plainly, never as ``2E+1``."""
        normalized = amount.normalize()
        is_whole_number = normalized == normalized.to_integral_value()
        return normalized.quantize(Decimal(1)) if is_whole_number else normalized


german_formatter = GermanFormatter()
