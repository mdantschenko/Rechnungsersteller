"""Public holidays and school holidays for the calendar.

Public holidays are computed offline by the ``holidays`` package. School
holidays cannot be computed — they are political decisions — so they come
from the OpenHolidays API and are cached in the database; saving the
settings screen refreshes them.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from datetime import date, timedelta

import holidays as holiday_calendars
from sqlmodel import Session, col, select

from invoicing.storage.models import AppSettings, SchoolHoliday

STATES = {
    "BW": "Baden-Württemberg",
    "BY": "Bayern",
    "BE": "Berlin",
    "BB": "Brandenburg",
    "HB": "Bremen",
    "HH": "Hamburg",
    "HE": "Hessen",
    "MV": "Mecklenburg-Vorpommern",
    "NI": "Niedersachsen",
    "NW": "Nordrhein-Westfalen",
    "RP": "Rheinland-Pfalz",
    "SL": "Saarland",
    "SN": "Sachsen",
    "ST": "Sachsen-Anhalt",
    "SH": "Schleswig-Holstein",
    "TH": "Thüringen",
}

# One colour per federal state, so overlapping school holidays stay apart.
STATE_COLORS = {
    "BW": "#e6550d",
    "BY": "#3182bd",
    "BE": "#31a354",
    "BB": "#756bb1",
    "HB": "#dd1c77",
    "HH": "#fd8d3c",
    "HE": "#e6ab02",
    "MV": "#6baed6",
    "NI": "#74c476",
    "NW": "#af52de",
    "RP": "#9e9ac8",
    "SL": "#a6761d",
    "SN": "#66a61e",
    "ST": "#e7298a",
    "SH": "#7570b3",
    "TH": "#1b9e77",
}

OPENHOLIDAYS = "https://openholidaysapi.org/SchoolHolidays"
TIMEOUT_SECONDS = 20

Fetch = Callable[[str, date, date], list[dict]]


class HolidayFetchError(Exception):
    """The school holidays could not be loaded; the reason is readable."""


def chosen_states(settings: AppSettings) -> list[str]:
    """The federal states picked on the settings screen, invalid codes dropped."""
    return [
        code for code in (settings.holiday_states or "").split(",") if code in STATES
    ]


def public_holidays(states: Sequence[str], first: date, last: date) -> dict[date, str]:
    """Every public holiday between ``first`` and ``last``, name per day."""
    found: dict[date, str] = {}
    for state in states:
        for day, name in _state_public_holidays(state, first, last):
            found.setdefault(day, name)
    return found


def _state_public_holidays(
    state: str, first: date, last: date
) -> list[tuple[date, str]]:
    calendar = holiday_calendars.country_holidays(
        "DE", subdiv=state, years=list(range(first.year, last.year + 1)), language="de"
    )
    return [(day, name) for day, name in calendar.items() if first <= day <= last]


def school_holidays(
    session: Session, states: Sequence[str], first: date, last: date
) -> dict[date, list[tuple[str, str]]]:
    """The cached school holidays per day: a list of (state, name) pairs."""
    rows = session.exec(
        select(SchoolHoliday)
        .where(col(SchoolHoliday.state).in_(list(states)))
        .where(SchoolHoliday.first_day <= last)
        .where(SchoolHoliday.last_day >= first)
    ).all()
    found: dict[date, list[tuple[str, str]]] = {}
    for row in sorted(rows, key=lambda row: row.state):
        _mark_holiday_days(found, row, first, last)
    return found


def _mark_holiday_days(
    found: dict[date, list[tuple[str, str]]],
    row: SchoolHoliday,
    first: date,
    last: date,
) -> None:
    day = max(row.first_day, first)
    stop = min(row.last_day, last)
    while day <= stop:
        entries = found.setdefault(day, [])
        if (row.state, row.name) not in entries:
            entries.append((row.state, row.name))
        day += timedelta(days=1)


def refresh_school_holidays(
    session: Session, states: Sequence[str], today: date, fetch: Fetch | None = None
) -> int:
    """Replace the cache with fresh data for the chosen states.

    Returns how many holiday stretches were stored.

    Raises:
        HolidayFetchError: if the API cannot be reached or answers nonsense.
    """
    fetch = fetch or _download
    first = date(today.year, 1, 1)
    last = date(today.year + 1, 12, 31)
    fresh = [
        SchoolHoliday(
            state=state,
            name=_german_name(entry),
            first_day=date.fromisoformat(entry["startDate"]),
            last_day=date.fromisoformat(entry["endDate"]),
        )
        for state in states
        for entry in fetch(state, first, last)
    ]
    for row in session.exec(select(SchoolHoliday)).all():
        session.delete(row)
    session.add_all(fresh)
    return len(fresh)


def _german_name(entry: dict) -> str:
    names = entry.get("name") or []
    for candidate in names:
        if candidate.get("language") == "DE":
            return str(candidate.get("text", "Ferien"))
    return str(names[0]["text"]) if names else "Ferien"


def _download(state: str, first: date, last: date) -> list[dict]:
    url = (
        f"{OPENHOLIDAYS}?countryIsoCode=DE&subdivisionCode=DE-{state}"
        f"&languageIsoCode=DE&validFrom={first}&validTo={last}"
    )
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as answer:
            payload = json.load(answer)
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise HolidayFetchError(
            f"Die Ferien für {STATES.get(state, state)} ließen sich nicht "
            f"laden: {error}"
        ) from error
    if not isinstance(payload, list):
        raise HolidayFetchError("Die Ferien-Antwort hatte eine unerwartete Form.")
    return payload
