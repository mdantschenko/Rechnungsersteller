from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from invoicing.storage.database import open_database
from invoicing.storage.models import (
    AppSettings,
    IssuedInvoice,
    Issuer,
    Lesson,
    LessonAlarm,
    NumberState,
    PushSubscription,
)
from invoicing.web import create_app
from invoicing.web.security import set_password

PASSWORD = "ein-gutes-passwort"


@pytest.fixture
def location(tmp_path: Path) -> Path:
    place = tmp_path / "invoicing.db"
    engine = open_database(place)
    with Session(engine) as session:
        set_password(session, PASSWORD)
        settings = session.exec(select(AppSettings)).one()
        settings.invoice_folder = str(tmp_path / "invoices")
        session.add(settings)
        session.add(NumberState(start=115))
        session.add(
            Issuer(
                name="Max Mustermann",
                street="Musterstraße 19 B",
                city="12345 Musterstadt",
                bank="Musterbank",
                iban="DE00 0000 0000 0000 0000 00",
                bic="MUSTDEFFXXX",
                tax_number="000/0000/0000",
                email="max@example.com",
                paypal="info@example.com",
            )
        )
        session.commit()
    return place


@pytest.fixture
def stranger(location: Path) -> TestClient:
    return TestClient(create_app(location))


@pytest.fixture
def client(stranger: TestClient) -> TestClient:
    stranger.post("/anmelden", data={"password": PASSWORD})
    return stranger


def test_a_stranger_is_sent_to_the_sign_in_page(stranger: TestClient) -> None:
    answer = stranger.get("/", follow_redirects=False)

    assert answer.status_code == 303
    assert answer.headers["location"] == "/anmelden"


def test_a_wrong_password_does_not_open_anything(stranger: TestClient) -> None:
    answer = stranger.post(
        "/anmelden", data={"password": "falsch"}, follow_redirects=False
    )

    assert answer.status_code == 401
    assert stranger.get("/", follow_redirects=False).status_code == 303


def test_the_manifest_is_reachable_without_signing_in(stranger: TestClient) -> None:
    answer = stranger.get("/manifest.webmanifest")

    assert answer.status_code == 200
    assert answer.json()["display"] == "standalone"


def test_signing_out_closes_the_door_again(client: TestClient) -> None:
    client.post("/abmelden")

    assert client.get("/", follow_redirects=False).status_code == 303


def test_every_screen_answers(client: TestClient) -> None:
    for path in (
        "/",
        "/kalender/2026/6",
        "/woche/2026-06-17",
        "/tag/2026-06-17",
        "/kunden",
        "/rechnungen",
        "/einstellungen",
    ):
        assert client.get(path).status_code == 200, path


def test_the_month_grid_carries_german_names(client: TestClient) -> None:
    page = client.get("/kalender/2026/6").text

    assert "Juni 2026" in page
    assert "Mo" in page and "So" in page


def test_the_week_view_names_every_day(client: TestClient) -> None:
    page = client.get("/woche/2026-06-17").text

    assert "Montag, 15. Juni" in page
    assert "Sonntag, 21. Juni" in page


def test_the_day_view_names_the_day(client: TestClient) -> None:
    assert "Mittwoch, 17. Juni 2026" in client.get("/tag/2026-06-17").text


def test_the_views_link_to_one_another(client: TestClient) -> None:
    page = client.get("/tag/2026-06-17").text

    assert "/kalender/2026/6" in page
    assert "/woche/2026-06-17" in page


def test_a_lesson_shows_up_on_its_day_and_in_its_month(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    _add_lesson(client, customer_id, date(2026, 5, 20))

    assert "Erika Beispiel" in client.get("/tag/2026-05-20").text
    assert "mark mark-planned" in client.get("/kalender/2026/5").text


def test_ticking_a_day_off_stays_on_that_day(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))

    answer = client.post(
        f"/termine/{lesson_id}/erledigt",
        data={"back": "/tag/2026-05-20"},
        follow_redirects=False,
    )

    assert answer.headers["location"] == "/tag/2026-05-20"
    assert "mark mark-done" in client.get("/kalender/2026/5").text


def test_an_answer_can_be_taken_back(client: TestClient, location: Path) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))

    client.post(f"/termine/{lesson_id}/ausgefallen", data={"back": "/"})
    client.post(f"/termine/{lesson_id}/offen", data={"back": "/"})

    with Session(open_database(location)) as session:
        lesson = session.get(Lesson, lesson_id)
        assert lesson is not None
        assert lesson.status.value == "planned"


