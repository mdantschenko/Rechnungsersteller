"""The morning round: what the server does by itself once a day.

From seven o'clock on, due invoices for e-mail customers leave on their own
when the switch in "Mehr" is on — WhatsApp and paper stay a human decision.
Whatever cannot leave by itself is announced on the lock screen instead, and
an invoice that crossed its due date overnight announces itself once.
"""

from __future__ import annotations

from datetime import date, datetime, time

from sqlmodel import Session, select

from invoicing import mail
from invoicing.alarms import Deliver
from invoicing.billing import release
from invoicing.pdf.invoice_document import write_pdf
from invoicing.storage.models import AppSettings, InvoiceDelivery, IssuedInvoice
from invoicing.web.invoices_page import (
    customer_names,
    due_runs,
    invoice_mail_body,
    issuer_name,
    pdf_path,
)

STARTS_AT = time(7, 0)


def morning_round(
    session: Session, settings: AppSettings, now: datetime, deliver: Deliver
) -> None:
    if now.time() < STARTS_AT or settings.last_daily_round == now.date():
        return
    settings.last_daily_round = now.date()
    session.add(settings)
    sent, waiting = _send_due_invoices(session, settings, now.date())
    lines = []
    if sent:
        lines.append(f"{sent} Rechnung(en) automatisch per E-Mail verschickt")
    if waiting:
        lines.append(f"{waiting} Rechnung(en) fällig — warten auf dich")
    lines.extend(
        f"Nr. {record.number} ({name}) ist seit heute überfällig"
        for record, name in _newly_overdue(session, settings, now.date())
    )
    if lines:
        deliver(
            {
                "title": "Rechnungen",
                "body": "\n".join(lines),
                "tag": "morgenrunde",
                "url": "/rechnungen",
            }
        )


def _send_due_invoices(
    session: Session, settings: AppSettings, today: date
) -> tuple[int, int]:
    sent = 0
    waiting = 0
    for run in due_runs(session, today):
        if run.invoice is None and not run.is_blocked:
            continue
        may_leave = (
            settings.auto_send_invoices
            and not run.is_blocked
            and run.invoice is not None
            and run.customer.delivery is InvoiceDelivery.EMAIL
            and run.customer.email
            and mail.is_configured(settings)
        )
        if not may_leave:
            waiting += 1
            continue
        released = release(session, run)
        session.flush()
        target = pdf_path(session, released.record, run.customer.name)
        write_pdf(released.document, target)
        try:
            mail.send_pdf(
                settings,
                to=run.customer.email or "",
                subject=f"Rechnung Nr. {released.record.number}",
                body=invoice_mail_body(session, released.record),
                pdf=target,
                sender_name=issuer_name(session),
            )
        except mail.MailError:
            waiting += 1
            continue
        released.record.sent_on = today
        session.add(released.record)
        sent += 1
    return sent, waiting


def _newly_overdue(
    session: Session, settings: AppSettings, today: date
) -> list[tuple[IssuedInvoice, str]]:
    names = customer_names(session)
    unpaid = session.exec(
        select(IssuedInvoice).where(IssuedInvoice.paid_on == None)  # noqa: E711
    ).all()
    return [
        (record, names.get(record.customer_id, "?"))
        for record in unpaid
        if (today - record.issued_on).days - settings.payment_days == 1
    ]
