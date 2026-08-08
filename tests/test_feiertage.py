from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlmodel import Session, select

from invoicing.feiertage import (
    chosen_states,
    public_holidays,
    refresh_school_holidays,
    school_holidays,
)
from invoicing.storage.database import open_database
from invoicing.storage.models import AppSettings, SchoolHoliday


def _settings(**overrides: object) -> AppSettings:
    values: dict[str, object] = {"password_hash": "x", "session_secret": "y"}
    values.update(overrides)
    return AppSettings(**values)  # type: ignore[arg-type]


def test_unknown_state_codes_are_dropped() -> None:
    settings = _settings(holiday_states="NW,XX,BY")

    assert chosen_states(settings) == ["NW", "BY"]


def test_public_holidays_know_allerheiligen() -> None:
    found = public_holidays(["NW"], date(2026, 11, 1), date(2026, 11, 1))

    assert found[date(2026, 11, 1)] == "Allerheiligen"


def test_school_holidays_cover_every_day_of_a_stretch(tmp_path: Path) -> None:
    engine = open_database(tmp_path / "test.db")
    with Session(engine) as session:
        session.add(
            SchoolHoliday(
                state="NW",
                name="Sommerferien",
                first_day=date(2026, 7, 14),
                last_day=date(2026, 8, 26),
            )
        )
        session.commit()

        found = school_holidays(session, ["NW"], date(2026, 8, 1), date(2026, 8, 31))

        assert found[date(2026, 8, 1)] == [("NW", "Sommerferien")]
        assert found[date(2026, 8, 26)] == [("NW", "Sommerferien")]
        assert date(2026, 8, 27) not in found


def test_refreshing_replaces_the_cache(tmp_path: Path) -> None:
    engine = open_database(tmp_path / "test.db")

    def fake_fetch(state: str, first: date, last: date) -> list[dict]:
        return [
            {
                "startDate": "2026-10-12",
                "endDate": "2026-10-24",
                "name": [{"language": "DE", "text": "Herbstferien"}],
            }
        ]

    with Session(engine) as session:
        session.add(
            SchoolHoliday(
                state="NW",
                name="Alt",
                first_day=date(2020, 1, 1),
                last_day=date(2020, 1, 2),
            )
        )
        session.commit()

        count = refresh_school_holidays(
            session, ["NW"], date(2026, 8, 8), fetch=fake_fetch
        )
        session.commit()

        rows = session.exec(select(SchoolHoliday)).all()
        assert count == 1
        assert len(rows) == 1
        assert rows[0].name == "Herbstferien"