def test_a_lesson_can_be_deleted_until_it_is_billed(
    client: TestClient, location: Path
) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))

    client.post(f"/termine/{lesson_id}/loeschen", data={"back": "/"})

    with Session(open_database(location)) as session:
        assert session.get(Lesson, lesson_id) is None


def test_overdue_lessons_are_announced_on_the_calendar(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    _add_lesson(client, customer_id, date(2020, 1, 6))

    assert "noch offen" in client.get("/").text


def test_a_new_customer_shows_up_in_the_list(client: TestClient) -> None:
    _add_customer(client)

    assert "Erika Beispiel" in client.get("/kunden").text


def test_the_terms_and_an_extra_column_can_be_set(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    _add_travel_cost_column(client, customer_id)

    page = client.get(f"/kunden/{customer_id}").text

    assert "33.33" in page
    assert "Anfahrtskosten" in page


def test_a_series_fills_the_lesson_list(client: TestClient, location: Path) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    client.post(
        f"/kunden/{customer_id}/serie",
        data={
            "recurrence": "RRULE:FREQ=WEEKLY;BYDAY=MO",
            "quantity": "1",
            "starts_on": str(date.today()),
            "starts_at": "",
        },
    )

    assert client.get("/").status_code == 200
    assert "Jeden Montag" in client.get(f"/kunden/{customer_id}").text
    with Session(open_database(location)) as session:
        assert session.exec(select(Lesson)).all()


def test_a_german_default_value_does_not_break_billing(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    client.post(
        f"/kunden/{customer_id}/spalte",
        data={
            "label": "Anfahrtskosten",
            "source": "fixed",
            "kind": "money",
            "total_rule": "add_per_row",
            "default_value": "20,00 €",
            "placeholder": "/",
        },
    )
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))
    client.post(f"/termine/{lesson_id}/erledigt")

    page = client.get("/rechnungen")

    assert page.status_code == 200
    assert "53,33" in page.text  # 33,33 lesson + 20,00 travel


def test_an_unreadable_default_value_is_refused(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)

    page = client.post(
        f"/kunden/{customer_id}/spalte",
        data={
            "label": "Anfahrtskosten",
            "source": "fixed",
            "kind": "money",
            "total_rule": "add_per_row",
            "default_value": "zwanzig",
            "placeholder": "/",
        },
    ).text

    assert "muss eine Zahl sein" in page
    # Only the form placeholder mentions the label; no column row was stored.
    assert client.get(f"/kunden/{customer_id}").text.count("Anfahrtskosten") == 1


def test_a_lesson_can_be_ticked_off_and_billed(
    client: TestClient, location: Path
) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    _add_travel_cost_column(client, customer_id)
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))

    client.post(f"/termine/{lesson_id}/erledigt")
    due = client.get("/rechnungen").text

    assert "Erika Beispiel" in due
    assert "Nr. 115" in due


def test_an_unanswered_lesson_blocks_the_invoice(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    _add_lesson(client, customer_id, date(2026, 5, 20))

    assert "noch offen" in client.get("/rechnungen").text


def test_releasing_writes_a_pdf_that_can_be_downloaded(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))
    client.post(f"/termine/{lesson_id}/erledigt")

    client.post(
        f"/rechnungen/{customer_id}/freigeben", data={"closing_day": "2026-06-15"}
    )
    downloaded = client.get("/rechnungen/115.pdf")

    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"%PDF")


def test_a_lesson_can_be_moved_and_shortened(
    client: TestClient, location: Path
) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))

    client.post(f"/termine/{lesson_id}/verschieben", data={"taught_on": "2026-05-27"})
    client.post(f"/termine/{lesson_id}/stunden", data={"quantity": "1.5"})

    with Session(open_database(location)) as session:
        lesson = session.get(Lesson, lesson_id)
        assert lesson is not None
        assert lesson.taught_on == date(2026, 5, 27)
        assert str(lesson.quantity) == "1.5"


def test_the_mail_account_can_be_saved_and_shown_again(client: TestClient) -> None:
    client.post(
        "/einstellungen/email",
        data={
            "smtp_host": "smtp.example.com",
            "smtp_port": "587",
            "smtp_user": "max@example.com",
            "smtp_password": "geheim",
            "smtp_from": "",
        },
    )

    page = client.get("/einstellungen").text

    assert "smtp.example.com" in page
    assert "geheim" not in page


