"""Turning a recurring series into the individual lessons it stands for.

Lessons are written out rather than computed on demand, because each one can
be moved, shortened or called off on its own once it exists. The recurrence
rule says when a lesson should happen; the row says what actually did.
"""

from __future__ import annotations

from datetime import date, datetime, time

from dateutil.rrule import rrulestr
from sqlmodel import Session, col, select

from invoicing.storage.models import Lesson, LessonSeries, LessonStatus


class LessonSeriesMaterialiser:
    """Writes the recurring series out as individual lesson rows."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def materialise_all_active(self, until: date) -> tuple[Lesson, ...]:
        """Create every lesson the active series call for, up to and including
        ``until``, and return the ones that were newly created."""
        created: list[Lesson] = []
        for series in self._session.exec(
            select(LessonSeries).where(col(LessonSeries.active))
        ).all():
            created.extend(self._materialise_one(series, until))
        return tuple(created)

    def unanswered_before(self, day: date) -> tuple[Lesson, ...]:
        """Lessons that were due before ``day`` and still wait for an answer."""
        statement = (
            select(Lesson)
            .where(Lesson.taught_on < day)
            .where(Lesson.status == LessonStatus.PLANNED)
        )
        return tuple(self._session.exec(statement).all())

    def _materialise_one(self, series: LessonSeries, until: date) -> list[Lesson]:
        already_there = self._dates_already_written(series)
        created: list[Lesson] = []
        for occurrence in self._occurrences(series, until):
            if occurrence in already_there:
                continue
            lesson = Lesson(
                customer_id=series.customer_id,
                series_id=series.id,
                taught_on=occurrence,
                starts_at=series.starts_at,
                quantity=series.quantity,
                status=LessonStatus.PLANNED,
            )
            self._session.add(lesson)
            created.append(lesson)
        return created

    def _dates_already_written(self, series: LessonSeries) -> set[date]:
        statement = select(col(Lesson.taught_on)).where(Lesson.series_id == series.id)
        return set(self._session.exec(statement).all())

    @staticmethod
    def _occurrences(series: LessonSeries, until: date) -> list[date]:
        last_day = min(until, series.ends_on) if series.ends_on else until
        if last_day < series.starts_on:
            return []
        start = datetime.combine(series.starts_on, series.starts_at or time.min)
        rule = rrulestr(series.recurrence, dtstart=start)
        return [
            moment.date()
            for moment in rule.between(
                start, datetime.combine(last_day, time.max), inc=True
            )
        ]
