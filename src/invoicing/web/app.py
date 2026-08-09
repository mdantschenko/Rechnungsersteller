"""The web application, assembled from one router per screen.

Every page except the sign-in form sits behind the password. The tunnel that
makes this reachable from a phone makes it reachable from anywhere, and
customer addresses are on the other side of it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine
from sqlmodel import Session
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse

from invoicing import alarms, push
from invoicing.storage.database import DEFAULT_LOCATION, open_database
from invoicing.web import (
    calendar_page,
    customers_page,
    daily,
    invoices_page,
    lessons_page,
    pwa,
    settings_page,
    sign_in,
)
from invoicing.web.page import STATIC_FOLDER, settings_of
from invoicing.web.security import SESSION_KEY, signing_key

OPEN_PATHS = ("/anmelden", "/static", "/manifest.webmanifest", "/sw.js")
RING_CHECK_SECONDS = 30


def create_app(location: Path = DEFAULT_LOCATION) -> FastAPI:
    """Build the application against the database at ``location``."""
    engine = open_database(location)
    with Session(engine) as session:
        secret = signing_key(session)

    app = FastAPI(
        title="Rechnungsersteller",
        docs_url=None,
        redoc_url=None,
        lifespan=_with_ticking_alarm_clock,
    )
    app.state.engine = engine
    # Starlette runs the last middleware added on the outside, so the guard is
    # registered first in order to run inside the session cookie handling.
    app.middleware("http")(_send_strangers_to_the_sign_in_page)
    app.add_middleware(SessionMiddleware, secret_key=secret, same_site="lax")
    app.mount("/static", StaticFiles(directory=STATIC_FOLDER), name="static")
    for page in (
        sign_in,
        pwa,
        calendar_page,
        lessons_page,
        customers_page,
        invoices_page,
        settings_page,
    ):
        app.include_router(page.router)
    return app


@asynccontextmanager
async def _with_ticking_alarm_clock(app: FastAPI) -> AsyncGenerator[None]:
    ticking = asyncio.create_task(_ring_forever(app.state.engine))
    yield
    ticking.cancel()
    with suppress(asyncio.CancelledError):
        await ticking


async def _ring_forever(engine: Engine) -> None:
    while True:
        try:
            await asyncio.to_thread(_ring_once, engine)
        except Exception:
            logging.getLogger(__name__).exception("Weckrunde fehlgeschlagen")
        await asyncio.sleep(RING_CHECK_SECONDS)


def _ring_once(engine: Engine) -> None:
    with Session(engine) as session:
        settings = settings_of(session)
        now = datetime.now()

        def send(message: dict[str, str]) -> int:
            return push.send_to_all(session, settings, message)

        alarms.ring_due(session, settings, now, send)
        daily.morning_round(session, settings, now, send)
        session.commit()


async def _send_strangers_to_the_sign_in_page(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if request.url.path.startswith(OPEN_PATHS) or request.session.get(SESSION_KEY):
        return await call_next(request)
    return RedirectResponse("/anmelden", status_code=303)
