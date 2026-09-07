"""What the ticked-off lessons of one month are worth.

Counted from the lessons themselves rather than from issued invoices, so the
figure grows with every lesson ticked off instead of jumping once a month
when the invoices go out. Each month starts again at nothing.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from sqlmodel import Session, col, select

from invoicing.constant import ZERO
from invoicing.lesson_pricing import StoredLessonPricer
from invoicing.storage.models import Lesson, LessonStatus
from invoicing.utils import billing_templates_by_customer, sum_of_cents


class LessonsEarnedInTheMonth:
    """Adds up what the lessons of one month have earned so far."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def total_for(self, year: int, month: int) -> Decimal:
        """The worth of every lesson ticked off in that month.

        Lessons whose customer has no terms yet are worth nothing and are
        quietly left out.
        """
        first_of_month = date(year, month, 1)
        last_of_month = first_of_month + relativedelta(months=1, days=-1)
        lessons = self._session.exec(
            select(Lesson)
            .where(Lesson.status == LessonStatus.DONE)
            .where(col(Lesson.taught_on).between(first_of_month, last_of_month))
        ).all()
        if not lessons:
            return ZERO
        terms_by_customer = billing_templates_by_customer(
            self._session, [lesson.customer_id for lesson in lessons]
        )
        return sum_of_cents(
            StoredLessonPricer(terms).priced_line(lesson).total
            for lesson in lessons
            if (terms := terms_by_customer.get(lesson.customer_id)) is not None
        )
