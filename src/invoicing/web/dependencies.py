"""The request dependencies the routers share."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlmodel import Session


def database_session(request: Request) -> Iterator[Session]:
    """A session that commits when the request finishes without an error.

    A free generator function because FastAPI's ``Depends`` drives it.
    """
    with request.app.state.database.session() as session:
        yield session
