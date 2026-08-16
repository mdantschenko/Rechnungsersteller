from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest

from invoicing.utils import (
    parse_german_amount,
    parse_german_date,
    parse_optional_clock_time,
)


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("1.234,56", "1234.56"),
        ("30", "30"),
        ("20,00 €", "20.00"),
        ("0,5", "0.5"),
    ],
)
def test_reads_amounts_the_way_a_person_writes_them(
    written: str, expected: str
) -> None:
    assert parse_german_amount(written) == Decimal(expected)


@pytest.mark.parametrize("junk", ["Unsinn", "", "   ", "€", "1,2,3"])
def test_unreadable_amounts_come_back_as_none(junk: str) -> None:
    assert parse_german_amount(junk) is None


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("11.03.2024", date(2024, 3, 11)),
        ("1.2.2024", date(2024, 2, 1)),
    ],
)
def test_reads_german_dates(written: str, expected: date) -> None:
    assert parse_german_date(written) == expected


@pytest.mark.parametrize("junk", ["Unsinn", "2024-03-11", "11.03"])
def test_unreadable_dates_raise(junk: str) -> None:
    with pytest.raises(ValueError):
        parse_german_date(junk)


def test_reads_a_clock_time_from_a_form_field() -> None:
    assert parse_optional_clock_time("14:30") == time(14, 30)


def test_an_empty_form_field_means_no_time() -> None:
    assert parse_optional_clock_time("") is None
