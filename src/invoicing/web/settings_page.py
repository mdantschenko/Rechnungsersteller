"""Sender details, filing, numbering, the password and the mail account."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlmodel import Session
from starlette.responses import RedirectResponse, Response

from invoicing import mail
from invoicing.mail_error import MailError
from invoicing.utils import mailbox_address_of, notice_redirect
from invoicing.web.dependencies import database_session
from invoicing.web.password_gate import PasswordGate
from invoicing.web.settings_service import SettingsService
from invoicing.web.store_queries import StoreQueries
from invoicing.web.template_renderer import template_renderer

router = APIRouter()


@router.get("/einstellungen")
def settings_form(
    request: Request, session: Session = Depends(database_session)
) -> Response:
    return template_renderer.render(
        request, "settings.html", SettingsService(session).form_context()
    )


@router.post("/einstellungen/feiertage")
def save_holidays(
    request: Request,
    show_public_holidays: str = Form(""),
    show_school_holidays: str = Form(""),
    states: list[str] = Form([]),
    session: Session = Depends(database_session),
) -> Response:
    notice = SettingsService(session).save_holidays(
        show_public_holidays, show_school_holidays, states
    )
    return notice_redirect(request, "/einstellungen", notice)


@router.post("/einstellungen/automatik")
def save_automation(
    request: Request,
    auto_send_invoices: str = Form(""),
    session: Session = Depends(database_session),
) -> Response:
    notice = SettingsService(session).save_automation(auto_send_invoices)
    return notice_redirect(request, "/einstellungen", notice)


@router.post("/einstellungen/zahlungsziel")
def save_payment_terms(
    request: Request,
    payment_days: int = Form(...),
    session: Session = Depends(database_session),
) -> Response:
    notice = SettingsService(session).save_payment_terms(payment_days)
    return notice_redirect(request, "/einstellungen", notice)


@router.post("/einstellungen/erinnerungen")
def save_reminders(
    request: Request,
    reminder_minutes: int = Form(...),
    session: Session = Depends(database_session),
) -> Response:
    notice = SettingsService(session).save_reminders(reminder_minutes)
    return notice_redirect(request, "/einstellungen", notice)


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
    session: Session = Depends(database_session),
) -> Response:
    SettingsService(session).save_issuer(
        name, street, city, country, bank, iban, bic, tax_number, email, paypal
    )
    return RedirectResponse("/einstellungen", status_code=303)


@router.post("/einstellungen/email")
def save_mail_account(
    request: Request,
    smtp_host: str = Form(""),
    smtp_port: int = Form(587),
    smtp_user: str = Form(""),
    smtp_password: str = Form(""),
    smtp_from: str = Form(""),
    session: Session = Depends(database_session),
) -> Response:
    notice = SettingsService(session).save_mail_account(
        smtp_host, smtp_port, smtp_user, smtp_password, smtp_from
    )
    return notice_redirect(request, "/einstellungen", notice)


@router.post("/einstellungen/email-loeschen")
def forget_mail_account(
    request: Request, session: Session = Depends(database_session)
) -> Response:
    notice = SettingsService(session).forget_mail_account()
    return notice_redirect(request, "/einstellungen", notice)


@router.post("/einstellungen/email-test")
def send_test_invoice(
    request: Request, to: str = Form(...), session: Session = Depends(database_session)
) -> Response:
    notice = SettingsService(session).send_test_invoice(to)
    return notice_redirect(request, "/einstellungen", notice)


@router.post("/einstellungen/nummern")
def save_numbering(
    request: Request,
    next_number: int = Form(...),
    session: Session = Depends(database_session),
) -> Response:
    notice = SettingsService(session).save_numbering(next_number)
    return notice_redirect(request, "/einstellungen", notice)


@router.post("/einstellungen/ablage")
def save_filing(
    invoice_folder: str = Form(...),
    lesson_horizon_days: int = Form(...),
    session: Session = Depends(database_session),
) -> Response:
    SettingsService(session).save_filing(invoice_folder, lesson_horizon_days)
    return RedirectResponse("/einstellungen", status_code=303)


@router.post("/einstellungen/passwort")
def change_password(
    request: Request,
    password: str = Form(...),
    session: Session = Depends(database_session),
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
    request: Request,
    code: str = Form(...),
    session: Session = Depends(database_session),
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
    request: Request, session: Session = Depends(database_session)
) -> Response:
    PasswordGate(session).cancel_change()
    return notice_redirect(request, "/einstellungen", "Passwortänderung verworfen.")
