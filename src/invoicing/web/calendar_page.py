"""A month calendar, and the day behind each of its cells.

The grid itself comes from the standard library and the German month and
weekday names from Babel, so nothing here reimplements a calendar.

Opening a month writes out the recurring lessons up to its end, which is what
lets you page forward and still see what is planned.
"""

from __future__ import annotations

from calendar import Calendar
from dataclasses import dataclass
from datetime import date, timedelta

from babel.dates import format_date
from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, col, select
from starlette.responses import Response

from invoicing import feiertage
from invoicing.billing import stored_columns, typed_values
from invoicing.domain.columns import ValueSource
from invoicing.domain.money import format_euro, format_quantity
from invoicing.scheduling import materialise_series
from invoicing.storage.models import (
    BillingTemplate,
    Customer,
    CustomerStatus,
    Lesson,
    LessonStatus,
)
from invoicing.web.page import database, series_labels, settings_of, templates

router = APIRouter()

GERMAN = "de_DE"
WEEK_STARTS_ON_MONDAY = 0


@dataclass(frozen=True, slots=True)
class CalendarDay:
    """One cell of the grid."""

    on: date
    inside_month: bool
    is_today: bool
    lessons: tuple[Lesson, ...]
    holiday: str | None = None
    vacations: tuple[tuple[str, str], ...] = ()
    """(state, name) pairs, one per federal state on holiday that day."""
    summary: str = ""
    """One line naming the day's lessons, for the long-press peek."""

    @property
    def peek(self) -> str:
        """What the long press shows: holidays first, then the lessons."""
        parts = [self.holiday] if self.holiday else []
        parts.extend(f"{name} ({state})" for state, name in self.vacations)
        if self.summary:
            parts.append(self.summary)
        return " · ".join(parts)


@router.get("/")
def this_week(request: Request, session: Session = Depends(database)) -> Response:
    """The start screen is the current week: that is where the work happens."""
    return _week_page(request, session, date.today())


@router.get("/kalender/{year}/{month}")
def a_month(
    year: int, month: int, request: Request, session: Session = Depends(database)
) -> Response:
    return _month_page(request, session, year, month)


@router.get("/woche/{on}")
def a_week(
    on: date, request: Request, session: Session = Depends(database)
) -> Response:
    return _week_page(request, session, on)


