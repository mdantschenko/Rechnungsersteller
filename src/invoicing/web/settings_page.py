"""Sender details, filing, numbering, the password and the mail account."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from sqlmodel import Session, select
from starlette.responses import RedirectResponse, Response

from invoicing import mail
from invoicing.billing import BillingRunOrchestrator
from invoicing.constant import (
    GERMAN_FEDERAL_STATES,
    PAYMENT_DAYS_MAXIMUM,
    REMINDER_MINUTES_MAXIMUM,
)
from invoicing.data_classes import Issuer as DomainIssuer
from invoicing.feiertage import HolidayCalendar
from invoicing.holiday_fetch_error import HolidayFetchError
from invoicing.mail_error import MailError
from invoicing.pdf import InvoiceDocumentWriter
from invoicing.sample import SampleInvoice
from invoicing.storage.models import Issuer, NumberState
from invoicing.utils import (
    ensure_backup_passphrase,
    mailbox_address_of,
    notice_redirect,
)
from invoicing.web.page import database
from invoicing.web.security import PasswordGate
from invoicing.web.store_queries import StoreQueries
from invoicing.web.template_renderer import template_renderer

router = APIRouter()


@router.get("/einstellungen")
def settings_form(request: Request, session: Session = Depends(database)) -> Response:
    settings = StoreQueries(session).app_settings()
    ensure_backup_passphrase(session, settings)
    numbering = session.exec(select(NumberState)).first()
    return template_renderer.render(
        request,
        "settings.html",
        {
            "issuer": session.exec(select(Issuer)).first(),
            "numbering": numbering,
            "next_number": (
                BillingRunOrchestrator.number_sequence_from_state(numbering).peek()
            ),
            "settings": settings,
            "states": GERMAN_FEDERAL_STATES,
            "chosen_states": HolidayCalendar.chosen_states(settings),
            "pending_password": PasswordGate(session).has_pending_change(),
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
    settings = StoreQueries(session).app_settings()
    settings.show_public_holidays = bool(show_public_holidays)
    settings.show_school_holidays = bool(show_school_holidays)
    chosen = [code for code in states if code in GERMAN_FEDERAL_STATES]
    settings.holiday_states = ",".join(chosen)
    session.add(settings)
    if not (settings.show_school_holidays and chosen):
        return notice_redirect(request, "/einstellungen", "Gespeichert.")
    try:
        count = HolidayCalendar(session).refresh_school_holidays(chosen, date.today())
    except HolidayFetchError as error:
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
    settings = StoreQueries(session).app_settings()
    settings.auto_send_invoices = bool(auto_send_invoices)
    session.add(settings)
    return notice_redirect(request, "/einstellungen", "Automatik gespeichert.")


@router.post("/einstellungen/zahlungsziel")
def save_payment_terms(
    request: Request,
    payment_days: int = Form(...),
    session: Session = Depends(database),
) -> Response:
    settings = StoreQueries(session).app_settings()
    settings.payment_days = max(0, min(payment_days, PAYMENT_DAYS_MAXIMUM))
    session.add(settings)
    return notice_redirect(request, "/einstellungen", "Zahlungsziel gespeichert.")


@router.post("/einstellungen/erinnerungen")
def save_reminders(
    request: Request,
    reminder_minutes: int = Form(...),
    session: Session = Depends(database),
) -> Response:
    settings = StoreQueries(session).app_settings()
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
    settings = StoreQueries(session).app_settings()
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
    settings = StoreQueries(session).app_settings()
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
    mailer = mail.mailer_for(StoreQueries(session).app_settings())
    if not mailer.is_configured():
        return notice_redirect(
            request,
            "/einstellungen",
            "Der E-Mail-Versand ist noch nicht eingerichtet. Trage Server, "
            "Benutzername und Passwort ein und speichere zuerst.",
        )
    issuer = _real_issuer(session)
    try:
        mailer.send_attachment(
            sender_name=issuer.address.name if issuer else "",
            to=to.strip(),
            subject="Testrechnung aus dem Rechnungsersteller",
            body=(
                "Guten Tag,\n\n"
                "dies ist eine Testrechnung mit erfundenen Daten. Wenn sie "
                "ankommt, ist der E-Mail-Versand fertig eingerichtet.\n"
            ),
            content=InvoiceDocumentWriter().pdf_bytes(SampleInvoice.build(issuer)),
            file_name="Testrechnung.pdf",
            subtype="pdf",
            copy_into_sent=True,
        )
    except MailError as error:
        return notice_redirect(request, "/einstellungen", str(error))
    return notice_redirect(
        request, "/einstellungen", f"Testrechnung an {to} geschickt."
    )


def _real_issuer(session: Session) -> DomainIssuer | None:
    """The stored sender details, so the test invoice looks like a real one.

    None when the settings screen has not been filled in yet; the sample then
    falls back to its invented sender.
    """
    stored = session.exec(select(Issuer)).first()
    return None if stored is None else BillingRunOrchestrator.as_domain_issuer(stored)


@router.post("/einstellungen/nummern")
def save_numbering(
    request: Request,
    next_number: int = Form(...),
    session: Session = Depends(database),
) -> Response:
    """Move the sequence so the next release gets exactly this number."""
    state = session.exec(select(NumberState)).first() or NumberState(start=next_number)
    sequence = BillingRunOrchestrator.number_sequence_from_state(state)
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
    settings = StoreQueries(session).app_settings()
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
    settings = StoreQueries(session).app_settings()
    mailer = mail.mailer_for(settings)
    gate = PasswordGate(session)
    if not mailer.is_configured() or not gate.is_configured():
        gate.set_password(password)
        return notice_redirect(request, "/einstellungen", "Passwort geändert.")
    code = gate.request_change(password)
    recipient = mailbox_address_of(settings)
    try:
        mailer.send_text(
            to=recipient,
            subject="Bestätigungscode für die Passwortänderung",
            body=(
                "Guten Tag,\n\n"
                f"der Code lautet: {code}\n\n"
                "Er gilt 15 Minuten. Wenn du keine Passwortänderung angestoßen "
                "hast, ändere das Passwort der Anwendung.\n"
            ),
        )
    except MailError as error:
        gate.cancel_change()
        return notice_redirect(request, "/einstellungen", str(error))
    return notice_redirect(request, "/einstellungen", f"Code an {recipient} geschickt.")


@router.post("/einstellungen/passwort-bestaetigen")
def confirm_password(
    request: Request, code: str = Form(...), session: Session = Depends(database)
) -> Response:
    if PasswordGate(session).confirm_change(code):
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
    PasswordGate(session).cancel_change()
    return notice_redirect(request, "/einstellungen", "Passwortänderung verworfen.")