def test_a_whitespace_password_does_not_replace_the_stored_one(
    client: TestClient, location: Path
) -> None:
    client.post(
        "/einstellungen/email",
        data={
            "smtp_host": "smtp.example.com",
            "smtp_port": "587",
            "smtp_user": "max@example.com",
            "smtp_password": "geheim",
            "smtp_from": "",
        },
    )
    client.post(
        "/einstellungen/email",
        data={
            "smtp_host": "smtp.example.com",
            "smtp_port": "587",
            "smtp_user": "max@example.com",
            "smtp_password": " ",
            "smtp_from": "",
        },
    )

    with Session(open_database(location)) as session:
        settings = session.exec(select(AppSettings)).one()
        assert settings.smtp_password == "geheim"


def test_the_mail_account_can_be_deleted_again(
    client: TestClient, location: Path
) -> None:
    client.post(
        "/einstellungen/email",
        data={
            "smtp_host": "smtp.example.com",
            "smtp_port": "587",
            "smtp_user": "max@example.com",
            "smtp_password": "geheim",
            "smtp_from": "",
        },
    )

    client.post("/einstellungen/email-loeschen")

    with Session(open_database(location)) as session:
        settings = session.exec(select(AppSettings)).one()
        assert settings.smtp_password is None
        assert settings.smtp_host is None


def test_a_test_invoice_without_mail_settings_is_refused(client: TestClient) -> None:
    page = client.post("/einstellungen/email-test", data={"to": "max@example.com"}).text

    assert "nicht eingerichtet" in page


def test_sending_an_invoice_needs_the_customer_address(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))
    client.post(f"/termine/{lesson_id}/erledigt")
    client.post(
        f"/rechnungen/{customer_id}/freigeben", data={"closing_day": "2026-06-15"}
    )

    page = client.post("/rechnungen/115/senden").text

    assert "keine E-Mail-Adresse" in page


def test_a_reminder_only_customer_is_never_billed(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    client.post(
        f"/kunden/{customer_id}",
        data={
            "name": "Erika Beispiel",
            "street": "Beispielstraße 21",
            "city": "54321 Beispielstadt",
            "email": "",
            "phone": "",
            "status": "active",
            "delivery": "none",
        },
    )
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))
    client.post(f"/termine/{lesson_id}/erledigt")

    assert "Zurzeit ist nichts abzurechnen." in client.get("/rechnungen").text


def test_the_student_details_are_kept(client: TestClient) -> None:
    customer_id = _add_customer(client)
    client.post(
        f"/kunden/{customer_id}",
        data={
            "name": "Erika Beispiel",
            "street": "Beispielstraße 21",
            "city": "54321 Beispielstadt",
            "email": "",
            "phone": "",
            "status": "active",
            "delivery": "email",
            "student_name": "Alexander",
            "student_grade": "8",
            "lesson_address": "Am Staatsforst 18",
        },
    )

    page = client.get(f"/kunden/{customer_id}").text

    assert 'value="Alexander"' in page
    assert 'value="8"' in page
    assert 'value="Am Staatsforst 18"' in page
    assert "#Alexander" in client.get("/kunden").text


def test_the_delivery_choice_is_kept(client: TestClient) -> None:
    customer_id = _add_customer(client)
    client.post(
        f"/kunden/{customer_id}",
        data={
            "name": "Erika Beispiel",
            "street": "Beispielstraße 21",
            "city": "54321 Beispielstadt",
            "email": "",
            "phone": "0151 2345678",
            "status": "active",
            "delivery": "whatsapp",
        },
    )

    page = client.get(f"/kunden/{customer_id}").text

    assert 'value="whatsapp" selected' in page


def test_sending_an_unknown_invoice_is_a_notice_not_a_crash(
    client: TestClient,
) -> None:
    page = client.post("/rechnungen/999/senden").text

    assert "keine Rechnung Nr. 999" in page


def test_a_sent_invoice_carries_its_mark(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))
    client.post(f"/termine/{lesson_id}/erledigt")
    client.post(
        f"/rechnungen/{customer_id}/freigeben", data={"closing_day": "2026-06-15"}
    )

    page = client.post("/rechnungen/115/gesendet").text

    assert "#Gesendet" in page
    assert "Nochmal senden" not in page


def test_an_unpaid_invoice_past_the_due_date_is_flagged(
    client: TestClient, location: Path
) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))
    client.post(f"/termine/{lesson_id}/erledigt")
    client.post(
        f"/rechnungen/{customer_id}/freigeben", data={"closing_day": "2026-06-15"}
    )
    assert "überfällig" not in client.get("/rechnungen").text

    with Session(open_database(location)) as session:
        record = session.exec(select(IssuedInvoice)).one()
        record.issued_on = date.today() - timedelta(days=30)
        session.add(record)
        session.commit()

    page = client.get("/rechnungen").text
    assert "is-overdue" in page
    assert "überfällig seit 16 Tagen" in page

    client.post("/rechnungen/115/bezahlt")
    assert "überfällig" not in client.get("/rechnungen").text


