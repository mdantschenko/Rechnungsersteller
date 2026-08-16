from __future__ import annotations

import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pyzipper
from sqlalchemy import Engine
from sqlmodel import Session, select

from invoicing.mail import SmtpMailer
from invoicing.storage.models import (
    AppSettings,
    Customer,
    IssuedInvoice,
    Lesson,
    LessonStatus,
)
from invoicing.web.daily import MorningRound

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
    monkeypatch.setattr(
        SmtpMailer, "send_pdf", lambda mailer, *a, **k: outbox.append(str(k["to"]))
    )
    rung: list[dict[str, str]] = []

    MorningRound(session, _settings(session), rung.append).run(MORNING)

    assert outbox == ["erika@example.com"]
    record = session.exec(select(IssuedInvoice)).one()
    assert record.sent_on == MORNING.date()
    assert "automatisch per E-Mail verschickt" in rung[0]["body"]


def test_without_the_switch_the_round_only_announces(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(SmtpMailer, "send_pdf", lambda *a, **k: pytest.fail("gesendet"))
    settings = _settings(session)
    settings.auto_send_invoices = False
    rung: list[dict[str, str]] = []

    MorningRound(session, settings, rung.append).run(MORNING)

    assert session.exec(select(IssuedInvoice)).first() is None
    assert "warten auf dich" in rung[0]["body"]


def test_the_round_respects_the_clock_and_runs_once(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(SmtpMailer, "send_pdf", lambda *a, **k: None)
    rung: list[dict[str, str]] = []

    MorningRound(session, _settings(session), rung.append).run(
        datetime(2026, 6, 16, 6, 59)
    )
    assert rung == []

    MorningRound(session, _settings(session), rung.append).run(MORNING)
    assert len(rung) == 1

    MorningRound(session, _settings(session), rung.append).run(
        datetime(2026, 6, 16, 9, 0)
    )
    assert len(rung) == 1


def test_monday_mails_a_sealed_backup(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    parcels: dict[str, object] = {}

    def capture(mailer: SmtpMailer, **parts: object) -> None:
        parcels.update(parts)

    monkeypatch.setattr(SmtpMailer, "send_attachment", capture)
    monkeypatch.setattr(SmtpMailer, "send_pdf", lambda *a, **k: None)
    settings = _settings(session)

    MorningRound(session, settings, lambda m: None).run(datetime(2026, 6, 15, 7, 30))

    assert str(parcels["file_name"]).endswith(".zip")
    sealed = pyzipper.AESZipFile(io.BytesIO(bytes(parcels["content"])))  # type: ignore[arg-type]
    sealed.setpassword((settings.backup_passphrase or "").encode())
    assert sealed.read("invoicing.db")
    assert settings.last_backup_mailed == date(2026, 6, 15)


def test_other_days_mail_no_backup(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        SmtpMailer,
        "send_attachment",
        lambda *a, **k: pytest.fail("Backup am Dienstag"),
    )
    monkeypatch.setattr(SmtpMailer, "send_pdf", lambda *a, **k: None)

    MorningRound(session, _settings(session), lambda m: None).run(MORNING)

    assert _settings(session).last_backup_mailed is None


def test_a_freshly_overdue_invoice_announces_itself(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(SmtpMailer, "send_pdf", lambda *a, **k: None)
    rung: list[dict[str, str]] = []
    MorningRound(session, _settings(session), rung.append).run(MORNING)
    record = session.exec(select(IssuedInvoice)).one()
    record.issued_on = MORNING.date() - timedelta(days=14)
    session.add(record)
    session.commit()

    MorningRound(session, _settings(session), rung.append).run(
        MORNING + timedelta(days=1)
    )
    assert "überfällig" in rung[1]["body"]

    MorningRound(session, _settings(session), rung.append).run(
        MORNING + timedelta(days=2)
    )
    assert len(rung) == 2
