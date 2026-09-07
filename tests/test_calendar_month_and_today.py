"""The view switch stays on today, and the month shows what it earned."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session, select
from test_web import _add_customer, _add_lesson, _set_terms

from invoicing.storage.invoice_database import InvoiceDatabase
from invoicing.storage.models import AppSettings, Lesson
from invoicing.web.calendar_view_builder import CalendarViewBuilder
from invoicing.web.lessons_earned_between import LessonsEarnedBetween


def _lesson_id_on(location: Path, taught_on: date) -> int:
    with Session(InvoiceDatabase(location).open()) as session:
        return (
            session.exec(select(Lesson).where(Lesson.taught_on == taught_on)).one().id
            or 0
        )


FRIDAY_IN_SEPTEMBER = date(2026, 9, 4)
ITS_MONDAY_IN_AUGUST = date(2026, 8, 31)


def _pretend_today_is(monkeypatch: pytest.MonkeyPatch, pretend: date) -> None:
    class Today(date):
        @classmethod
        def today(cls) -> date:
            return pretend

    monkeypatch.setattr("invoicing.web.calendar_view_builder.date", Today)


def _set_up(session: Session) -> None:
    if session.exec(select(AppSettings)).first() is None:
        session.add(AppSettings(password_hash="egal", session_secret="egal"))
        session.commit()


def test_the_switch_leads_to_the_month_of_today_not_of_the_monday(
    ready_to_bill: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The week of 31 August holds 4 September, so the switch says September."""
    _pretend_today_is(monkeypatch, FRIDAY_IN_SEPTEMBER)

    with Session(ready_to_bill) as session:
        _set_up(session)
        context = CalendarViewBuilder(session).week_context(ITS_MONDAY_IN_AUGUST)

    assert context["reference"] == FRIDAY_IN_SEPTEMBER


def test_a_week_without_today_keeps_its_own_monday(
    ready_to_bill: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pretend_today_is(monkeypatch, FRIDAY_IN_SEPTEMBER)
    monday_far_away = date(2026, 6, 1)

    with Session(ready_to_bill) as session:
        _set_up(session)
        context = CalendarViewBuilder(session).week_context(monday_far_away)

    assert context["reference"] == monday_far_away


WEDNESDAY = date(2026, 5, 20)
THE_FRIDAY_AFTER = date(2026, 5, 22)


def _a_lesson_ticked_off(client: TestClient, location: Path, on: date) -> None:
    customer_id = 1
    _add_lesson(client, customer_id, on)
    client.post(f"/termine/{_lesson_id_on(location, on)}/erledigt")


def test_a_ticked_off_lesson_counts_only_for_its_own_days(
    client: TestClient, location: Path
) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    _add_lesson(client, customer_id, WEDNESDAY)

    with Session(InvoiceDatabase(location).open()) as session:
        assert LessonsEarnedBetween(session).total(WEDNESDAY, WEDNESDAY) == 0

    client.post(f"/termine/{_lesson_id_on(location, WEDNESDAY)}/erledigt")

    with Session(InvoiceDatabase(location).open()) as session:
        earned = LessonsEarnedBetween(session)
        assert str(earned.total(WEDNESDAY, WEDNESDAY)) == "33.33"
        assert earned.total(THE_FRIDAY_AFTER, THE_FRIDAY_AFTER) == 0
        assert earned.total(date(2026, 6, 1), date(2026, 6, 30)) == 0


def test_each_view_counts_its_own_stretch_of_days(
    client: TestClient, location: Path
) -> None:
    """Two lessons in one week: the day shows one, the week and month both."""
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    _a_lesson_ticked_off(client, location, WEDNESDAY)
    _a_lesson_ticked_off(client, location, THE_FRIDAY_AFTER)

    day = client.get(f"/tag/{WEDNESDAY}").text
    week = client.get(f"/woche/{WEDNESDAY}").text
    month = client.get("/kalender/2026/5").text

    assert "33,33" in day
    assert "an diesem Tag abgehakt" in day
    assert "66,66" in week
    assert "in dieser Woche abgehakt" in week
    assert "66,66" in month
    assert "in diesem Monat abgehakt" in month


def test_every_stretch_starts_again_at_nothing(
    client: TestClient, location: Path
) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    _a_lesson_ticked_off(client, location, WEDNESDAY)

    assert "0,00" in client.get("/kalender/2026/6").text
    assert "0,00" in client.get(f"/tag/{THE_FRIDAY_AFTER}").text
    assert "0,00" in client.get("/woche/2026-06-01").text