def _week_page(request: Request, session: Session, on: date) -> Response:
    monday = on - timedelta(days=on.weekday())
    sunday = monday + timedelta(days=6)
    materialise_series(session, until=max(sunday, _horizon_end(session)))
    session.flush()

    today = date.today()
    lessons = _lessons_between(session, monday, sunday)
    public, school = _holiday_notes(session, monday, sunday)
    names = _customer_names(session)
    return templates.TemplateResponse(
        request,
        "week.html",
        {
            "heading": _week_heading(monday, sunday),
            "monday": monday,
            "days": [
                _cell(
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
            "places": _lesson_places(session),
            "extras": _lesson_extras(session, lessons),
            "series": series_labels(session),
            "overdue": _open_lessons_before(session, today),
            "colors": feiertage.STATE_COLORS,
            "back": f"/woche/{monday}",
        },
    )


@router.get("/tag/{on}")
def a_day(on: date, request: Request, session: Session = Depends(database)) -> Response:
    public, school = _holiday_notes(session, on, on)
    lessons = _lessons_between(session, on, on)
    return templates.TemplateResponse(
        request,
        "day.html",
        {
            "on": on,
            "heading": format_date(on, "EEEE, d. MMMM y", locale=GERMAN),
            "previous": on - timedelta(days=1),
            "next": on + timedelta(days=1),
            "today": date.today(),
            "lessons": lessons,
            "names": _customer_names(session),
            "places": _lesson_places(session),
            "extras": _lesson_extras(session, lessons),
            "series": series_labels(session),
            "customers": _active_customers(session),
            "holiday": public.get(on),
            "vacations": school.get(on, []),
            "colors": feiertage.STATE_COLORS,
            "back": f"/tag/{on}",
        },
    )


def _week_heading(monday: date, sunday: date) -> str:
    if monday.month == sunday.month:
        return f"{monday.day}.–{sunday.day}. {format_date(monday, 'LLLL', GERMAN)}"
    return (
        f"{format_date(monday, 'd. MMM', GERMAN)} – "
        f"{format_date(sunday, 'd. MMM y', GERMAN)}"
    )


def _month_page(request: Request, session: Session, year: int, month: int) -> Response:
    first_of_month = date(year, month, 1)
    weeks = Calendar(WEEK_STARTS_ON_MONDAY).monthdatescalendar(year, month)
    materialise_series(session, until=max(weeks[-1][-1], _horizon_end(session)))
    session.flush()

    today = date.today()
    lessons = _lessons_between(session, weeks[0][0], weeks[-1][-1])
    public, school = _holiday_notes(session, weeks[0][0], weeks[-1][-1])
    names = _customer_names(session)
    return templates.TemplateResponse(
        request,
        "calendar.html",
        {
            "heading": format_date(first_of_month, "LLLL y", locale=GERMAN),
            "weekday_names": _weekday_names(),
            "weeks": [
                [
                    _cell(day, month, today, lessons, public, school, names)
                    for day in week
                ]
                for week in weeks
            ],
            "previous": first_of_month - timedelta(days=1),
            "next": first_of_month + relativedelta(months=1),
            "today": today,
            "reference": today if today.month == month else first_of_month,
            "names": names,
            "colors": feiertage.STATE_COLORS,
            "school_states": _school_states(session),
            "overdue": [
                lesson
                for lesson in _open_lessons_before(session, today)
                if lesson.taught_on < today
            ],
        },
    )


def _cell(
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
        summary=_summary(todays, names),
    )


def _summary(lessons: tuple[Lesson, ...], names: dict[int, str]) -> str:
    states = {"done": "erledigt", "cancelled": "ausgefallen"}
    pieces = []
    for lesson in lessons:
        clock = (
            f"{lesson.starts_at.hour:02d}:{lesson.starts_at.minute:02d} "
            if lesson.starts_at
            else ""
        )
        state = states.get(lesson.status.value)
        extra = f", {state}" if state else ""
        pieces.append(
            f"{clock}{names.get(lesson.customer_id, '?')} "
            f"({format_quantity(lesson.quantity)} h{extra})"
        )
    return " · ".join(pieces)


def _holiday_notes(
    session: Session, first: date, last: date
) -> tuple[dict[date, str], dict[date, list[tuple[str, str]]]]:
    settings = settings_of(session)
    states = feiertage.chosen_states(settings)
    if not states:
        return {}, {}
    public = (
        feiertage.public_holidays(states, first, last)
        if settings.show_public_holidays
        else {}
    )
    school = (
        feiertage.school_holidays(session, states, first, last)
        if settings.show_school_holidays
        else {}
    )
    return public, school


def _school_states(session: Session) -> list[str]:
    settings = settings_of(session)
    if not settings.show_school_holidays:
        return []
    return feiertage.chosen_states(settings)


def _lessons_between(session: Session, first: date, last: date) -> list[Lesson]:
    statement = (
        select(Lesson)
        .where(Lesson.taught_on >= first)
        .where(Lesson.taught_on <= last)
        .order_by(col(Lesson.taught_on), col(Lesson.starts_at))
    )
    return list(session.exec(statement).all())


def _open_lessons_before(session: Session, day: date) -> list[Lesson]:
    statement = (
        select(Lesson)
        .where(Lesson.status == LessonStatus.PLANNED)
        .where(Lesson.taught_on < day)
        .order_by(col(Lesson.taught_on))
    )
    return list(session.exec(statement).all())


def _active_customers(session: Session) -> list[Customer]:
    statement = (
        select(Customer)
        .where(Customer.status == CustomerStatus.ACTIVE)
        .order_by(col(Customer.name))
    )
    return list(session.exec(statement).all())


def _customer_names(session: Session) -> dict[int, str]:
    """The pupil's name where one is set; the calendar is about the child."""
    return {
        customer.id or 0: customer.student_name or customer.name
        for customer in session.exec(select(Customer)).all()
    }


def _lesson_extras(
    session: Session, lessons: list[Lesson]
) -> dict[int, list[dict[str, object]]]:
    """Per lesson: which extra costs apply, what they add, what is switchable."""
    customer_ids = list({lesson.customer_id for lesson in lessons})
    if not customer_ids:
        return {}
    terms_map = {
        terms.customer_id: terms
        for terms in session.exec(
            select(BillingTemplate).where(
                col(BillingTemplate.customer_id).in_(customer_ids)
            )
        ).all()
    }
    found: dict[int, list[dict[str, object]]] = {}
    for lesson in lessons:
        terms = terms_map.get(lesson.customer_id)
        if terms is None:
            continue
        columns = stored_columns(terms)
        if not columns:
            continue
        kinds = {column.label: column.kind for column in columns}
        values = typed_values(kinds, lesson.column_values)
        entries: list[dict[str, object]] = []
        for column in columns:
            value = column.value_for(values)
            contribution = column.contribution(value, lesson.quantity)
            entries.append(
                {
                    "label": column.label,
                    "active": value is not None,
                    "amount": format_euro(contribution) if contribution > 0 else "",
                    "toggleable": column.source is ValueSource.PER_LESSON,
                }
            )
        found[lesson.id or 0] = entries
    return found


def _lesson_places(session: Session) -> dict[int, str]:
    """What to print under the name: the lesson address, or Online."""
    places: dict[int, str] = {}
    for customer in session.exec(select(Customer)).all():
        if customer.online:
            places[customer.id or 0] = "Online"
        else:
            places[customer.id or 0] = customer.lesson_address or (
                f"{customer.street}, {customer.city}"
            )
    return places


def _weekday_names() -> list[str]:
    monday = date(2024, 1, 1)
    return [
        format_date(monday + timedelta(days=offset), "EEEEEE", locale=GERMAN)
        for offset in range(7)
    ]


def _horizon_end(session: Session) -> date:
    return date.today() + timedelta(days=settings_of(session).lesson_horizon_days)
