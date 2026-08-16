"""The one place that changes a lesson after it was written down."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlmodel import Session, select

from invoicing.constant import ValueSource
from invoicing.storage.models import BillingTemplate, Lesson, LessonStatus
from invoicing.utils import parse_optional_clock_time


class LessonEditor:
    """Answers, moves, resizes, removes and adds single lessons."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def set_extra_costs(self, lesson_id: int, aktiv: list[str]) -> None:
        """Tick the extra costs that apply to this one lesson.

        Only "je Termin" columns can be switched here; an unticked one is
        stored as an explicit "nothing", which prints the placeholder on the
        invoice and adds nothing to the total.
        """
        lesson = self._lesson(lesson_id)
        if lesson.invoice_id is not None:
            return
        terms = self._session.exec(
            select(BillingTemplate).where(
                BillingTemplate.customer_id == lesson.customer_id
            )
        ).first()
        if terms is None:
            return
        values = dict(lesson.column_values)
        for column in terms.columns:
            if column.source is not ValueSource.PER_LESSON:
                continue
            if column.label in aktiv:
                values.pop(column.label, None)
            else:
                values[column.label] = None
        lesson.column_values = values
        self._session.add(lesson)

    def mark_done(self, lesson_id: int) -> None:
        self._lesson(lesson_id).status = LessonStatus.DONE

    def mark_cancelled(self, lesson_id: int) -> None:
        self._lesson(lesson_id).status = LessonStatus.CANCELLED

    def mark_planned(self, lesson_id: int) -> None:
        """Undo an answer that was given by mistake."""
        self._lesson(lesson_id).status = LessonStatus.PLANNED

    def reschedule(self, lesson_id: int, taught_on: date, starts_at: str) -> None:
        lesson = self._lesson(lesson_id)
        lesson.taught_on = taught_on
        new_start = parse_optional_clock_time(starts_at)
        if new_start is not None:
            lesson.starts_at = new_start

    def change_quantity(self, lesson_id: int, quantity: Decimal) -> None:
        self._lesson(lesson_id).quantity = quantity

    def remove(self, lesson_id: int) -> None:
        """Delete a lesson that should never have existed.

        Refused once the lesson has been billed, because the invoice would
        then name a lesson that is no longer there.

        Raises:
            ValueError: if the lesson is already on an invoice.
        """
        lesson = self._lesson(lesson_id)
        if lesson.invoice_id is not None:
            raise ValueError(f"lesson {lesson_id} is already on an invoice")
        self._session.delete(lesson)

    def add(
        self, customer_id: int, taught_on: date, quantity: Decimal, starts_at: str
    ) -> None:
        self._session.add(
            Lesson(
                customer_id=customer_id,
                taught_on=taught_on,
                quantity=quantity,
                starts_at=parse_optional_clock_time(starts_at),
            )
        )

    def _lesson(self, lesson_id: int) -> Lesson:
        lesson = self._session.get(Lesson, lesson_id)
        if lesson is None:
            raise ValueError(f"no lesson with id {lesson_id}")
        self._session.add(lesson)
        return lesson
