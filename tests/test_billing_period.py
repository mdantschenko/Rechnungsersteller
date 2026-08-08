from __future__ import annotations

from datetime import date

import pytest

from invoicing.domain.billing_period import (
    BillingCycle,
    is_closing_day,
    next_closing_day,
    period_closing_on,
    period_containing,
)


def test_month_start_covers_the_previous_calendar_month() -> None:
    period = period_closing_on(BillingCycle.MONTH_START, date(2026, 8, 1))

    assert period.printed_from == date(2026, 7, 1)
    assert period.first_day == date(2026, 7, 1)
    assert period.last_day == date(2026, 7, 31)


def test_month_midpoint_runs_from_the_day_after_the_printed_start() -> None:
    period = period_closing_on(BillingCycle.MONTH_MIDPOINT, date(2026, 7, 15))

    assert period.printed_from == date(2026, 6, 15)
    assert period.first_day == date(2026, 6, 16)
    assert period.last_day == date(2026, 7, 15)


def test_both_ends_of_the_printed_range_are_billed() -> None:
    period = period_closing_on(BillingCycle.MONTH_START, date(2026, 8, 1))

    assert period.covers(date(2026, 7, 1))
    assert period.covers(date(2026, 7, 31))
    assert not period.covers(date(2026, 6, 30))
    assert not period.covers(date(2026, 8, 1))


def test_a_lesson_on_the_boundary_belongs_to_the_period_ending_there() -> None:
    ending_there = period_closing_on(BillingCycle.MONTH_MIDPOINT, date(2026, 7, 15))
    starting_there = period_closing_on(BillingCycle.MONTH_MIDPOINT, date(2026, 8, 15))

    assert ending_there.covers(date(2026, 7, 15))
    assert not starting_there.covers(date(2026, 7, 15))


def test_consecutive_periods_leave_no_gap_and_no_overlap() -> None:
    for cycle, first_close, second_close in [
        (BillingCycle.MONTH_START, date(2026, 7, 1), date(2026, 8, 1)),
        (BillingCycle.MONTH_MIDPOINT, date(2026, 7, 15), date(2026, 8, 15)),
    ]:
        earlier = period_closing_on(cycle, first_close)
        later = period_closing_on(cycle, second_close)

        assert earlier.last_day.toordinal() + 1 == later.first_day.toordinal()


def test_closing_on_a_day_that_closes_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="does not close"):
        period_closing_on(BillingCycle.MONTH_MIDPOINT, date(2026, 6, 20))


@pytest.mark.parametrize(
    ("cycle", "day", "expected"),
    [
        (BillingCycle.MONTH_MIDPOINT, date(2026, 7, 10), date(2026, 7, 15)),
        (BillingCycle.MONTH_MIDPOINT, date(2026, 7, 15), date(2026, 7, 15)),
        (BillingCycle.MONTH_MIDPOINT, date(2026, 7, 31), date(2026, 8, 15)),
        (BillingCycle.MONTH_START, date(2026, 7, 1), date(2026, 7, 1)),
        (BillingCycle.MONTH_START, date(2026, 7, 2), date(2026, 8, 1)),
        (BillingCycle.MONTH_MIDPOINT, date(2026, 1, 31), date(2026, 2, 15)),
    ],
)
def test_finds_the_next_closing_day(
    cycle: BillingCycle, day: date, expected: date
) -> None:
    assert next_closing_day(cycle, day) == expected


def test_recognises_closing_days() -> None:
    assert is_closing_day(BillingCycle.MONTH_MIDPOINT, date(2026, 6, 15))
    assert is_closing_day(BillingCycle.MONTH_START, date(2026, 6, 1))


def test_rejects_days_that_close_nothing() -> None:
    assert not is_closing_day(BillingCycle.MONTH_MIDPOINT, date(2026, 6, 1))
    assert not is_closing_day(BillingCycle.MONTH_START, date(2026, 6, 15))


@pytest.mark.parametrize(
    ("cycle", "lesson_date", "expected_last_day"),
    [
        (BillingCycle.MONTH_MIDPOINT, date(2026, 5, 20), date(2026, 6, 15)),
        (BillingCycle.MONTH_MIDPOINT, date(2026, 6, 5), date(2026, 6, 15)),
        (BillingCycle.MONTH_MIDPOINT, date(2026, 6, 15), date(2026, 6, 15)),
        (BillingCycle.MONTH_MIDPOINT, date(2026, 6, 16), date(2026, 7, 15)),
        (BillingCycle.MONTH_START, date(2026, 5, 1), date(2026, 5, 31)),
        (BillingCycle.MONTH_START, date(2026, 5, 31), date(2026, 5, 31)),
    ],
)
def test_assigns_a_lesson_to_its_period(
    cycle: BillingCycle, lesson_date: date, expected_last_day: date
) -> None:
    period = period_containing(cycle, lesson_date)

    assert period.last_day == expected_last_day
    assert period.covers(lesson_date)
