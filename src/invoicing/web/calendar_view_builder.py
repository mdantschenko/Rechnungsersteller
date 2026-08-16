"""Builds what the calendar pages show.

The grid itself comes from the standard library and the German month and
weekday names from Babel, so nothing here reimplements a calendar.

Building a view writes out the recurring lessons up to its end, which is what
lets you page forward and still see what is planned.
"""

from __future__ import annotations

from calendar import Calendar
from datetime import date, timedelta

from babel.dates import format_date
from dateutil.relativedelta import relativedelta
from sqlmodel import Session, col, select

from invoicing.alarms import LessonAlarmClock
from invoicing.constant import (
    FEDERAL_STATE_COLORS,
    GERMAN_LOCALE,
    WEEK_STARTS_ON_MONDAY,
    ValueSource,
)
from invoicing.data_classes import CalendarDay
from invoicing.feiertage import HolidayCalendar
from invoicing.german_formatter import german_formatter
from invoicing.lesson_pricing import StoredLessonPricer
from invoicing.push import WebPushSender
from invoicing.scheduling import LessonSeriesMaterialiser
from invoicing.storage.models import Lesson, LessonStatus
from invoicing.utils import billing_templates_by_customer, planning_horizon
from invoicing.web.store_queries import StoreQueries


class CalendarViewBuilder:
    """Builds the template contexts of the week, month and day pages."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._store = StoreQueries(session)

    def week_context(self, on: date) -> dict[str, object]:
        today = date.today()
        monday = on - timedelta(days=on.weekday())
        sunday = monday + timedelta(days=6)
        horizon = planning_horizon(self._store.app_settings(), today)
        LessonSeriesMaterialiser(self._session).materialise_all_active(
            until=max(sunday, horizon)
        )
        self._session.flush()
        lessons = self._lessons_between(monday, sunday)
        public, school = self._holiday_notes(monday, sunday)
        names = self._store.pupil_names_by_customer_id()
        return {
            "heading": german_formatter.week_heading(monday, sunday),
            "monday": monday,
            "days": [
                self._calendar_day_cell(
                    monday + timedelta(days=offset),
                    monday.month,
                    today,
                    lessons,
                    public,
                    school,
                    names,
                )
                for offset in range(7)
            ],
            "previous": monday - timedelta(days=7),
            "next": monday + timedelta(days=7),
            "today": today,
            "names": names,
            "places": self._store.lesson_places_by_customer_id(),
            "extras": self._lesson_extras(lessons),
            "series": self._store.series_labels(),
            "overdue": self._open_lessons_before(today),
            "colors": FEDERAL_STATE_COLORS,
            "back": f"/woche/{monday}",
        }

    def month_context(self, year: int, month: int) -> dict[str, object]:
        today = date.today()
        first_of_month = date(year, month, 1)
        weeks = Calendar(WEEK_STARTS_ON_MONDAY).monthdatescalendar(year, month)
        horizon = planning_horizon(self._store.app_settings(), today)
        LessonSeriesMaterialiser(self._session).materialise_all_active(
            until=max(weeks[-1][-1], horizon)
        )
        self._session.flush()
        lessons = self._lessons_between(weeks[0][0], weeks[-1][-1])
        public, school = self._holiday_notes(weeks[0][0], weeks[-1][-1])
        names = self._store.pupil_names_by_customer_id()
        return {
            "heading": format_date(first_of_month, "LLLL y", locale=GERMAN_LOCALE),
            "weekday_names": german_formatter.weekday_names(),
            "weeks": [
                [
                    self._calendar_day_cell(
                        day, month, today, lessons, public, school, names
                    )
                    for day in week
                ]
                for week in weeks
            ],
            "previous": first_of_month - timedelta(days=1),
            "next": first_of_month + relativedelta(months=1),
            "today": today,
            "reference": today if today.month == month else first_of_month,
            "names": names,
            "colors": FEDERAL_STATE_COLORS,
            "school_states": self._school_states(),
            "overdue": [
                lesson
                for lesson in self._open_lessons_before(today)
                if lesson.taught_on < today
            ],
        }

    def day_context(self, on: date) -> dict[str, object]:
        settings = self._store.app_settings()
        deliver = WebPushSender(self._session, settings).send_to_all
        LessonAlarmClock(self._session, settings, deliver).acknowledge_day(on)
        public, school = self._holiday_notes(on, on)
        lessons = self._lessons_between(on, on)
        return {
            "on": on,
            "heading": format_date(on, "EEEE, d. MMMM y", locale=GERMAN_LOCALE),
            "previous": on - timedelta(days=1),
            "next": on + timedelta(days=1),
            "today": date.today(),
            "lessons": lessons,
            "names": self._store.pupil_names_by_customer_id(),
            "places": self._store.lesson_places_by_customer_id(),
            "extras": self._lesson_extras(lessons),
            "series": self._store.series_labels(),
            "customers": self._store.active_customers(),
            "holiday": public.get(on),
            "vacations": school.get(on, []),
            "colors": FEDERAL_STATE_COLORS,
            "back": f"/tag/{on}",
        }

    def _calendar_day_cell(
        self,
        on: date,
        month: int,
        today: date,
        lessons: list[Lesson],
        public: dict[date, str],
        school: dict[date, list[tuple[str, str]]],
        names: dict[int, str],
    ) -> CalendarDay:
        todays = tuple(lesson for lesson in lessons if lesson.taught_on == on)
        return CalendarDay(
            on=on,
            inside_month=on.month == month,
            is_today=on == today,
            lessons=todays,
            holiday=public.get(on),
            vacations=tuple(school.get(on, [])),
            summary=self._summary(todays, names),
        )

    @staticmethod
    def _summary(lessons: tuple[Lesson, ...], names: dict[int, str]) -> str:
        states = {"done": "erledigt", "cancelled": "ausgefallen"}
        pieces = []
        for lesson in lessons:
            clock = f"{lesson.starts_at:%H:%M} " if lesson.starts_at else ""
            state = states.get(lesson.status.value)
            extra = f", {state}" if state else ""
            pieces.append(
                f"{clock}{names.get(lesson.customer_id, '?')} "
                f"({german_formatter.format_quantity(lesson.quantity)} h{extra})"
            )
        return "\n".join(pieces)

    def _holiday_notes(
        self, first: date, last: date
    ) -> tuple[dict[date, str], dict[date, list[tuple[str, str]]]]:
        settings = self._store.app_settings()
        states = HolidayCalendar.chosen_states(settings)
        if not states:
            return {}, {}
        public = (
            HolidayCalendar.public_holidays(states, first, last)
            if settings.show_public_holidays
            else {}
        )
        school = (
            HolidayCalendar(self._session).school_holidays(states, first, last)
            if settings.show_school_holidays
            else {}
        )
        return public, school

    def _school_states(self) -> list[str]:
        settings = self._store.app_settings()
        if not settings.show_school_holidays:
            return []
        return HolidayCalendar.chosen_states(settings)

    def _lessons_between(self, first: date, last: date) -> list[Lesson]:
        statement = (
            select(Lesson)
            .where(Lesson.taught_on >= first)
            .where(Lesson.taught_on <= last)
            .order_by(col(Lesson.taught_on), col(Lesson.starts_at))
        )
        return list(self._session.exec(statement).all())

    def _open_lessons_before(self, day: date) -> list[Lesson]:
        statement = (
            select(Lesson)
            .where(Lesson.status == LessonStatus.PLANNED)
            .where(Lesson.taught_on < day)
            .order_by(col(Lesson.taught_on))
        )
        return list(self._session.exec(statement).all())

    def _lesson_extras(
        self, lessons: list[Lesson]
    ) -> dict[int, list[dict[str, object]]]:
        """Per lesson: which extra costs apply, what they add, what is switchable."""
        customer_ids = list({lesson.customer_id for lesson in lessons})
        if not customer_ids:
            return {}
        terms_map = billing_templates_by_customer(self._session, customer_ids)
        found: dict[int, list[dict[str, object]]] = {}
        for lesson in lessons:
            terms = terms_map.get(lesson.customer_id)
            if terms is None:
                continue
            shares = StoredLessonPricer(terms).priced_columns(lesson)
            if not shares:
                continue
            found[lesson.id or 0] = [
                {
                    "label": column.label,
                    "active": value is not None,
                    "amount": (
                        german_formatter.format_euro(contribution)
                        if contribution > 0
                        else ""
                    ),
                    "toggleable": column.source is ValueSource.PER_LESSON,
                }
                for column, value, contribution in shares
            ]
        return found
