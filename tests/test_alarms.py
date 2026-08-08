from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine
from sqlmodel import Session, select

from invoicing.alarms import RING_EVERY, RINGS_AT_MOST, acknowledge_day, ring_due
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

    assert (
        ring_due(session, settings, RING_MOMENT - timedelta(minutes=1), rung.append)
        == 0
    )
    assert ring_due(session, settings, RING_MOMENT, rung.append) == 1

    assert rung[0]["title"] == "Nachhilfe Max"
    assert "um 15:00" in rung[0]["body"]
    assert "Beispielstraße 21" in rung[0]["body"]
    assert rung[0]["url"] == f"/tag/{LESSON_DAY}"


def test_the_customer_clock_time_wins(session: Session, settings: AppSettings) -> None:
    _lesson(session, reminder_at=time(8, 30))
    rung: list[dict[str, str]] = []

    assert ring_due(session, settings, datetime(2026, 6, 17, 8, 29), rung.append) == 0
    assert ring_due(session, settings, datetime(2026, 6, 17, 8, 30), rung.append) == 1


def test_an_untimed_lesson_stays_quiet(session: Session, settings: AppSettings) -> None:
    _lesson(session, starts_at=None)

    assert ring_due(session, settings, RING_MOMENT, lambda m: 1) == 0


def test_an_answered_lesson_stays_quiet(
    session: Session, settings: AppSettings
) -> None:
    _lesson(session, status=LessonStatus.DONE)

    assert ring_due(session, settings, RING_MOMENT, lambda m: 1) == 0


def test_it_keeps_ringing_until_acknowledged(
    session: Session, settings: AppSettings
) -> None:
    _lesson(session)
    rung: list[dict[str, str]] = []

    ring_due(session, settings, RING_MOMENT, rung.append)
    ring_due(session, settings, RING_MOMENT + timedelta(seconds=30), rung.append)
    assert len(rung) == 1

    ring_due(session, settings, RING_MOMENT + RING_EVERY, rung.append)
    assert len(rung) == 2
    assert rung[1]["body"].startswith("2. Weckruf")

    acknowledge_day(session, LESSON_DAY)
    ring_due(session, settings, RING_MOMENT + 2 * RING_EVERY, rung.append)
    assert len(rung) == 2


def test_the_ringing_gives_up_eventually(
    session: Session, settings: AppSettings
) -> None:
    _lesson(session)
    rung: list[dict[str, str]] = []

    moment = RING_MOMENT
    for _ in range(RINGS_AT_MOST + 3):
        ring_due(session, settings, moment, rung.append)
        moment += RING_EVERY

    assert len(rung) == RINGS_AT_MOST


def test_a_long_missed_alarm_stays_quiet(
    session: Session, settings: AppSettings
) -> None:
    _lesson(session)

    assert (
        ring_due(session, settings, RING_MOMENT + timedelta(hours=2), lambda m: 1) == 0
    )
    assert session.exec(select(LessonAlarm)).first() is None
