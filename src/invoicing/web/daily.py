"""The morning round: what the server does by itself once a day.

From seven o'clock on, due invoices for e-mail customers leave on their own
when the switch in "Mehr" is on — WhatsApp and paper stay a human decision.
Whatever cannot leave by itself is announced on the lock screen instead, and
an invoice that crossed its due date overnight announces itself once.
"""

from __future__ import annotations

import io
import secrets
import sqlite3
from datetime import date, datetime, time
from pathlib import Path
from tempfile import TemporaryDirectory

import pyzipper
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
    if _mail_weekly_backup(session, settings, now.date()):
        lines.append("Backup der Datenbank ans Postfach gemailt")
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


def _mail_weekly_backup(session: Session, settings: AppSettings, today: date) -> bool:
    """Mail the sealed database home every Monday; losing the server must
    never mean losing the books."""
    if today.weekday() != 0 or settings.last_backup_mailed == today:
        return False
    if not mail.is_configured(settings):
        return False
    database = Path(str(session.get_bind().engine.url.database or ""))
    if not database.exists():
        return False
    settings.last_backup_mailed = today
    if not settings.backup_passphrase:
        settings.backup_passphrase = secrets.token_urlsafe(12)
    session.add(settings)
    try:
        mail.send_attachment(
            settings,
            to=settings.smtp_from or settings.smtp_user or "",
            subject=f"Datenbank-Backup {today:%d.%m.%Y}",
            body=(
                "Guten Tag,\n\n"
                "anbei die wöchentliche Kopie der Rechnungsdatenbank. Entpacken "
                "mit dem Backup-Passwort aus den Einstellungen.\n"
            ),
            content=_sealed_copy(database, settings.backup_passphrase),
            file_name=f"invoicing-{today}.zip",
            subtype="zip",
        )
    except mail.MailError:
        return False
    return True


def _sealed_copy(database: Path, passphrase: str) -> bytes:
    with TemporaryDirectory() as folder:
        snapshot = Path(folder) / database.name
        source = sqlite3.connect(database)
        try:
            copy = sqlite3.connect(snapshot)
            try:
                source.backup(copy)
            finally:
                copy.close()
        finally:
            source.close()
        buffer = io.BytesIO()
        with pyzipper.AESZipFile(
            buffer, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES
        ) as archive:
            archive.setpassword(passphrase.encode())
            archive.write(snapshot, arcname=database.name)
        return buffer.getvalue()


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