def test_a_paid_invoice_moves_out_of_the_open_list(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))
    client.post(f"/termine/{lesson_id}/erledigt")
    client.post(
        f"/rechnungen/{customer_id}/freigeben", data={"closing_day": "2026-06-15"}
    )

    page = client.post("/rechnungen/115/bezahlt").text

    assert "bezahlt am" in page
    assert "Doch nicht bezahlt" in page

    page = client.post("/rechnungen/115/unbezahlt").text
    assert "Doch nicht bezahlt" not in page


def test_a_reminder_is_recorded_and_counted(client: TestClient, location: Path) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    client.post(
        f"/kunden/{customer_id}",
        data={
            "name": "Erika Beispiel",
            "street": "Beispielstraße 21",
            "city": "54321 Beispielstadt",
            "email": "",
            "phone": "0151 2345678",
            "status": "active",
            "delivery": "whatsapp",
        },
    )
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))
    client.post(f"/termine/{lesson_id}/erledigt")
    client.post(
        f"/rechnungen/{customer_id}/freigeben", data={"closing_day": "2026-06-15"}
    )

    client.post("/rechnungen/115/erinnern")
    page = client.post("/rechnungen/115/erinnern").text

    assert "2. Erinnerung" in page
    assert "Erneut erinnern" not in page

    with Session(open_database(location)) as session:
        record = session.exec(select(IssuedInvoice)).one()
        record.issued_on = date.today() - timedelta(days=30)
        session.add(record)
        session.commit()

    assert "Erneut erinnern" in client.get("/rechnungen").text


def test_the_reminder_letter_can_be_the_customers_own(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: dict[str, str] = {}

    def capture(settings: object, **mail_parts: object) -> None:
        sent["body"] = str(mail_parts["body"])

    monkeypatch.setattr("invoicing.web.invoices_page.mail.send_pdf", capture)
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
            "reminder_text": "Rechnung {NUMMER}: {ANZAHL}. Mahnung über {BETRAG}.",
        },
    )
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))
    client.post(f"/termine/{lesson_id}/erledigt")
    client.post(
        f"/rechnungen/{customer_id}/freigeben", data={"closing_day": "2026-06-15"}
    )

    client.post("/rechnungen/115/erinnern")

    assert sent["body"] == "Rechnung 115: 1. Mahnung über 33,33\xa0€."


def test_a_customer_without_invoices_can_be_deleted(
    client: TestClient, location: Path
) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    _add_lesson(client, customer_id, date(2026, 5, 20))

    page = client.post(f"/kunden/{customer_id}/loeschen").text

    assert "gelöscht" in page
    with Session(open_database(location)) as session:
        assert session.exec(select(Lesson)).all() == []


def test_a_customer_with_invoices_cannot_be_deleted(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))
    client.post(f"/termine/{lesson_id}/erledigt")
    client.post(
        f"/rechnungen/{customer_id}/freigeben", data={"closing_day": "2026-06-15"}
    )

    page = client.post(f"/kunden/{customer_id}/loeschen").text

    assert "kann nicht" in page
    assert "Erika Beispiel" in client.get("/kunden").text


def test_earnings_and_the_tax_zip_follow_the_money(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))
    client.post(f"/termine/{lesson_id}/erledigt")
    client.post(
        f"/rechnungen/{customer_id}/freigeben", data={"closing_day": "2026-06-15"}
    )

    page = client.get("/rechnungen").text
    assert "Gesamt erhalten" in page
    assert "noch zu erwarten" in page
    assert "33,33" in page

    client.post("/rechnungen/115/bezahlt")
    page = client.get("/rechnungen").text
    assert "noch zu erwarten" not in page

    year = date.today().year
    archive = client.get(f"/rechnungen/finanzamt/{year}.zip")
    assert archive.status_code == 200
    assert archive.content.startswith(b"PK")

    per_customer = client.get(f"/kunden/{customer_id}/rechnungen.zip")
    assert per_customer.status_code == 200
    assert per_customer.content.startswith(b"PK")


