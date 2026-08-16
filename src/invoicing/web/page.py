"""What every page needs: the template renderer and the request dependencies."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, col, select

from invoicing.constant import WEB_STATIC_DIRECTORY, WEB_TEMPLATES_DIRECTORY
from invoicing.german_formatter import german_formatter
from invoicing.storage.database import session_for
from invoicing.storage.models import AppSettings, Customer, CustomerStatus, LessonSeries
from invoicing.templating import GermanTemplateFilters
from invoicing.utils import recurrence_label, recurrence_words


def _static_version() -> int:
    """The newest change time among the static files.

    Read once at import; every deploy restarts the server, and that restart
    is what makes the phones drop their stale caches.
    """
    return max(int(entry.stat().st_mtime) for entry in WEB_STATIC_DIRECTORY.iterdir())


templates = Jinja2Templates(directory=WEB_TEMPLATES_DIRECTORY)
GermanTemplateFilters(german_formatter).install_into(templates.env)
templates.env.filters["short_date"] = german_formatter.short_date
templates.env.filters["long_weekday"] = german_formatter.long_weekday
templates.env.filters["clock"] = german_formatter.clock
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


def series_labels(session: Session) -> dict[int, str]:
    """What to print behind the repeat sign of a lesson born from a series."""
    return {
        entry.id or 0: recurrence_label(entry.recurrence)
        for entry in session.exec(select(LessonSeries)).all()
    }


templates.env.filters["serie"] = recurrence_words
