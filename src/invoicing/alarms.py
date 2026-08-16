"""The wake-up calls behind the lessons.

A planned lesson rings at its reminder time — the customer's clock time on
the lesson day, or the global lead before the start — and keeps ringing
every few minutes until someone opens the lesson's day. A server that was
asleep at alarm time still rings when it wakes, but an alarm older than an
hour stays quiet instead of startling anyone at night.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlmodel import Session, col, select

from invoicing.constant import (
    ALARM_CATCH_UP_WINDOW,
    ALARM_RING_EVERY,
    ALARM_RINGS_AT_MOST,
    DeliverPushMessage,
)
from invoicing.storage.models import (
    AppSettings,
    Customer,
    Lesson,
    LessonAlarm,
    LessonStatus,
)


class LessonAlarmClock:
    """Rings the lesson reminders through the given deliverer."""

    def __init__(
        self, session: Session, settings: AppSettings, deliver: DeliverPushMessage
    ) -> None:
        self._session = session
        self._settings = settings
        self._deliver = deliver

    @staticmethod
    def ring_time_for(
        lesson: Lesson, customer: Customer, reminder_minutes: int
    ) -> datetime | None:
        """When this lesson's alarm goes off, or None for an untimed lesson."""
        if customer.reminder_at is not None:
            return datetime.combine(lesson.taught_on, customer.reminder_at)
        if lesson.starts_at is None:
            return None
        begin = datetime.combine(lesson.taught_on, lesson.starts_at)
        return begin - timedelta(minutes=reminder_minutes)

    def ring_all_due(self, now: datetime) -> int:
        """Ring every lesson whose time has come, and return how often it rang."""
        rung = 0
        for lesson, customer in self._planned_lessons_today_and_tomorrow(now):
            moment = self.ring_time_for(
                lesson, customer, self._settings.reminder_minutes
            )
            if moment is None or now < moment:
                continue
            alarm = self._session.exec(
                select(LessonAlarm).where(LessonAlarm.lesson_id == lesson.id)
            ).first()
            if alarm is None:
                if now > moment + ALARM_CATCH_UP_WINDOW:
                    continue
                alarm = LessonAlarm(lesson_id=lesson.id or 0)
            if alarm.acknowledged or alarm.rings >= ALARM_RINGS_AT_MOST:
                continue
            if (
                alarm.last_rung_at is not None
                and now < alarm.last_rung_at + ALARM_RING_EVERY
            ):
                continue
            self._deliver(self._wake_up_message(lesson, customer, alarm.rings + 1))
            alarm.rings += 1
            alarm.last_rung_at = now
            self._session.add(alarm)
            rung += 1
        return rung

    def acknowledge_day(self, day: date) -> None:
        """Opening a day answers its alarms; the ringing stops."""
        lessons = select(Lesson.id).where(Lesson.taught_on == day)
        alarms = select(LessonAlarm).where(col(LessonAlarm.lesson_id).in_(lessons))
        for alarm in self._session.exec(alarms).all():
            alarm.acknowledged = True
            self._session.add(alarm)

    def _planned_lessons_today_and_tomorrow(
        self, now: datetime
    ) -> list[tuple[Lesson, Customer]]:
        today = now.date()
        rows = self._session.exec(
            select(Lesson, Customer)
            .where(Lesson.customer_id == Customer.id)
            .where(Lesson.status == LessonStatus.PLANNED)
            .where(col(Lesson.taught_on).between(today, today + timedelta(days=1)))
        ).all()
        return list(rows)

    @staticmethod
    def _wake_up_message(
        lesson: Lesson, customer: Customer, ring: int
    ) -> dict[str, str]:
        pieces = []
        if ring > 1:
            pieces.append(f"{ring}. Weckruf")
        if lesson.starts_at is not None:
            pieces.append(f"um {lesson.starts_at:%H:%M}")
        pieces.append(customer.lesson_place)
        return {
            "title": f"Nachhilfe {customer.pupil_name}",
            "body": " · ".join(pieces),
            "tag": f"termin-{lesson.id}",
            "url": f"/tag/{lesson.taught_on}",
        }
