"""Opening the database and bringing its schema up to date.

The schema is owned by Alembic rather than by create_all, because from the
moment the historical invoices are imported the file holds records that must
survive every later schema change.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlmodel import Session, create_engine

from invoicing.constant import DATABASE_MIGRATIONS_DIRECTORY, DEFAULT_DATABASE_LOCATION


class InvoiceDatabase:
    """The database file: opening, migrating and handing out sessions."""

    def __init__(self, location: Path = DEFAULT_DATABASE_LOCATION) -> None:
        self._location = location
        self._engine: Engine | None = None

    def open(self) -> Engine:
        """Open the database, creating and migrating the file when necessary."""
        self._location.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{self._location}"
        command.upgrade(self._alembic_configuration(url), "head")
        self._engine = create_engine(url)
        return self._engine

    @contextmanager
    def session(self) -> Iterator[Session]:
        """A session that commits on success and rolls back on failure."""
        engine = self._engine if self._engine is not None else self.open()
        with Session(engine) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    @staticmethod
    def _alembic_configuration(url: str) -> Config:
        config = Config()
        config.set_main_option("script_location", str(DATABASE_MIGRATIONS_DIRECTORY))
        config.set_main_option("sqlalchemy.url", url)
        return config