def test_the_customer_page_tells_the_whole_story(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))
    client.post(f"/termine/{lesson_id}/erledigt")
    client.post(
        f"/rechnungen/{customer_id}/freigeben", data={"closing_day": "2026-06-15"}
    )

    page = client.get(f"/kunden/{customer_id}").text

    assert "Mai 2026" in page
    assert "stattgefunden" in page
    assert "Einnahmen" in page
    assert "Alle Rechnungen als ZIP" in page


def test_the_pdf_previews_inline_and_downloads_only_on_request(
    client: TestClient,
) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))
    client.post(f"/termine/{lesson_id}/erledigt")
    client.post(
        f"/rechnungen/{customer_id}/freigeben", data={"closing_day": "2026-06-15"}
    )

    shown = client.get("/rechnungen/115.pdf")
    fetched = client.get("/rechnungen/115.pdf?herunterladen=1")

    assert shown.headers["content-disposition"].startswith("inline")
    assert fetched.headers["content-disposition"].startswith("attachment")


def test_the_invoice_view_serves_its_pages_as_images(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))
    client.post(f"/termine/{lesson_id}/erledigt")
    client.post(
        f"/rechnungen/{customer_id}/freigeben", data={"closing_day": "2026-06-15"}
    )

    assert "/rechnungen/115/seite/0.png" in client.get("/rechnungen/115/ansehen").text

    page = client.get("/rechnungen/115/seite/0.png")
    assert page.status_code == 200
    assert page.content.startswith(b"\x89PNG")
    assert client.get("/rechnungen/115/seite/9.png").status_code == 404


def test_the_pdf_survives_renaming_the_customer(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))
    client.post(f"/termine/{lesson_id}/erledigt")
    client.post(
        f"/rechnungen/{customer_id}/freigeben", data={"closing_day": "2026-06-15"}
    )

    client.post(
        f"/kunden/{customer_id}",
        data={
            "name": "Erika Beispiel-Muster",
            "street": "Beispielstraße 21",
            "city": "54321 Beispielstadt",
            "email": "",
            "phone": "",
            "status": "active",
        },
    )

    assert client.get("/rechnungen/115.pdf").status_code == 200


def test_a_series_can_be_reshaped_from_today_on(
    client: TestClient, location: Path
) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    client.post(
        f"/kunden/{customer_id}/serie",
        data={
            "recurrence": "RRULE:FREQ=WEEKLY;BYDAY=MO",
            "quantity": "1",
            "starts_on": str(date.today()),
            "starts_at": "",
        },
    )
    client.get("/")

    client.post(
        f"/kunden/{customer_id}/serie/1/anpassen",
        data={
            "recurrence": "RRULE:FREQ=WEEKLY;BYDAY=WE",
            "quantity": "2",
            "starts_at": "16:00",
        },
    )

    assert "Jeden Mittwoch" in client.get(f"/kunden/{customer_id}").text
    with Session(open_database(location)) as session:
        future = [
            lesson
            for lesson in session.exec(select(Lesson)).all()
            if lesson.taught_on >= date.today()
        ]
        assert future
        assert all(lesson.taught_on.weekday() == 2 for lesson in future)
        assert all(str(lesson.quantity) == "2" for lesson in future)


def test_the_service_worker_is_reachable_without_signing_in(
    stranger: TestClient,
) -> None:
    answer = stranger.get("/sw.js")

    assert answer.status_code == 200
    assert "showNotification" in answer.text


def test_a_device_can_subscribe_to_the_alarm(
    client: TestClient, location: Path
) -> None:
    key = client.get("/push/schluessel").json()["key"]
    assert key

    answer = client.post(
        "/push/abo",
        json={
            "endpoint": "https://push.example.com/geraet-1",
            "keys": {"p256dh": "schloss", "auth": "geheim"},
        },
    )

    assert answer.status_code == 204
    with Session(open_database(location)) as session:
        stored = session.exec(select(PushSubscription)).one()
        assert stored.endpoint == "https://push.example.com/geraet-1"


def test_without_devices_the_test_ring_says_so(client: TestClient) -> None:
    page = client.post("/push/test", follow_redirects=True).text

    assert "Kein Gerät" in page


def test_opening_a_day_silences_its_alarms(client: TestClient, location: Path) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))
    with Session(open_database(location)) as session:
        session.add(LessonAlarm(lesson_id=lesson_id, rings=1))
        session.commit()

    client.get("/tag/2026-05-20")

    with Session(open_database(location)) as session:
        assert session.exec(select(LessonAlarm)).one().acknowledged


