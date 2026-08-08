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

MIGRATIONS = Path(__file__).resolve().parents[3] / "migrations"
DEFAULT_LOCATION = Path("data/invoicing.db")


def open_database(location: Path = DEFAULT_LOCATION) -> Engine:
    """Open the database, creating and migrating the file when necessary."""
    location.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{location}"
    command.upgrade(_alembic_config(url), "head")
    return create_engine(url)


@contextmanager
def session_for(engine: Engine) -> Iterator[Session]:
    """A session that commits on success and rolls back on failure."""
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def _alembic_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url)
    return config
