"""A new invoice and an older unpaid one leave the house as one mail."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from test_web import _add_customer, _add_lesson, _set_terms

from invoicing.storage.invoice_database import InvoiceDatabase
from invoicing.storage.models import IssuedInvoice, Lesson, PaymentReminder


def _customer_with_email(client: TestClient) -> int:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    client.post(
        f"/kunden/{customer_id}",
        data={
            "name": "Erika Beispiel",
            "street": "Beispielstraße 21",
            "city": "54321 Beispielstadt",
            "email": "erika@example.com",
            "status": "active",
            "delivery": "email",
        },
    )
    return customer_id


def _released_invoice(
    client: TestClient,
    location: Path,
    customer_id: int,
    taught_on: date,
    closing_day: date,
) -> None:
    _add_lesson(client, customer_id, taught_on)
    client.post(f"/termine/{_lesson_id_on(location, taught_on)}/erledigt")
    client.post(
        f"/rechnungen/{customer_id}/freigeben",
        data={"closing_day": closing_day.isoformat()},
    )


def _lesson_id_on(location: Path, taught_on: date) -> int:
    with Session(InvoiceDatabase(location).open()) as session:
        lesson = session.exec(select(Lesson).where(Lesson.taught_on == taught_on)).one()
        return lesson.id or 0


def _make_overdue(location: Path, number: int, days: int) -> None:
    with Session(InvoiceDatabase(location).open()) as session:
        record = session.exec(
            select(IssuedInvoice).where(IssuedInvoice.number == number)
        ).one()
        record.issued_on = date.today() - timedelta(days=days)
        session.add(record)
        session.commit()


def test_an_overdue_invoice_rides_along_with_the_new_one(
    client: TestClient, location: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: dict[str, Any] = {}
    monkeypatch.setattr(
        "invoicing.mail.SmtpMailer.send_pdf",
        lambda mailer, **parts: sent.update(parts),
    )
    customer_id = _customer_with_email(client)
    _released_invoice(
        client, location, customer_id, date(2026, 5, 20), date(2026, 6, 15)
    )
    _make_overdue(location, 115, 60)
    _released_invoice(
        client, location, customer_id, date(2026, 6, 20), date(2026, 7, 15)
    )

    client.post("/rechnungen/116/senden")

    assert sent["subject"] == "Rechnung Nr. 116 und offene Rechnung Nr. 115"
    assert "P.S.: Offen ist außerdem noch die Rechnung Nr. 115" in str(sent["body"])
    assert len(list(sent["more_pdfs"])) == 1


def test_the_open_invoice_is_written_down_as_reminded(
    client: TestClient, location: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("invoicing.mail.SmtpMailer.send_pdf", lambda *a, **k: None)
    customer_id = _customer_with_email(client)
    _released_invoice(
        client, location, customer_id, date(2026, 5, 20), date(2026, 6, 15)
    )
    _make_overdue(location, 115, 60)
    _released_invoice(
        client, location, customer_id, date(2026, 6, 20), date(2026, 7, 15)
    )

    client.post("/rechnungen/116/senden")

    with Session(InvoiceDatabase(location).open()) as session:
        older = session.exec(
            select(IssuedInvoice).where(IssuedInvoice.number == 115)
        ).one()
        reminders = session.exec(
            select(PaymentReminder).where(PaymentReminder.invoice_id == older.id)
        ).all()
    assert len(reminders) == 1


def test_an_invoice_still_inside_its_payment_window_stays_out(
    client: TestClient, location: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: dict[str, Any] = {}
    monkeypatch.setattr(
        "invoicing.mail.SmtpMailer.send_pdf",
        lambda mailer, **parts: sent.update(parts),
    )
    customer_id = _customer_with_email(client)
    _released_invoice(
        client, location, customer_id, date(2026, 5, 20), date(2026, 6, 15)
    )
    _make_overdue(location, 115, 1)
    _released_invoice(
        client, location, customer_id, date(2026, 6, 20), date(2026, 7, 15)
    )

    client.post("/rechnungen/116/senden")

    assert sent["subject"] == "Rechnung Nr. 116"
    assert "P.S." not in str(sent["body"])
    assert list(sent["more_pdfs"]) == []


def test_a_paid_older_invoice_stays_out(
    client: TestClient, location: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: dict[str, Any] = {}
    monkeypatch.setattr(
        "invoicing.mail.SmtpMailer.send_pdf",
        lambda mailer, **parts: sent.update(parts),
    )
    customer_id = _customer_with_email(client)
    _released_invoice(
        client, location, customer_id, date(2026, 5, 20), date(2026, 6, 15)
    )
    _make_overdue(location, 115, 60)
    client.post("/rechnungen/115/bezahlt")
    _released_invoice(
        client, location, customer_id, date(2026, 6, 20), date(2026, 7, 15)
    )

    client.post("/rechnungen/116/senden")

    assert sent["subject"] == "Rechnung Nr. 116"
    assert list(sent["more_pdfs"]) == []


def test_the_reminder_shows_its_letter_before_it_goes_out(
    client: TestClient, location: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outbox: list[object] = []
    monkeypatch.setattr(
        "invoicing.mail.SmtpMailer.send_pdf", lambda *a, **k: outbox.append(k)
    )
    customer_id = _customer_with_email(client)
    _released_invoice(
        client, location, customer_id, date(2026, 5, 20), date(2026, 6, 15)
    )
    _make_overdue(location, 115, 60)

    page = client.get("/rechnungen/115/erinnerung").text

    assert "1. Zahlungserinnerung" in page
    assert "Zahlungserinnerung zur Rechnung Nr. 115" in page
    assert "erika@example.com" in page
    assert outbox == []


def test_the_letter_keeps_its_line_breaks_without_running_off_the_screen(
    client: TestClient, location: Path
) -> None:
    """The letter is styled text, not a code block that scrolls sideways."""
    customer_id = _customer_with_email(client)
    _released_invoice(
        client, location, customer_id, date(2026, 5, 20), date(2026, 6, 15)
    )
    _make_overdue(location, 115, 60)

    page = client.get("/rechnungen/115/erinnerung").text
    stylesheet = client.get("/static/app.css").text

    assert '<p class="mail-body">' in page
    assert "<pre" not in page
    assert "white-space: pre-wrap" in stylesheet
    assert "overflow-wrap: anywhere" in stylesheet


def test_the_paid_list_has_a_button_and_no_swipe_gesture(
    client: TestClient, location: Path
) -> None:
    """The button is the only way in; a swipe would fight the page scroll."""
    customer_id = _customer_with_email(client)
    _released_invoice(
        client, location, customer_id, date(2026, 5, 20), date(2026, 6, 15)
    )
    client.post("/rechnungen/115/bezahlt")

    page = client.get("/rechnungen").text

    assert "/rechnungen/115/ausblenden" in page
    assert "swipe-away" not in page
    assert client.get("/static/keep-scroll-position.js").status_code == 200


def test_a_paid_invoice_can_be_taken_off_the_list(
    client: TestClient, location: Path
) -> None:
    customer_id = _customer_with_email(client)
    _released_invoice(
        client, location, customer_id, date(2026, 5, 20), date(2026, 6, 15)
    )
    client.post("/rechnungen/115/bezahlt")
    assert "bezahlt am" in client.get("/rechnungen").text

    client.post("/rechnungen/115/ausblenden")

    page = client.get("/rechnungen").text
    assert "bezahlt am" not in page
    assert "1 bezahlte Rechnung(en) ausgeblendet" in page


def test_a_hidden_invoice_still_counts_for_the_books(
    client: TestClient, location: Path
) -> None:
    """Hiding tidies the screen; it must never touch the records."""
    customer_id = _customer_with_email(client)
    _released_invoice(
        client, location, customer_id, date(2026, 5, 20), date(2026, 6, 15)
    )
    client.post("/rechnungen/115/bezahlt")
    client.post("/rechnungen/115/ausblenden")

    with Session(InvoiceDatabase(location).open()) as session:
        record = session.exec(
            select(IssuedInvoice).where(IssuedInvoice.number == 115)
        ).one()
        assert record.paid_on is not None
    assert client.get("/rechnungen/115.pdf").status_code == 200
    assert client.get("/rechnungen/finanzamt/2026.zip").status_code == 200


def test_hidden_invoices_can_be_brought_back(
    client: TestClient, location: Path
) -> None:
    customer_id = _customer_with_email(client)
    _released_invoice(
        client, location, customer_id, date(2026, 5, 20), date(2026, 6, 15)
    )
    client.post("/rechnungen/115/bezahlt")
    client.post("/rechnungen/115/ausblenden")

    client.post("/rechnungen/bezahlt-wieder-zeigen")

    page = client.get("/rechnungen").text
    assert "bezahlt am" in page
    assert "ausgeblendet" not in page


def test_marking_it_unpaid_brings_a_hidden_invoice_back(
    client: TestClient, location: Path
) -> None:
    customer_id = _customer_with_email(client)
    _released_invoice(
        client, location, customer_id, date(2026, 5, 20), date(2026, 6, 15)
    )
    client.post("/rechnungen/115/bezahlt")
    client.post("/rechnungen/115/ausblenden")
    client.post("/rechnungen/115/unbezahlt")
    client.post("/rechnungen/115/bezahlt")

    assert "bezahlt am" in client.get("/rechnungen").text