def test_a_draft_can_be_previewed_without_releasing(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))
    client.post(f"/termine/{lesson_id}/erledigt")

    preview = client.get(
        f"/rechnungen/vorschau-manuell?customer_id={customer_id}"
        "&first_day=2026-05-01&last_day=2026-05-31"
    )

    assert preview.status_code == 200
    assert preview.content.startswith(b"%PDF")
    assert "Nr. 115" in client.get("/rechnungen").text  # still only a draft


def test_the_html_preview_serves_the_invoice_page(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))
    client.post(f"/termine/{lesson_id}/erledigt")

    preview = client.get(
        f"/rechnungen/vorschau-manuell.html?customer_id={customer_id}"
        "&first_day=2026-05-01&last_day=2026-05-31"
    )

    assert preview.status_code == 200
    assert "Erika Beispiel" in preview.text
    assert "33,33" in preview.text


def test_a_manual_invoice_takes_a_hand_picked_stretch(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))
    client.post(f"/termine/{lesson_id}/erledigt")

    page = client.post(
        "/rechnungen/manuell",
        data={
            "customer_id": str(customer_id),
            "first_day": "2026-05-01",
            "last_day": "2026-05-31",
        },
    ).text

    assert "Rechnung Nr. 115" in page
    assert client.get("/rechnungen/115.pdf").status_code == 200


def test_holidays_appear_once_a_state_is_chosen(
    client: TestClient, location: Path
) -> None:
    page = client.post(
        "/einstellungen/feiertage",
        data={"show_public_holidays": "on", "states": ["NW"]},
    ).text

    assert "Gespeichert" in page
    with Session(open_database(location)) as session:
        assert session.exec(select(AppSettings)).one().holiday_states == "NW"
    assert "is-holiday" in client.get("/kalender/2026/11").text


def test_the_unit_does_the_arithmetic(client: TestClient) -> None:
    customer_id = _add_customer(client)
    client.post(
        f"/kunden/{customer_id}/vorlage",
        data={
            "unit_price": "40.00",
            "unit": "1,5h",
            "description": "Mathe Nachhilfe",
            "cycle": "month_midpoint",
        },
    )
    lesson_id = _add_lesson_with_hours(client, customer_id, date(2026, 5, 20), "1.5")
    client.post(f"/termine/{lesson_id}/erledigt")

    page = client.get("/rechnungen").text

    assert "40,00" in page  # 1.5 hours = exactly one 1,5h unit
    assert "60,00" not in page


def test_a_partial_unit_lands_on_the_calculator_cent(client: TestClient) -> None:
    customer_id = _add_customer(client)
    client.post(
        f"/kunden/{customer_id}/vorlage",
        data={
            "unit_price": "40.00",
            "unit": "1,5h",
            "description": "Mathe Nachhilfe",
            "cycle": "month_midpoint",
        },
    )
    client.post(
        f"/kunden/{customer_id}/spalte",
        data={
            "label": "Fahrtkosten",
            "source": "fixed",
            "kind": "money",
            "total_rule": "add_per_row",
            "default_value": "25,00",
            "placeholder": "/",
        },
    )
    lesson_id = _add_lesson_with_hours(client, customer_id, date(2026, 5, 20), "1")
    client.post(f"/termine/{lesson_id}/erledigt")

    page = client.get("/rechnungen").text

    assert "51,67" in page  # 40 x (1/1.5) = 26.67, plus 25 travel
    assert "51,80" not in page


def _add_lesson_with_hours(
    client: TestClient, customer_id: int, taught_on: date, hours: str
) -> int:
    client.post(
        "/termine/neu",
        data={
            "customer_id": str(customer_id),
            "taught_on": str(taught_on),
            "quantity": hours,
            "starts_at": "",
        },
    )
    return 1


def test_extra_costs_can_be_switched_off_for_one_lesson(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    client.post(
        f"/kunden/{customer_id}/spalte",
        data={
            "label": "Anfahrtskosten",
            "source": "per_lesson",
            "kind": "money",
            "total_rule": "add_per_row",
            "default_value": "25,00",
            "placeholder": "/",
        },
    )
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))

    page = client.get("/tag/2026-05-20").text
    assert "+ Anfahrtskosten" in page
    assert "Zusatzkosten speichern" in page

    client.post(f"/termine/{lesson_id}/zusatz", data={"back": "/tag/2026-05-20"})
    page = client.get("/tag/2026-05-20").text
    assert "+ Anfahrtskosten" not in page

    client.post(
        f"/termine/{lesson_id}/zusatz",
        data={"back": "/tag/2026-05-20", "aktiv": ["Anfahrtskosten"]},
    )
    assert "+ Anfahrtskosten" in client.get("/tag/2026-05-20").text


