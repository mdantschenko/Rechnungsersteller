from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest

from invoicing.german_formatter import GermanFormatter

formatter = GermanFormatter()


@pytest.mark.parametrize(
    ("amount", "expected"),
    [("33.33", "33,33\xa0€"), ("0", "0,00\xa0€"), ("1234.5", "1.234,50\xa0€")],
)
def test_formats_amounts_the_german_way(amount: str, expected: str) -> None:
    assert formatter.format_euro(Decimal(amount)) == expected


def test_rounds_to_cents_before_formatting() -> None:
    assert formatter.euro_rounded(Decimal("13.335")) == "13,34\xa0€"


@pytest.mark.parametrize(
    ("quantity", "expected"),
    [
        ("1", "1"),
        ("1.0", "1"),
        ("0.5", "0,5"),
        ("1.50", "1,5"),
        ("2", "2"),
        ("20", "20"),
    ],
)
def test_drops_trailing_zeros_from_quantities(quantity: str, expected: str) -> None:
    assert formatter.format_quantity(Decimal(quantity)) == expected


def test_writes_dates_the_german_way() -> None:
    assert formatter.format_german_date(date(2026, 3, 17)) == "17.03.2026"


def test_writes_clock_times_with_leading_zeros() -> None:
    assert formatter.clock(time(9, 5)) == "09:05"


def test_a_week_inside_one_month_names_the_month_once() -> None:
    assert formatter.week_heading(date(2026, 3, 2), date(2026, 3, 8)) == "2.–8. März"


def test_a_week_across_months_names_both() -> None:
    heading = formatter.week_heading(date(2026, 3, 30), date(2026, 4, 5))
    assert heading == "30. März – 5. Apr. 2026"


def test_weekday_names_start_on_monday() -> None:
    names = formatter.weekday_names()
    assert names[0] == "Mo."
    assert len(names) == 7
