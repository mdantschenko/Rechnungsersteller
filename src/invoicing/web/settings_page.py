"""Sender details, filing, numbering, the password and the mail account."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import APIRouter, Depends, Form, Request
from sqlmodel import Session, select
from starlette.responses import RedirectResponse, Response

from invoicing import feiertage, mail
from invoicing.billing import domain_issuer, sequence_of
from invoicing.constant import (
    GERMAN_FEDERAL_STATES,
    PAYMENT_DAYS_MAXIMUM,
    REMINDER_MINUTES_MAXIMUM,
)
from invoicing.domain import invoice as document
from invoicing.pdf.invoice_document import write_pdf
from invoicing.sample import sample_invoice
from invoicing.storage.models import Issuer, NumberState
from invoicing.utils import (
    ensure_backup_passphrase,
    mailbox_address_of,
    notice_redirect,
)
from invoicing.web import security
from invoicing.web.page import database, settings_of, templates

router = APIRouter()


@router.get("/einstellungen")
def settings_form(request: Request, session: Session = Depends(database)) -> Response:
    settings = settings_of(session)
    ensure_backup_passphrase(session, settings)
    numbering = session.exec(select(NumberState)).first()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "issuer": session.exec(select(Issuer)).first(),
            "numbering": numbering,
            "next_number": sequence_of(numbering).peek(),
            "settings": settings,
            "states": GERMAN_FEDERAL_STATES,
            "chosen_states": feiertage.chosen_states(settings),
            "pending_password": security.has_pending_password(session),
        },
    )


@router.post("/einstellungen/feiertage")
def save_holidays(
    request: Request,
    show_public_holidays: str = Form(""),
    show_school_holidays: str = Form(""),
    states: list[str] = Form([]),
    session: Session = Depends(database),
) -> Response:
    settings = settings_of(session)
    settings.show_public_holidays = bool(show_public_holidays)
    settings.show_school_holidays = bool(show_school_holidays)
    chosen = [code for code in states if code in GERMAN_FEDERAL_STATES]
    settings.holiday_states = ",".join(chosen)
    session.add(settings)
    if not (settings.show_school_holidays and chosen):
        return notice_redirect(request, "/einstellungen", "Gespeichert.")
    try:
        count = feiertage.refresh_school_holidays(session, chosen, date.today())
    except feiertage.HolidayFetchError as error:
        return notice_redirect(request, "/einstellungen", f"Gespeichert, aber: {error}")
    return notice_redirect(
        request, "/einstellungen", f"Gespeichert — {count} Ferienzeiträume geladen."
    )


@router.post("/einstellungen/automatik")
def save_automation(
    request: Request,
    auto_send_invoices: str = Form(""),
    session: Session = Depends(database),
) -> Response:
    settings = settings_of(session)
    settings.auto_send_invoices = bool(auto_send_invoices)
    session.add(settings)
    return notice_redirect(request, "/einstellungen", "Automatik gespeichert.")


@router.post("/einstellungen/zahlungsziel")
def save_payment_terms(
    request: Request,
    payment_days: int = Form(...),
    session: Session = Depends(database),
) -> Response:
    settings = settings_of(session)
    settings.payment_days = max(0, min(payment_days, PAYMENT_DAYS_MAXIMUM))
    session.add(settings)
    return notice_redirect(request, "/einstellungen", "Zahlungsziel gespeichert.")


@router.post("/einstellungen/erinnerungen")
def save_reminders(
    request: Request,
    reminder_minutes: int = Form(...),
    session: Session = Depends(database),
) -> Response:
    settings = settings_of(session)
    settings.reminder_minutes = max(0, min(reminder_minutes, REMINDER_MINUTES_MAXIMUM))
    session.add(settings)
    return notice_redirect(request, "/einstellungen", "Erinnerungen gespeichert.")


@router.post("/einstellungen/absender")
def save_issuer(
    name: str = Form(...),
    street: str = Form(...),
    city: str = Form(...),
    country: str = Form(...),
    bank: str = Form(...),
    iban: str = Form(...),
    bic: str = Form(...),
    tax_number: str = Form(...),
    email: str = Form(...),
    paypal: str = Form(...),
    session: Session = Depends(database),
) -> Response:
    issuer = session.exec(select(Issuer)).first() or Issuer(
        name=name,
        street=street,
        city=city,
        bank=bank,
        iban=iban,
        bic=bic,
        tax_number=tax_number,
        email=email,
        paypal=paypal,
    )
    issuer.name = name
    issuer.street = street
    issuer.city = city
    issuer.country = country
    issuer.bank = bank
    issuer.iban = iban
    issuer.bic = bic
    issuer.tax_number = tax_number
    issuer.email = email
    issuer.paypal = paypal
    session.add(issuer)
    return RedirectResponse("/einstellungen", status_code=303)


@router.post("/einstellungen/email")
def save_mail_account(
    request: Request,
    smtp_host: str = Form(""),
    smtp_port: int = Form(587),
    smtp_user: str = Form(""),
    smtp_password: str = Form(""),
    smtp_from: str = Form(""),
    session: Session = Depends(database),
) -> Response:
    settings = settings_of(session)
    settings.smtp_host = smtp_host.strip() or None
    settings.smtp_port = smtp_port
    settings.smtp_user = smtp_user.strip() or None
    if smtp_password.strip():
        settings.smtp_password = smtp_password.strip()
    settings.smtp_from = smtp_from.strip() or None
    session.add(settings)
    return notice_redirect(
        request, "/einstellungen", "E-Mail-Einstellungen gespeichert."
    )


@router.post("/einstellungen/email-loeschen")
def forget_mail_account(
    request: Request, session: Session = Depends(database)
) -> Response:
    """Remove the whole SMTP account, the stored password included."""
    settings = settings_of(session)
    settings.smtp_host = None
    settings.smtp_user = None
    settings.smtp_password = None
    settings.smtp_from = None
    session.add(settings)
    return notice_redirect(request, "/einstellungen", "Zugangsdaten gelöscht.")


@router.post("/einstellungen/email-test")
def send_test_invoice(
    request: Request, to: str = Form(...), session: Session = Depends(database)
) -> Response:
    """Render the sample invoice and send it to the given address."""
    settings = settings_of(session)
    if not mail.is_configured(settings):
        return notice_redirect(
            request,
            "/einstellungen",
            "Der E-Mail-Versand ist noch nicht eingerichtet. Trage Server, "
            "Benutzername und Passwort ein und speichere zuerst.",
        )
    issuer = _real_issuer(session)
    try:
        with TemporaryDirectory() as folder:
            pdf = write_pdf(
                sample_invoice(issuer),
                Path(folder) / "Testrechnung.pdf",
            )
            mail.send_pdf(
                settings,
                sender_name=issuer.address.name if issuer else "",
                to=to.strip(),
                subject="Testrechnung aus dem Rechnungsersteller",
                body=(
                    "Guten Tag,\n\n"
                    "dies ist eine Testrechnung mit erfundenen Daten. Wenn sie "
                    "ankommt, ist der E-Mail-Versand fertig eingerichtet.\n"
                ),
                pdf=pdf,
            )
    except mail.MailError as error:
        return notice_redirect(request, "/einstellungen", str(error))
    return notice_redirect(
        request, "/einstellungen", f"Testrechnung an {to} geschickt."
    )


def _real_issuer(session: Session) -> document.Issuer | None:
    """The stored sender details, so the test invoice looks like a real one.

    None when the settings screen has not been filled in yet; the sample then
    falls back to its invented sender.
    """
    stored = session.exec(select(Issuer)).first()
    return None if stored is None else domain_issuer(stored)


@router.post("/einstellungen/nummern")
def save_numbering(
    request: Request,
    next_number: int = Form(...),
    session: Session = Depends(database),
) -> Response:
    """Move the sequence so the next release gets exactly this number."""
    state = session.exec(select(NumberState)).first() or NumberState(start=next_number)
    sequence = sequence_of(state)
    try:
        sequence.restart_at(next_number)
    except ValueError:
        return notice_redirect(
            request,
            "/einstellungen",
            f"Nummer {next_number} ist schon vergeben — zuletzt: "
            f"{state.last_assigned}. Es geht erst ab {sequence.peek()} weiter.",
        )
    state.start = sequence.start
    session.add(state)
    return notice_redirect(
        request, "/einstellungen", f"Die nächste Rechnung bekommt Nummer {next_number}."
    )


@router.post("/einstellungen/ablage")
def save_filing(
    invoice_folder: str = Form(...),
    lesson_horizon_days: int = Form(...),
    session: Session = Depends(database),
) -> Response:
    settings = settings_of(session)
    settings.invoice_folder = invoice_folder
    settings.lesson_horizon_days = lesson_horizon_days
    session.add(settings)
    return RedirectResponse("/einstellungen", status_code=303)


@router.post("/einstellungen/passwort")
def change_password(
    request: Request, password: str = Form(...), session: Session = Depends(database)
) -> Response:
    """Ask the mailbox before the password changes.

    Without a working mail account the change happens directly — otherwise a
    broken SMTP setting would lock the password forever.
    """
    settings = settings_of(session)
    if not mail.is_configured(settings) or not security.is_configured(session):
        security.set_password(session, password)
        return notice_redirect(request, "/einstellungen", "Passwort geändert.")
    code = security.request_password_change(session, password)
    recipient = mailbox_address_of(settings)
    try:
        mail.send_text(
            settings,
            to=recipient,
            subject="Bestätigungscode für die Passwortänderung",
            body=(
                "Guten Tag,\n\n"
                f"der Code lautet: {code}\n\n"
                "Er gilt 15 Minuten. Wenn du keine Passwortänderung angestoßen "
                "hast, ändere das Passwort der Anwendung.\n"
            ),
        )
    except mail.MailError as error:
        security.cancel_password_change(session)
        return notice_redirect(request, "/einstellungen", str(error))
    return notice_redirect(request, "/einstellungen", f"Code an {recipient} geschickt.")


@router.post("/einstellungen/passwort-bestaetigen")
def confirm_password(
    request: Request, code: str = Form(...), session: Session = Depends(database)
) -> Response:
    if security.confirm_password_change(session, code):
        return notice_redirect(request, "/einstellungen", "Passwort geändert.")
    return notice_redirect(
        request,
        "/einstellungen",
        "Der Code stimmt nicht oder ist abgelaufen. Stoße die Änderung neu an.",
    )


@router.post("/einstellungen/passwort-abbrechen")
def abandon_password(
    request: Request, session: Session = Depends(database)
) -> Response:
    security.cancel_password_change(session)
    return notice_redirect(request, "/einstellungen", "Passwortänderung verworfen.")
