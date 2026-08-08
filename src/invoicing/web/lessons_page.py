"""Answering for a lesson: it happened, it did not, it moved, it was shorter.

Every action comes back to the page it was triggered from, so ticking a day
off in the calendar leaves you in the calendar.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from fastapi import APIRouter, Depends, Form
from sqlmodel import Session, select
from starlette.responses import RedirectResponse, Response

from invoicing.domain.columns import ValueSource
from invoicing.storage.models import BillingTemplate, Lesson, LessonStatus
from invoicing.web.page import database

router = APIRouter()


@router.post("/termine/{lesson_id}/zusatz")
def set_extra_costs(
    lesson_id: int,
    back: str = Form("/"),
    aktiv: list[str] = Form([]),
    session: Session = Depends(database),
) -> Response:
    """Tick the extra costs that apply to this one lesson.

    Only "je Termin" columns can be switched here; an unticked one is stored
    as an explicit "nothing", which prints the placeholder on the invoice
    and adds nothing to the total.
    """
    lesson = _lesson(session, lesson_id)
    if lesson.invoice_id is not None:
        return _back_to(back)
    terms = session.exec(
        select(BillingTemplate).where(BillingTemplate.customer_id == lesson.customer_id)
    ).first()
    if terms is None:
        return _back_to(back)
    values = dict(lesson.column_values)
    for column in terms.columns:
        if column.source is not ValueSource.PER_LESSON:
            continue
        if column.label in aktiv:
            values.pop(column.label, None)
        else:
            values[column.label] = None
    lesson.column_values = values
    session.add(lesson)
    return _back_to(back)


@router.post("/termine/{lesson_id}/erledigt")
def mark_done(
    lesson_id: int,
    back: str = Form("/"),
    session: Session = Depends(database),
) -> Response:
    _lesson(session, lesson_id).status = LessonStatus.DONE
    return _back_to(back)


@router.post("/termine/{lesson_id}/ausgefallen")
def mark_cancelled(
    lesson_id: int,
    back: str = Form("/"),
    session: Session = Depends(database),
) -> Response:
    _lesson(session, lesson_id).status = LessonStatus.CANCELLED
    return _back_to(back)


@router.post("/termine/{lesson_id}/offen")
def mark_planned(
    lesson_id: int,
    back: str = Form("/"),
    session: Session = Depends(database),
) -> Response:
    """Undo an answer that was given by mistake."""
    _lesson(session, lesson_id).status = LessonStatus.PLANNED
    return _back_to(back)


@router.post("/termine/{lesson_id}/verschieben")
def reschedule(
    lesson_id: int,
    taught_on: date = Form(...),
    starts_at: str = Form(""),
    back: str = Form("/"),
    session: Session = Depends(database),
) -> Response:
    lesson = _lesson(session, lesson_id)
    lesson.taught_on = taught_on
    if starts_at:
        lesson.starts_at = time.fromisoformat(starts_at)
    return _back_to(back)


@router.post("/termine/{lesson_id}/stunden")
def change_quantity(
    lesson_id: int,
    quantity: Decimal = Form(...),
    back: str = Form("/"),
    session: Session = Depends(database),
) -> Response:
    _lesson(session, lesson_id).quantity = quantity
    return _back_to(back)


@router.post("/termine/{lesson_id}/loeschen")
def remove_lesson(
    lesson_id: int,
    back: str = Form("/"),
    session: Session = Depends(database),
) -> Response:
    """Delete a lesson that should never have existed.

    Refused once the lesson has been billed, because the invoice would then
    name a lesson that is no longer there.
    """
    lesson = _lesson(session, lesson_id)
    if lesson.invoice_id is not None:
        raise ValueError(f"lesson {lesson_id} is already on an invoice")
    session.delete(lesson)
    return _back_to(back)


@router.post("/termine/neu")
def add_lesson(
    customer_id: int = Form(...),
    taught_on: date = Form(...),
    quantity: Decimal = Form(...),
    starts_at: str = Form(""),
    back: str = Form("/"),
    session: Session = Depends(database),
) -> Response:
    session.add(
        Lesson(
            customer_id=customer_id,
            taught_on=taught_on,
            quantity=quantity,
            starts_at=time.fromisoformat(starts_at) if starts_at else None,
        )
    )
    return _back_to(back)


def _lesson(session: Session, lesson_id: int) -> Lesson:
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise ValueError(f"no lesson with id {lesson_id}")
    session.add(lesson)
    return lesson


def _back_to(back: str) -> Response:
    return RedirectResponse(back if back.startswith("/") else "/", status_code=303)
