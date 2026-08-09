from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlmodel import Session, select

from invoicing import mail
from invoicing.storage.models import (
    AppSettings,
    Customer,
    IssuedInvoice,
    Lesson,
    LessonStatus,
)
from invoicing.web.daily import morning_round

MORNING = datetime(2026, 6, 16, 7, 30)


@pytest.fixture
def session(ready_to_bill: Engine, tmp_path: Path):
    with Session(ready_to_bill) as inside:
        inside.add(
            AppSettings(
                password_hash="egal",
                session_secret="egal",
                invoice_folder=str(tmp_path / "rechnungen"),
                smtp_host="smtp.example.com",
                smtp_user="ich@example.com",
                smtp_password="geheim",
                auto_send_invoices=True,
            )
        )
        customer = inside.exec(select(Customer)).one()
        customer.email = "erika@example.com"
        inside.add(customer)
        inside.add(
            Lesson(
                customer_id=customer.id or 0,
                taught_on=date(2026, 6, 10),
                quantity=Decimal(1),
                status=LessonStatus.DONE,
            )
        )
        inside.commit()
        yield inside


def _settings(session: Session) -> AppSettings:
    return session.exec(select(AppSettings)).one()


def test_the_round_sends_due_invoices_and_reports(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    outbox: list[str] = []
    monkeypatch.setattr(mail, "send_pdf", lambda *a, **k: outbox.append(str(k["to"])))
    rung: list[dict[str, str]] = []

    morning_round(session, _settings(session), MORNING, rung.append)

    assert outbox == ["erika@example.com"]
    record = session.exec(select(IssuedInvoice)).one()
    assert record.sent_on == MORNING.date()
    assert "automatisch per E-Mail verschickt" in rung[0]["body"]


def test_without_the_switch_the_round_only_announces(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mail, "send_pdf", lambda *a, **k: pytest.fail("gesendet"))
    settings = _settings(session)
    settings.auto_send_invoices = False
    rung: list[dict[str, str]] = []

    morning_round(session, settings, MORNING, rung.append)

    assert session.exec(select(IssuedInvoice)).first() is None
    assert "warten auf dich" in rung[0]["body"]


def test_the_round_respects_the_clock_and_runs_once(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mail, "send_pdf", lambda *a, **k: None)
    rung: list[dict[str, str]] = []

    morning_round(
        session, _settings(session), datetime(2026, 6, 16, 6, 59), rung.append
    )
    assert rung == []

    morning_round(session, _settings(session), MORNING, rung.append)
    assert len(rung) == 1

    morning_round(session, _settings(session), datetime(2026, 6, 16, 9, 0), rung.append)
    assert len(rung) == 1


def test_a_freshly_overdue_invoice_announces_itself(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mail, "send_pdf", lambda *a, **k: None)
    rung: list[dict[str, str]] = []
    morning_round(session, _settings(session), MORNING, rung.append)
    record = session.exec(select(IssuedInvoice)).one()
    record.issued_on = MORNING.date() - timedelta(days=14)
    session.add(record)
    session.commit()

    morning_round(session, _settings(session), MORNING + timedelta(days=1), rung.append)
    assert "überfällig" in rung[1]["body"]

    morning_round(session, _settings(session), MORNING + timedelta(days=2), rung.append)
    assert len(rung) == 2
