"""A month calendar, and the day behind each of its cells.

The grid itself comes from the standard library and the German month and
weekday names from Babel, so nothing here reimplements a calendar.

Opening a month writes out the recurring lessons up to its end, which is what
lets you page forward and still see what is planned.
"""

from __future__ import annotations

from calendar import Calendar
from datetime import date, timedelta

from babel.dates import format_date
from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, col, select
from starlette.responses import Response

from invoicing import alarms, feiertage
from invoicing.billing import priced_columns
from invoicing.constant import (
    FEDERAL_STATE_COLORS,
    GERMAN_LOCALE,
    WEEK_STARTS_ON_MONDAY,
    ValueSource,
)
from invoicing.data_classes import CalendarDay
from invoicing.domain.money import format_euro, format_quantity
from invoicing.scheduling import materialise_series
from invoicing.storage.models import Customer, Lesson, LessonStatus
from invoicing.utils import billing_templates_by_customer, planning_horizon
from invoicing.web.page import (
    active_customers,
    database,
    series_labels,
    settings_of,
    templates,
)

router = APIRouter()


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
    today = date.today()
    monday = on - timedelta(days=on.weekday())
    sunday = monday + timedelta(days=6)
    horizon = planning_horizon(settings_of(session), today)
    materialise_series(session, until=max(sunday, horizon))
    session.flush()
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
            "colors": FEDERAL_STATE_COLORS,
            "back": f"/woche/{monday}",
        },
    )


@router.get("/tag/{on}")
def a_day(on: date, request: Request, session: Session = Depends(database)) -> Response:
    alarms.acknowledge_day(session, on)
    public, school = _holiday_notes(session, on, on)
    lessons = _lessons_between(session, on, on)
    return templates.TemplateResponse(
        request,
        "day.html",
        {
            "on": on,
            "heading": format_date(on, "EEEE, d. MMMM y", locale=GERMAN_LOCALE),
            "previous": on - timedelta(days=1),
            "next": on + timedelta(days=1),
            "today": date.today(),
            "lessons": lessons,
            "names": _customer_names(session),
            "places": _lesson_places(session),
            "extras": _lesson_extras(session, lessons),
            "series": series_labels(session),
            "customers": active_customers(session),
            "holiday": public.get(on),
            "vacations": school.get(on, []),
            "colors": FEDERAL_STATE_COLORS,
            "back": f"/tag/{on}",
        },
    )


def _week_heading(monday: date, sunday: date) -> str:
    if monday.month == sunday.month:
        return (
            f"{monday.day}.–{sunday.day}. {format_date(monday, 'LLLL', GERMAN_LOCALE)}"
        )
    return (
        f"{format_date(monday, 'd. MMM', GERMAN_LOCALE)} – "
        f"{format_date(sunday, 'd. MMM y', GERMAN_LOCALE)}"
    )


def _month_page(request: Request, session: Session, year: int, month: int) -> Response:
    today = date.today()
    first_of_month = date(year, month, 1)
    weeks = Calendar(WEEK_STARTS_ON_MONDAY).monthdatescalendar(year, month)
    horizon = planning_horizon(settings_of(session), today)
    materialise_series(session, until=max(weeks[-1][-1], horizon))
    session.flush()
    lessons = _lessons_between(session, weeks[0][0], weeks[-1][-1])
    public, school = _holiday_notes(session, weeks[0][0], weeks[-1][-1])
    names = _customer_names(session)
    return templates.TemplateResponse(
        request,
        "calendar.html",
        {
            "heading": format_date(first_of_month, "LLLL y", locale=GERMAN_LOCALE),
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
            "colors": FEDERAL_STATE_COLORS,
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
        clock = f"{lesson.starts_at:%H:%M} " if lesson.starts_at else ""
        state = states.get(lesson.status.value)
        extra = f", {state}" if state else ""
        pieces.append(
            f"{clock}{names.get(lesson.customer_id, '?')} "
            f"({format_quantity(lesson.quantity)} h{extra})"
        )
    return "\n".join(pieces)


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


def _customer_names(session: Session) -> dict[int, str]:
    """The pupil's name where one is set; the calendar is about the child."""
    return {
        customer.id or 0: customer.pupil_name
        for customer in session.exec(select(Customer)).all()
    }


def _lesson_extras(
    session: Session, lessons: list[Lesson]
) -> dict[int, list[dict[str, object]]]:
    """Per lesson: which extra costs apply, what they add, what is switchable."""
    customer_ids = list({lesson.customer_id for lesson in lessons})
    if not customer_ids:
        return {}
    terms_map = billing_templates_by_customer(session, customer_ids)
    found: dict[int, list[dict[str, object]]] = {}
    for lesson in lessons:
        terms = terms_map.get(lesson.customer_id)
        if terms is None:
            continue
        shares = priced_columns(terms, lesson)
        if not shares:
            continue
        found[lesson.id or 0] = [
            {
                "label": column.label,
                "active": value is not None,
                "amount": format_euro(contribution) if contribution > 0 else "",
                "toggleable": column.source is ValueSource.PER_LESSON,
            }
            for column, value, contribution in shares
        ]
    return found


def _lesson_places(session: Session) -> dict[int, str]:
    """What to print under the name: the lesson address, or Online."""
    return {
        customer.id or 0: customer.lesson_place
        for customer in session.exec(select(Customer)).all()
    }


def _weekday_names() -> list[str]:
    monday = date(2024, 1, 1)
    return [
        format_date(monday + timedelta(days=offset), "EEEEEE", locale=GERMAN_LOCALE)
        for offset in range(7)
    ]
