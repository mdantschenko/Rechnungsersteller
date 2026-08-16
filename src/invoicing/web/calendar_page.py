"""A month calendar, and the day behind each of its cells."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session
from starlette.responses import Response

from invoicing.web.calendar_view_builder import CalendarViewBuilder
from invoicing.web.page import database
from invoicing.web.template_renderer import template_renderer

router = APIRouter()


@router.get("/")
def this_week(request: Request, session: Session = Depends(database)) -> Response:
    """The start screen is the current week: that is where the work happens."""
    return template_renderer.render(
        request, "week.html", CalendarViewBuilder(session).week_context(date.today())
    )


@router.get("/kalender/{year}/{month}")
def a_month(
    year: int, month: int, request: Request, session: Session = Depends(database)
) -> Response:
    return template_renderer.render(
        request,
        "calendar.html",
        CalendarViewBuilder(session).month_context(year, month),
    )


@router.get("/woche/{on}")
def a_week(
    on: date, request: Request, session: Session = Depends(database)
) -> Response:
    return template_renderer.render(
        request, "week.html", CalendarViewBuilder(session).week_context(on)
    )


@router.get("/tag/{on}")
def a_day(on: date, request: Request, session: Session = Depends(database)) -> Response:
    return template_renderer.render(
        request, "day.html", CalendarViewBuilder(session).day_context(on)
    )
