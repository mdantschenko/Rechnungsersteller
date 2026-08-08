"""The web application, assembled from one router per screen.

Every page except the sign-in form sits behind the password. The tunnel that
makes this reachable from a phone makes it reachable from anywhere, and
customer addresses are on the other side of it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse

from invoicing.storage.database import DEFAULT_LOCATION, open_database
from invoicing.web import (
    calendar_feed,
    calendar_page,
    customers_page,
    invoices_page,
    lessons_page,
    pwa,
    settings_page,
    sign_in,
)
from invoicing.web.page import STATIC_FOLDER
from invoicing.web.security import SESSION_KEY, signing_key

# The calendar feed guards itself with a token; a calendar app cannot sign in.
OPEN_PATHS = ("/anmelden", "/static", "/manifest.webmanifest", "/kalender.ics")


def create_app(location: Path = DEFAULT_LOCATION) -> FastAPI:
    """Build the application against the database at ``location``."""
    engine = open_database(location)
    with Session(engine) as session:
        secret = signing_key(session)

    app = FastAPI(title="Rechnungsersteller", docs_url=None, redoc_url=None)
    app.state.engine = engine
    # Starlette runs the last middleware added on the outside, so the guard is
    # registered first in order to run inside the session cookie handling.
    app.middleware("http")(_send_strangers_to_the_sign_in_page)
    app.add_middleware(SessionMiddleware, secret_key=secret, same_site="lax")
    app.mount("/static", StaticFiles(directory=STATIC_FOLDER), name="static")
    for page in (
        sign_in,
        pwa,
        calendar_feed,
        calendar_page,
        lessons_page,
        customers_page,
        invoices_page,
        settings_page,
    ):
        app.include_router(page.router)
    return app


async def _send_strangers_to_the_sign_in_page(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if request.url.path.startswith(OPEN_PATHS) or request.session.get(SESSION_KEY):
        return await call_next(request)
    return RedirectResponse("/anmelden", status_code=303)
