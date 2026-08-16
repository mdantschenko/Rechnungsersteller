from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine
from sqlmodel import Session, select

from invoicing.alarms import LessonAlarmClock
from invoicing.constant import ALARM_RING_EVERY, ALARM_RINGS_AT_MOST
from invoicing.storage.models import (
    AppSettings,
    Customer,
    Lesson,
    LessonAlarm,
    LessonStatus,
)

LESSON_DAY = date(2026, 6, 17)
LESSON_START = time(15, 0)
RING_MOMENT = datetime(2026, 6, 17, 14, 0)


@pytest.fixture
def session(engine: Engine):
    with Session(engine) as inside:
        yield inside


@pytest.fixture
def settings() -> AppSettings:
    return AppSettings(password_hash="egal", session_secret="egal", reminder_minutes=60)


def _lesson(
    session: Session,
    starts_at: time | None = LESSON_START,
    reminder_at: time | None = None,
    status: LessonStatus = LessonStatus.PLANNED,
) -> Lesson:
    customer = Customer(
        name="Erika Beispiel",
        street="Beispielstraße 21",
        city="54321 Beispielstadt",
        student_name="Max",
        reminder_at=reminder_at,
    )
    session.add(customer)
    session.flush()
    lesson = Lesson(
        customer_id=customer.id or 0,
        taught_on=LESSON_DAY,
        starts_at=starts_at,
        quantity=Decimal(1),
        status=status,
    )
    session.add(lesson)
    session.flush()
    return lesson


def test_rings_at_the_lead_time_and_names_the_lesson(
    session: Session, settings: AppSettings
) -> None:
    _lesson(session)
    rung: list[dict[str, str]] = []
    clock = LessonAlarmClock(session, settings, rung.append)

    assert clock.ring_all_due(RING_MOMENT - timedelta(minutes=1)) == 0
    assert clock.ring_all_due(RING_MOMENT) == 1

    assert rung[0]["title"] == "Nachhilfe Max"
    assert "um 15:00" in rung[0]["body"]
    assert "Beispielstraße 21" in rung[0]["body"]
    assert rung[0]["url"] == f"/tag/{LESSON_DAY}"


def test_the_customer_clock_time_wins(session: Session, settings: AppSettings) -> None:
    _lesson(session, reminder_at=time(8, 30))
    rung: list[dict[str, str]] = []
    clock = LessonAlarmClock(session, settings, rung.append)

    assert clock.ring_all_due(datetime(2026, 6, 17, 8, 29)) == 0
    assert clock.ring_all_due(datetime(2026, 6, 17, 8, 30)) == 1


def test_an_untimed_lesson_stays_quiet(session: Session, settings: AppSettings) -> None:
    _lesson(session, starts_at=None)
    clock = LessonAlarmClock(session, settings, lambda message: 1)

    assert clock.ring_all_due(RING_MOMENT) == 0


def test_an_answered_lesson_stays_quiet(
    session: Session, settings: AppSettings
) -> None:
    _lesson(session, status=LessonStatus.DONE)
    clock = LessonAlarmClock(session, settings, lambda message: 1)

    assert clock.ring_all_due(RING_MOMENT) == 0


def test_it_keeps_ringing_until_acknowledged(
    session: Session, settings: AppSettings
) -> None:
    _lesson(session)
    rung: list[dict[str, str]] = []
    clock = LessonAlarmClock(session, settings, rung.append)

    clock.ring_all_due(RING_MOMENT)
    clock.ring_all_due(RING_MOMENT + timedelta(seconds=30))
    assert len(rung) == 1

    clock.ring_all_due(RING_MOMENT + ALARM_RING_EVERY)
    assert len(rung) == 2
    assert rung[1]["body"].startswith("2. Weckruf")

    clock.acknowledge_day(LESSON_DAY)
    clock.ring_all_due(RING_MOMENT + 2 * ALARM_RING_EVERY)
    assert len(rung) == 2


def test_a_ring_that_reached_nobody_does_not_use_up_the_alarm(
    session: Session, settings: AppSettings
) -> None:
    _lesson(session)
    clock = LessonAlarmClock(session, settings, lambda message: 0)

    assert clock.ring_all_due(RING_MOMENT) == 1

    alarm = session.exec(select(LessonAlarm)).one()
    assert alarm.rings == 0
    assert alarm.last_rung_at == RING_MOMENT


def test_a_ring_that_reached_a_device_counts(
    session: Session, settings: AppSettings
) -> None:
    _lesson(session)
    clock = LessonAlarmClock(session, settings, lambda message: 2)

    clock.ring_all_due(RING_MOMENT)

    alarm = session.exec(select(LessonAlarm)).one()
    assert alarm.rings == 1
    assert alarm.last_rung_at == RING_MOMENT


def test_the_ringing_gives_up_eventually(
    session: Session, settings: AppSettings
) -> None:
    _lesson(session)
    rung: list[dict[str, str]] = []
    clock = LessonAlarmClock(session, settings, rung.append)

    moment = RING_MOMENT
    for _ in range(ALARM_RINGS_AT_MOST + 3):
        clock.ring_all_due(moment)
        moment += ALARM_RING_EVERY

    assert len(rung) == ALARM_RINGS_AT_MOST


def test_a_long_missed_alarm_stays_quiet(
    session: Session, settings: AppSettings
) -> None:
    _lesson(session)
    clock = LessonAlarmClock(session, settings, lambda message: 1)

    assert clock.ring_all_due(RING_MOMENT + timedelta(hours=2)) == 0
    assert session.exec(select(LessonAlarm)).first() is None