def test_a_column_can_be_reshaped(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    _add_travel_cost_column(client, customer_id)

    client.post(
        f"/kunden/{customer_id}/spalte/1",
        data={
            "label": "Fahrkosten",
            "source": "per_lesson",
            "total_rule": "add_per_row",
            "default_value": "30,00",
            "placeholder": "/",
        },
    )

    page = client.get(f"/kunden/{customer_id}").text
    assert "Fahrkosten" in page
    assert "30,00" in page
    assert "je Termin an/abwählbar" in page


def test_uninvoiced_earnings_count_the_extra_columns(client: TestClient) -> None:
    customer_id = _add_customer(client)
    client.post(
        f"/kunden/{customer_id}/vorlage",
        data={
            "unit_price": "40.00",
            "unit": "h",
            "description": "Mathe Nachhilfe",
            "cycle": "month_start",
        },
    )
    client.post(
        f"/kunden/{customer_id}/spalte",
        data={
            "label": "Fahrkosten",
            "source": "fixed",
            "kind": "money",
            "total_rule": "add_per_row",
            "default_value": "25,00",
            "placeholder": "/",
        },
    )
    client.post(
        f"/kunden/{customer_id}",
        data={
            "name": "Erika Beispiel",
            "street": "Beispielstraße 21",
            "city": "54321 Beispielstadt",
            "email": "",
            "phone": "",
            "status": "active",
            "delivery": "none",
        },
    )
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))
    client.post(f"/termine/{lesson_id}/erledigt")

    page = client.get("/rechnungen").text

    assert "65,00" in page  # 40 the hour + 25 travel


