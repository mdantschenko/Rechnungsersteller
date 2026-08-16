"""The stretch of time one invoice covers.

A customer is billed either on the first of a month for the whole previous
month, or on the fifteenth for the stretch since the last fifteenth.

The two cycles print their range differently, and that difference decides where
a lesson taught on a boundary day belongs:

- A month-start invoice prints a whole calendar month, 01.07. to 31.07. Both
  ends are covered and the next period starts a day later, so nothing overlaps.
- A mid-month invoice prints boundary to boundary, 15.06. to 15.07., and the
  next one starts again at 15.07. Reading both ends as covered would bill a
  lesson on the fifteenth twice.

The historical invoices settle which end wins. Invoice 73 runs 15.05. to
15.06. and bills a lesson taught on 15.06.; the following invoice starts at
15.06. and does not. "bis zum" is therefore inclusive and the printed start day
belongs to the invoice before it.
"""

from __future__ import annotations

from datetime import date

from dateutil.relativedelta import relativedelta

from invoicing.constant import CLOSING_DAY_OF_MONTH, ONE_DAY, BillingCycle
from invoicing.data_classes import BillingPeriod


def is_closing_day(cycle: BillingCycle, day: date) -> bool:
    """Whether an invoice of this cycle is drawn up on the given day."""
    return day.day == CLOSING_DAY_OF_MONTH[cycle]


def next_closing_day(cycle: BillingCycle, on_or_after: date) -> date:
    """The first day on or after ``on_or_after`` that closes a period."""
    day_of_month = CLOSING_DAY_OF_MONTH[cycle]
    if on_or_after.day <= day_of_month:
        return on_or_after.replace(day=day_of_month)
    return (on_or_after + relativedelta(months=1)).replace(day=day_of_month)


def period_closing_on(cycle: BillingCycle, closing_day: date) -> BillingPeriod:
    """The period an invoice drawn up on ``closing_day`` settles.

    Raises:
        ValueError: if no period of this cycle closes on that day.
    """
    if not is_closing_day(cycle, closing_day):
        raise ValueError(f"{closing_day:%d.%m.%Y} does not close a {cycle} period")
    printed_from = closing_day - relativedelta(months=1)
    if cycle is BillingCycle.MONTH_MIDPOINT:
        return BillingPeriod(
            printed_from=printed_from,
            first_day=printed_from + ONE_DAY,
            last_day=closing_day,
        )
    return BillingPeriod(
        printed_from=printed_from,
        first_day=printed_from,
        last_day=closing_day - ONE_DAY,
    )


def period_containing(cycle: BillingCycle, lesson_date: date) -> BillingPeriod:
    """The period whose invoice a lesson on ``lesson_date`` appears on."""
    day_of_month = CLOSING_DAY_OF_MONTH[cycle]
    closes_this_month = lesson_date.day <= day_of_month
    closing_day = (
        lesson_date.replace(day=day_of_month)
        if closes_this_month
        else (lesson_date + relativedelta(months=1)).replace(day=day_of_month)
    )
    period = period_closing_on(cycle, closing_day)
    if period.covers(lesson_date):
        return period
    return period_closing_on(cycle, next_closing_day(cycle, closing_day + ONE_DAY))
