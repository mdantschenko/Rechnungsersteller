"""What every page needs: the template renderer and the request dependencies."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

from babel.dates import format_date
from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from starlette.responses import RedirectResponse

from invoicing.domain.money import format_euro, format_quantity
from invoicing.storage.database import session_for
from invoicing.storage.models import AppSettings, LessonSeries

NOTICE_KEY = "hinweis"

TEMPLATES_FOLDER = Path(__file__).parent / "templates"
STATIC_FOLDER = Path(__file__).parent / "static"

GERMAN = "de_DE"


def german_date(day: date) -> str:
    return f"{day:%d.%m.%Y}"


def short_date(day: date) -> str:
    return format_date(day, "EE d.M.", locale=GERMAN)


def long_weekday(day: date) -> str:
    return format_date(day, "EEEE, d. MMMM", locale=GERMAN)


def month_name(day: date) -> str:
    return format_date(day, "LLLL", locale=GERMAN)


templates = Jinja2Templates(directory=TEMPLATES_FOLDER)
templates.env.filters["euro"] = format_euro
templates.env.filters["quantity"] = format_quantity
templates.env.filters["german_date"] = german_date
templates.env.filters["short_date"] = short_date
templates.env.filters["long_weekday"] = long_weekday


def database(request: Request) -> Iterator[Session]:
    """A session that commits when the request finishes without an error."""
    with session_for(request.app.state.engine) as session:
        yield session


def settings_of(session: Session) -> AppSettings:
    """The single settings row.

    Raises:
        ValueError: if the application has not been set up yet.
    """
    settings = session.exec(select(AppSettings)).first()
    if settings is None:
        raise ValueError("the application has not been set up yet")
    return settings


def notice_redirect(request: Request, path: str, message: str) -> RedirectResponse:
    """Back to ``path`` with a message the layout shows once as a toast.

    The message travels in the session rather than in the URL, so a crafted
    link cannot place its own words inside the application's chrome.
    """
    request.session[NOTICE_KEY] = message
    return RedirectResponse(path, status_code=303)


def series_labels(session: Session) -> dict[int, str]:
    """What to print behind the repeat sign of a lesson born from a series."""
    return {
        entry.id or 0: _recurrence_label(entry.recurrence)
        for entry in session.exec(select(LessonSeries)).all()
    }


def _recurrence_label(recurrence: str) -> str:
    if "FREQ=WEEKLY" in recurrence:
        return "Alle zwei Wochen" if "INTERVAL=2" in recurrence else "Wöchentlich"
    return "Serie"


WEEKDAY_NAMES = {
    "MO": "Montag",
    "TU": "Dienstag",
    "WE": "Mittwoch",
    "TH": "Donnerstag",
    "FR": "Freitag",
    "SA": "Samstag",
    "SU": "Sonntag",
}


def recurrence_words(recurrence: str) -> str:
    """The recurrence rule as a German sentence: "Jeden zweiten Dienstag"."""
    if "FREQ=WEEKLY" not in recurrence:
        return recurrence
    day = next(
        (name for code, name in WEEKDAY_NAMES.items() if f"BYDAY={code}" in recurrence),
        None,
    )
    if day is None:
        return _recurrence_label(recurrence)
    return f"Jeden zweiten {day}" if "INTERVAL=2" in recurrence else f"Jeden {day}"


templates.env.filters["serie"] = recurrence_words