def test_the_calendar_speaks_of_the_pupil_and_the_place(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    client.post(
        f"/kunden/{customer_id}",
        data={
            "name": "Erika Beispiel",
            "street": "Beispielstraße 21",
            "city": "54321 Beispielstadt",
            "email": "",
            "phone": "",
            "status": "active",
            "delivery": "email",
            "student_name": "Alexander",
            "lesson_address": "Am Staatsforst 18",
        },
    )
    _add_lesson(client, customer_id, date(2026, 5, 20))

    page = client.get("/tag/2026-05-20").text

    assert "Alexander" in page
    assert "Am Staatsforst 18" in page


def test_an_online_pupil_shows_no_address(client: TestClient) -> None:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    client.post(
        f"/kunden/{customer_id}",
        data={
            "name": "Erika Beispiel",
            "street": "Beispielstraße 21",
            "city": "54321 Beispielstadt",
            "email": "",
            "phone": "",
            "status": "active",
            "delivery": "email",
            "online": "on",
        },
    )
    _add_lesson(client, customer_id, date(2026, 5, 20))

    page = client.get("/tag/2026-05-20").text

    assert "#Online" in page
    assert "Beispielstraße 21" not in page


def test_the_custom_letter_fills_its_placeholders(
    client: TestClient, location: Path
) -> None:
    from invoicing.storage.models import IssuedInvoice
    from invoicing.web.invoices_page import invoice_mail_body

    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    client.post(
        f"/kunden/{customer_id}",
        data={
            "name": "Erika Beispiel",
            "street": "Beispielstraße 21",
            "city": "54321 Beispielstadt",
            "email": "erika@example.com",
            "phone": "",
            "status": "active",
            "delivery": "email",
            "mail_text": "Rechnung für {MONAT} über {BETRAG}, Gruß {ABSENDER}",
        },
    )
    lesson_id = _add_lesson(client, customer_id, date(2026, 5, 20))
    client.post(f"/termine/{lesson_id}/erledigt")
    client.post(
        f"/rechnungen/{customer_id}/freigeben", data={"closing_day": "2026-06-15"}
    )

    with Session(open_database(location)) as session:
        record = session.exec(select(IssuedInvoice)).one()
        body = invoice_mail_body(session, record)

    assert "Rechnung für Mai über 33,33\xa0€, Gruß Max Mustermann" in body


def test_the_reminder_clock_time_is_kept(client: TestClient) -> None:
    customer_id = _add_customer(client)
    client.post(
        f"/kunden/{customer_id}/serie",
        data={
            "recurrence": "RRULE:FREQ=WEEKLY;BYDAY=MO",
            "quantity": "1",
            "starts_on": "2026-06-01",
            "starts_at": "15:00",
            "reminder_at": "08:30",
        },
    )

    assert 'value="08:30"' in client.get(f"/kunden/{customer_id}").text


def test_the_settings_show_the_true_next_number(
    client: TestClient, location: Path
) -> None:
    with Session(open_database(location)) as session:
        state = session.exec(select(NumberState)).one()
        state.last_assigned = 119
        session.add(state)
        session.commit()

    page = client.get("/einstellungen").text

    assert "Zuletzt vergeben: 119." in page
    assert 'name="next_number" value="120"' in page


def test_the_next_number_can_be_moved_forward(client: TestClient) -> None:
    client.post("/einstellungen/nummern", data={"next_number": "200"})

    assert 'name="next_number" value="200"' in client.get("/einstellungen").text


def test_an_already_assigned_number_is_refused(
    client: TestClient, location: Path
) -> None:
    with Session(open_database(location)) as session:
        state = session.exec(select(NumberState)).one()
        state.last_assigned = 119
        session.add(state)
        session.commit()

    page = client.post(
        "/einstellungen/nummern", data={"next_number": "110"}, follow_redirects=True
    ).text

    assert "schon vergeben" in page
    assert 'name="next_number" value="120"' in page


def test_the_password_can_be_changed_from_the_settings(client: TestClient) -> None:
    client.post("/einstellungen/passwort", data={"password": "noch-ein-passwort"})
    client.post("/abmelden")

    assert (
        client.post(
            "/anmelden", data={"password": "noch-ein-passwort"}, follow_redirects=False
        ).status_code
        == 303
    )


def _configure_mail(client: TestClient) -> None:
    client.post(
        "/einstellungen/email",
        data={
            "smtp_host": "smtp.example.com",
            "smtp_port": "587",
            "smtp_user": "ich@example.com",
            "smtp_password": "geheim",
            "smtp_from": "",
        },
    )


def test_with_mail_set_up_the_password_waits_for_the_code(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: dict[str, str] = {}

    def capture(
        settings: object, to: str, subject: str, body: str, **_: object
    ) -> None:
        sent["to"] = to
        sent["code"] = body.split("Code lautet: ")[1].split("\n")[0]

    monkeypatch.setattr("invoicing.web.settings_page.mail.send_text", capture)
    _configure_mail(client)
    client.post("/einstellungen/passwort", data={"password": "noch-ein-passwort"})

    assert sent["to"] == "ich@example.com"
    client.post("/abmelden")
    assert (
        client.post(
            "/anmelden", data={"password": "noch-ein-passwort"}, follow_redirects=False
        ).status_code
        == 401
    )

    client.post("/anmelden", data={"password": PASSWORD})
    client.post("/einstellungen/passwort-bestaetigen", data={"code": sent["code"]})
    client.post("/abmelden")
    assert (
        client.post(
            "/anmelden", data={"password": "noch-ein-passwort"}, follow_redirects=False
        ).status_code
        == 303
    )


def test_a_wrong_code_changes_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "invoicing.web.settings_page.mail.send_text", lambda *a, **k: None
    )
    _configure_mail(client)
    client.post("/einstellungen/passwort", data={"password": "noch-ein-passwort"})

    page = client.post(
        "/einstellungen/passwort-bestaetigen",
        data={"code": "000000"},
        follow_redirects=True,
    ).text

    assert "stimmt nicht" in page
    client.post("/abmelden")
    assert (
        client.post(
            "/anmelden", data={"password": PASSWORD}, follow_redirects=False
        ).status_code
        == 303
    )


def _add_customer(client: TestClient) -> int:
    answer = client.post(
        "/kunden/neu",
        data={
            "name": "Erika Beispiel",
            "street": "Beispielstraße 21",
            "city": "54321 Beispielstadt",
        },
        follow_redirects=False,
    )
    return int(answer.headers["location"].rsplit("/", maxsplit=1)[1])


def _set_terms(client: TestClient, customer_id: int) -> None:
    client.post(
        f"/kunden/{customer_id}/vorlage",
        data={
            "unit_price": "33.33",
            "unit": "h",
            "description": "Mathe Nachhilfe",
            "cycle": "month_midpoint",
        },
    )


def _add_travel_cost_column(client: TestClient, customer_id: int) -> None:
    client.post(
        f"/kunden/{customer_id}/spalte",
        data={
            "label": "Anfahrtskosten",
            "source": "fixed",
            "kind": "money",
            "total_rule": "add_per_row",
            "default_value": "",
            "placeholder": "0 €",
        },
    )


def _add_lesson(client: TestClient, customer_id: int, taught_on: date) -> int:
    client.post(
        "/termine/neu",
        data={
            "customer_id": str(customer_id),
            "taught_on": str(taught_on),
            "quantity": "1",
            "starts_at": "",
        },
    )
    return 1
