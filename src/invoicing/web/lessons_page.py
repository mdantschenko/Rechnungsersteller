"""Answering for a lesson: it happened, it did not, it moved, it was shorter.

Every action comes back to the page it was triggered from, so ticking a day
off in the calendar leaves you in the calendar.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Form
from sqlmodel import Session
from starlette.responses import Response

from invoicing.utils import safe_back_redirect
from invoicing.web.dependencies import database_session
from invoicing.web.lesson_editor import LessonEditor

router = APIRouter()


@router.post("/termine/{lesson_id}/zusatz")
def set_extra_costs(
    lesson_id: int,
    back: str = Form("/"),
    aktiv: list[str] = Form([]),
    session: Session = Depends(database_session),
) -> Response:
    LessonEditor(session).set_extra_costs(lesson_id, aktiv)
    return safe_back_redirect(back)


@router.post("/termine/{lesson_id}/erledigt")
def mark_done(
    lesson_id: int,
    back: str = Form("/"),
    session: Session = Depends(database_session),
) -> Response:
    LessonEditor(session).mark_done(lesson_id)
    return safe_back_redirect(back)


@router.post("/termine/{lesson_id}/ausgefallen")
def mark_cancelled(
    lesson_id: int,
    back: str = Form("/"),
    session: Session = Depends(database_session),
) -> Response:
    LessonEditor(session).mark_cancelled(lesson_id)
    return safe_back_redirect(back)


@router.post("/termine/{lesson_id}/offen")
def mark_planned(
    lesson_id: int,
    back: str = Form("/"),
    session: Session = Depends(database_session),
) -> Response:
    LessonEditor(session).mark_planned(lesson_id)
    return safe_back_redirect(back)


@router.post("/termine/{lesson_id}/verschieben")
def reschedule(
    lesson_id: int,
    taught_on: date = Form(...),
    starts_at: str = Form(""),
    back: str = Form("/"),
    session: Session = Depends(database_session),
) -> Response:
    LessonEditor(session).reschedule(lesson_id, taught_on, starts_at)
    return safe_back_redirect(back)


@router.post("/termine/{lesson_id}/stunden")
def change_quantity(
    lesson_id: int,
    quantity: Decimal = Form(...),
    back: str = Form("/"),
    session: Session = Depends(database_session),
) -> Response:
    LessonEditor(session).change_quantity(lesson_id, quantity)
    return safe_back_redirect(back)


@router.post("/termine/{lesson_id}/loeschen")
def remove_lesson(
    lesson_id: int,
    back: str = Form("/"),
    session: Session = Depends(database_session),
) -> Response:
    LessonEditor(session).remove(lesson_id)
    return safe_back_redirect(back)


@router.post("/termine/neu")
def add_lesson(
    customer_id: int = Form(...),
    taught_on: date = Form(...),
    quantity: Decimal = Form(...),
    starts_at: str = Form(""),
    back: str = Form("/"),
    session: Session = Depends(database_session),
) -> Response:
    LessonEditor(session).add(customer_id, taught_on, quantity, starts_at)
    return safe_back_redirect(back)
