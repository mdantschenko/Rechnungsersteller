"""The lessons as an iCalendar feed the phone subscribes to.

Subscribing once in the calendar app is what turns lessons into real
notifications: the phone itself rings before each lesson, with the lead
time set on the settings screen. A calendar app cannot sign in, so the
feed URL carries a secret token instead of the session cookie.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, col, select
from starlette.responses import PlainTextResponse

from invoicing.scheduling import materialise_series
from invoicing.storage.models import AppSettings, Customer, Lesson, LessonStatus
from invoicing.web.page import database, settings_of

router = APIRouter()

LOOKBACK_DAYS = 14


@router.get("/kalender.ics")
def calendar_feed(
    schluessel: str = Query(""), session: Session = Depends(database)
) -> PlainTextResponse:
    settings = settings_of(session)
    if not settings.calendar_token or schluessel != settings.calendar_token:
        raise HTTPException(status_code=404)
    today = date.today()
    horizon = today + timedelta(days=settings.lesson_horizon_days)
    materialise_series(session, until=horizon)
    session.flush()
    return PlainTextResponse(
        _calendar(session, settings, today), media_type="text/calendar; charset=utf-8"
    )


def _calendar(session: Session, settings: AppSettings, today: date) -> str:
    customers = {
        customer.id: customer for customer in session.exec(select(Customer)).all()
    }
    lessons = session.exec(
        select(Lesson)
        .where(Lesson.taught_on >= today - timedelta(days=LOOKBACK_DAYS))
        .where(Lesson.status != LessonStatus.CANCELLED)
        .order_by(col(Lesson.taught_on))
    ).all()
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Rechnungsersteller//DE",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:Nachhilfe",
    ]
    for lesson in lessons:
        customer = customers.get(lesson.customer_id)
        if customer is None:
            continue
        lines.extend(_event(lesson, customer, settings.reminder_minutes))
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _event(lesson: Lesson, customer: Customer, reminder_minutes: int) -> list[str]:
    title = f"Nachhilfe {customer.student_name or customer.name}"
    if customer.online:
        place = "Online"
    else:
        place = customer.lesson_address or f"{customer.street}, {customer.city}"
    lines = [
        "BEGIN:VEVENT",
        f"UID:termin-{lesson.id}@rechnungsersteller",
        f"DTSTAMP:{datetime.now():%Y%m%dT%H%M%SZ}",
        f"SUMMARY:{_escaped(title)} ({_hours(lesson)} h)",
        f"LOCATION:{_escaped(place)}",
    ]
    if lesson.starts_at is None:
        lines.append(f"DTSTART;VALUE=DATE:{lesson.taught_on:%Y%m%d}")
    else:
        begin = datetime.combine(lesson.taught_on, lesson.starts_at)
        end = begin + timedelta(hours=float(lesson.quantity))
        lines.append(f"DTSTART:{begin:%Y%m%dT%H%M%S}")
        lines.append(f"DTEND:{end:%Y%m%dT%H%M%S}")
    lines.extend(
        [
            "BEGIN:VALARM",
            f"TRIGGER:{_trigger(lesson, customer, reminder_minutes)}",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_escaped(title)}",
            "END:VALARM",
            "END:VEVENT",
        ]
    )
    return lines


def _trigger(lesson: Lesson, customer: Customer, reminder_minutes: int) -> str:
    """When the alarm fires, relative to the event start.

    A customer with a clock time gets the alarm at that time on the lesson
    day; everyone else gets the global lead in minutes.
    """
    if customer.reminder_at is None:
        return f"-PT{reminder_minutes}M"
    start = lesson.starts_at
    start_minutes = start.hour * 60 + start.minute if start else 0
    alarm_minutes = customer.reminder_at.hour * 60 + customer.reminder_at.minute
    lead_minutes = start_minutes - alarm_minutes
    if lead_minutes >= 0:
        return f"-PT{lead_minutes}M"
    return f"PT{-lead_minutes}M"


def _hours(lesson: Lesson) -> str:
    return str(lesson.quantity).rstrip("0").rstrip(".")


def _escaped(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")).replace(
        "\n", "\\n"
    )
