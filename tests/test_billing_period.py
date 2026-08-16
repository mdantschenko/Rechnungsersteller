from __future__ import annotations

from datetime import date

import pytest

from invoicing.constant import BillingCycle
from invoicing.domain.billing_calendar import BillingCalendar


def test_month_start_covers_the_previous_calendar_month() -> None:
    period = BillingCalendar(BillingCycle.MONTH_START).period_closing_on(
        date(2026, 8, 1)
    )

    assert period.printed_from == date(2026, 7, 1)
    assert period.first_day == date(2026, 7, 1)
    assert period.last_day == date(2026, 7, 31)


def test_month_midpoint_runs_from_the_day_after_the_printed_start() -> None:
    period = BillingCalendar(BillingCycle.MONTH_MIDPOINT).period_closing_on(
        date(2026, 7, 15)
    )

    assert period.printed_from == date(2026, 6, 15)
    assert period.first_day == date(2026, 6, 16)
    assert period.last_day == date(2026, 7, 15)


def test_both_ends_of_the_printed_range_are_billed() -> None:
    period = BillingCalendar(BillingCycle.MONTH_START).period_closing_on(
        date(2026, 8, 1)
    )

    assert period.covers(date(2026, 7, 1))
    assert period.covers(date(2026, 7, 31))
    assert not period.covers(date(2026, 6, 30))
    assert not period.covers(date(2026, 8, 1))


def test_a_lesson_on_the_boundary_belongs_to_the_period_ending_there() -> None:
    calendar = BillingCalendar(BillingCycle.MONTH_MIDPOINT)
    ending_there = calendar.period_closing_on(date(2026, 7, 15))
    starting_there = calendar.period_closing_on(date(2026, 8, 15))

    assert ending_there.covers(date(2026, 7, 15))
    assert not starting_there.covers(date(2026, 7, 15))


def test_consecutive_periods_leave_no_gap_and_no_overlap() -> None:
    for cycle, first_close, second_close in [
        (BillingCycle.MONTH_START, date(2026, 7, 1), date(2026, 8, 1)),
        (BillingCycle.MONTH_MIDPOINT, date(2026, 7, 15), date(2026, 8, 15)),
    ]:
        calendar = BillingCalendar(cycle)
        earlier = calendar.period_closing_on(first_close)
        later = calendar.period_closing_on(second_close)

        assert earlier.last_day.toordinal() + 1 == later.first_day.toordinal()


def test_closing_on_a_day_that_closes_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="does not close"):
        BillingCalendar(BillingCycle.MONTH_MIDPOINT).period_closing_on(
            date(2026, 6, 20)
        )


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
    assert BillingCalendar(cycle).next_closing_day(day) == expected


def test_recognises_closing_days() -> None:
    assert BillingCalendar(BillingCycle.MONTH_MIDPOINT).is_closing_day(
        date(2026, 6, 15)
    )
    assert BillingCalendar(BillingCycle.MONTH_START).is_closing_day(date(2026, 6, 1))


def test_rejects_days_that_close_nothing() -> None:
    assert not BillingCalendar(BillingCycle.MONTH_MIDPOINT).is_closing_day(
        date(2026, 6, 1)
    )
    assert not BillingCalendar(BillingCycle.MONTH_START).is_closing_day(
        date(2026, 6, 15)
    )


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
    period = BillingCalendar(cycle).period_containing(lesson_date)

    assert period.last_day == expected_last_day
    assert period.covers(lesson_date)
