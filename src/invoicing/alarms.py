"""The wake-up calls behind the lessons.

A planned lesson rings at its reminder time — the customer's clock time on
the lesson day, or the global lead before the start — and keeps ringing
every few minutes until someone opens the lesson's day. A server that was
asleep at alarm time still rings when it wakes, but an alarm older than an
hour stays quiet instead of startling anyone at night.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta

from sqlmodel import Session, col, select

from invoicing.storage.models import (
    AppSettings,
    Customer,
    Lesson,
    LessonAlarm,
    LessonStatus,
)

RING_EVERY = timedelta(minutes=2)
RINGS_AT_MOST = 8
CATCH_UP = timedelta(hours=1)

Deliver = Callable[[dict[str, str]], object]


def ring_time(
    lesson: Lesson, customer: Customer, reminder_minutes: int
) -> datetime | None:
    """When this lesson's alarm goes off, or None for an untimed lesson."""
    if customer.reminder_at is not None:
        return datetime.combine(lesson.taught_on, customer.reminder_at)
    if lesson.starts_at is None:
        return None
    begin = datetime.combine(lesson.taught_on, lesson.starts_at)
    return begin - timedelta(minutes=reminder_minutes)


def ring_due(
    session: Session, settings: AppSettings, now: datetime, deliver: Deliver
) -> int:
    """Ring every lesson whose time has come, and return how often it rang."""
    rung = 0
    for lesson, customer in _upcoming(session, now):
        moment = ring_time(lesson, customer, settings.reminder_minutes)
        if moment is None or now < moment:
            continue
        alarm = session.exec(
            select(LessonAlarm).where(LessonAlarm.lesson_id == lesson.id)
        ).first()
        if alarm is None:
            if now > moment + CATCH_UP:
                continue
            alarm = LessonAlarm(lesson_id=lesson.id or 0)
        if alarm.acknowledged or alarm.rings >= RINGS_AT_MOST:
            continue
        if alarm.last_rung_at is not None and now < alarm.last_rung_at + RING_EVERY:
            continue
        deliver(_message(lesson, customer, alarm.rings + 1))
        alarm.rings += 1
        alarm.last_rung_at = now
        session.add(alarm)
        rung += 1
    return rung


def acknowledge_day(session: Session, day: date) -> None:
    """Opening a day answers its alarms; the ringing stops."""
    lessons = select(Lesson.id).where(Lesson.taught_on == day)
    alarms = select(LessonAlarm).where(col(LessonAlarm.lesson_id).in_(lessons))
    for alarm in session.exec(alarms).all():
        alarm.acknowledged = True
        session.add(alarm)


def _upcoming(session: Session, now: datetime) -> list[tuple[Lesson, Customer]]:
    today = now.date()
    rows = session.exec(
        select(Lesson, Customer)
        .where(Lesson.customer_id == Customer.id)
        .where(Lesson.status == LessonStatus.PLANNED)
        .where(col(Lesson.taught_on).between(today, today + timedelta(days=1)))
    ).all()
    return list(rows)


def _message(lesson: Lesson, customer: Customer, ring: int) -> dict[str, str]:
    pupil = customer.student_name or customer.name
    if customer.online:
        place = "Online"
    else:
        place = customer.lesson_address or f"{customer.street}, {customer.city}"
    pieces = []
    if ring > 1:
        pieces.append(f"{ring}. Weckruf")
    if lesson.starts_at is not None:
        pieces.append(f"um {lesson.starts_at:%H:%M}")
    pieces.append(place)
    return {
        "title": f"Nachhilfe {pupil}",
        "body": " · ".join(pieces),
        "tag": f"termin-{lesson.id}",
        "url": f"/tag/{lesson.taught_on}",
    }
