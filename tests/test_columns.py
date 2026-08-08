from __future__ import annotations

from decimal import Decimal

from invoicing.domain.columns import Column, TotalRule, ValueKind, ValueSource

ONE_HOUR = Decimal("1")
TWO_HOURS = Decimal("2")

TRAVEL_COST_PRINTED_AS_ZERO = Column(
    label="Anfahrtskosten",
    total_rule=TotalRule.ADD_PER_ROW,
    placeholder="0 €",
)

TRAVEL_COST_NOT_APPLICABLE = Column(label="Anfahrtskosten")

EXERCISE_SHEETS = Column(
    label="Übungsaufgaben",
    source=ValueSource.PER_LESSON,
    total_rule=TotalRule.ADD_PER_ROW,
    default_value=Decimal("20"),
)


def test_missing_value_shows_the_placeholder() -> None:
    assert TRAVEL_COST_PRINTED_AS_ZERO.display(None) == "0 €"
    assert TRAVEL_COST_NOT_APPLICABLE.display(None) == "/"


def test_missing_value_adds_nothing_to_the_row() -> None:
    assert TRAVEL_COST_PRINTED_AS_ZERO.contribution(None, ONE_HOUR) == Decimal("0.00")


def test_a_fixed_column_ignores_what_the_lesson_carries() -> None:
    assert (
        TRAVEL_COST_PRINTED_AS_ZERO.value_for({"Anfahrtskosten": Decimal("5")}) is None
    )


def test_a_per_lesson_column_prefers_the_lessons_value() -> None:
    assert EXERCISE_SHEETS.value_for({"Übungsaufgaben": Decimal("30")}) == Decimal("30")


def test_a_per_lesson_column_falls_back_to_its_default() -> None:
    assert EXERCISE_SHEETS.value_for({}) == Decimal("20")


def test_a_lesson_can_blank_out_a_column() -> None:
    assert EXERCISE_SHEETS.value_for({"Übungsaufgaben": None}) is None


def test_added_per_row_does_not_scale_with_the_hours() -> None:
    assert EXERCISE_SHEETS.contribution(Decimal("20"), TWO_HOURS) == Decimal("20.00")


def test_multiplied_by_quantity_scales_with_the_hours() -> None:
    per_hour_surcharge = Column(
        label="Materialzuschlag",
        total_rule=TotalRule.MULTIPLY_BY_QUANTITY,
        default_value=Decimal("2.50"),
    )

    assert per_hour_surcharge.contribution(Decimal("2.50"), TWO_HOURS) == Decimal(
        "5.00"
    )


def test_an_excluded_column_never_touches_the_total() -> None:
    note = Column(label="Notiz", kind=ValueKind.TEXT, default_value="online")

    assert note.contribution("online", ONE_HOUR) == Decimal("0.00")
    assert note.display("online") == "online"


def test_money_is_formatted_german_and_quantities_lose_trailing_zeros() -> None:
    hours = Column(label="Fahrtzeit", kind=ValueKind.QUANTITY)

    assert TRAVEL_COST_PRINTED_AS_ZERO.display(Decimal("20")) == "20,00\xa0€"
    assert hours.display(Decimal("0.50")) == "0,5"
