from __future__ import annotations

from decimal import Decimal

import pytest

from invoicing.domain.money import format_euro, format_quantity, round_to_cents


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ("13.335", "13.34"),
        ("13.334", "13.33"),
        ("0.005", "0.01"),
        ("0.015", "0.02"),
        ("66.66", "66.66"),
    ],
)
def test_rounds_half_away_from_zero(amount: str, expected: str) -> None:
    assert round_to_cents(Decimal(amount)) == Decimal(expected)


def test_rounds_up_where_pythons_default_rounds_down() -> None:
    assert Decimal("0.025").quantize(Decimal("0.01")) == Decimal("0.02")
    assert round_to_cents(Decimal("0.025")) == Decimal("0.03")


@pytest.mark.parametrize(
    ("amount", "expected"),
    [("33.33", "33,33\xa0€"), ("0", "0,00\xa0€"), ("1234.5", "1.234,50\xa0€")],
)
def test_formats_amounts_the_german_way(amount: str, expected: str) -> None:
    assert format_euro(Decimal(amount)) == expected


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
    assert format_quantity(Decimal(quantity)) == expected
