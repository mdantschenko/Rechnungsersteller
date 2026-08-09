"""What every page needs: the template renderer and the request dependencies."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, time
from pathlib import Path

from babel.dates import format_date
from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, col, select
from starlette.responses import RedirectResponse

from invoicing.storage.database import session_for
from invoicing.storage.models import AppSettings, Customer, CustomerStatus, LessonSeries
from invoicing.templating import install_german_filters

NOTICE_KEY = "hinweis"

TEMPLATES_FOLDER = Path(__file__).parent / "templates"
STATIC_FOLDER = Path(__file__).parent / "static"

GERMAN = "de_DE"


def short_date(day: date) -> str:
    return format_date(day, "EE d.M.", locale=GERMAN)


def long_weekday(day: date) -> str:
    return format_date(day, "EEEE, d. MMMM", locale=GERMAN)


def month_name(day: date) -> str:
    return format_date(day, "LLLL", locale=GERMAN)


def clock(moment: time) -> str:
    """A clock time the way the calendar prints it: ``14:30``."""
    return f"{moment:%H:%M}"


def _static_version() -> int:
    """The newest change time among the static files.

    Read once at import; every deploy restarts the server, and that restart
    is what makes the phones drop their stale caches.
    """
    return max(int(entry.stat().st_mtime) for entry in STATIC_FOLDER.iterdir())


templates = Jinja2Templates(directory=TEMPLATES_FOLDER)
install_german_filters(templates.env)
templates.env.filters["short_date"] = short_date
templates.env.filters["long_weekday"] = long_weekday
templates.env.filters["clock"] = clock
templates.env.globals["static_version"] = _static_version()


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


def customer_of(session: Session, customer_id: int) -> Customer:
    """The customer behind an id.

    Raises:
        ValueError: if the id does not belong to anyone.
    """
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise ValueError(f"no customer with id {customer_id}")
    return customer


def active_customers(session: Session) -> list[Customer]:
    """Everyone still taking lessons, A to Z."""
    statement = (
        select(Customer)
        .where(Customer.status == CustomerStatus.ACTIVE)
        .order_by(col(Customer.name))
    )
    return list(session.exec(statement).all())


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
