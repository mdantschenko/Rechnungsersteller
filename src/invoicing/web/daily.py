"""The morning round: what the server does by itself once a day.

From seven o'clock on, due invoices for e-mail customers leave on their own
when the switch in the settings is on — WhatsApp and paper stay a human decision.
Whatever cannot leave by itself is announced on the lock screen instead, and
an invoice that crossed its due date overnight announces itself once.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from sqlmodel import Session, select

from invoicing import mail
from invoicing.billing import BillingRunOrchestrator
from invoicing.constant import MORNING_ROUND_STARTS_AT, DeliverPushMessage
from invoicing.mail_error import MailError
from invoicing.pdf import InvoiceDocumentWriter
from invoicing.storage.models import AppSettings, InvoiceDelivery, IssuedInvoice
from invoicing.utils import (
    ensure_backup_passphrase,
    mailbox_address_of,
    sealed_sqlite_copy,
)
from invoicing.web.invoice_list_view import InvoiceListViewBuilder
from invoicing.web.invoice_mail_composer import InvoiceMailComposer
from invoicing.web.invoice_pdf_archive import InvoicePdfArchive


class MorningRound:
    """Sends, announces and backs up once per day through ``run``."""

    def __init__(
        self, session: Session, settings: AppSettings, deliver: DeliverPushMessage
    ) -> None:
        self._session = session
        self._settings = settings
        self._deliver = deliver

    def run(self, now: datetime) -> None:
        if (
            now.time() < MORNING_ROUND_STARTS_AT
            or self._settings.last_daily_round == now.date()
        ):
            return
        self._settings.last_daily_round = now.date()
        self._session.add(self._settings)
        sent, waiting = self._send_due_invoices(now.date())
        lines = []
        if sent:
            lines.append(f"{sent} Rechnung(en) automatisch per E-Mail verschickt")
        if waiting:
            lines.append(f"{waiting} Rechnung(en) fällig — warten auf dich")
        lines.extend(
            f"Nr. {record.number} ({name}) ist seit heute überfällig"
            for record, name in self._newly_overdue(now.date())
        )
        if self._mail_weekly_backup(now.date()):
            lines.append("Backup der Datenbank ans Postfach gemailt")
        if lines:
            self._deliver(
                {
                    "title": "Rechnungen",
                    "body": "\n".join(lines),
                    "tag": "morgenrunde",
                    "url": "/rechnungen",
                }
            )

    def _send_due_invoices(self, today: date) -> tuple[int, int]:
        sent = 0
        waiting = 0
        orchestrator = BillingRunOrchestrator(self._session)
        mailer = mail.mailer_for(self._settings)
        composer = InvoiceMailComposer(self._session)
        for run in InvoiceListViewBuilder(self._session).open_billing_runs(today):
            if run.invoice is None and not run.is_blocked:
                continue
            may_leave = (
                self._settings.auto_send_invoices
                and not run.is_blocked
                and run.invoice is not None
                and run.customer.delivery is InvoiceDelivery.EMAIL
                and run.customer.email
                and mailer.is_configured()
            )
            if not may_leave:
                waiting += 1
                continue
            released = orchestrator.release(run)
            self._session.flush()
            target = InvoicePdfArchive(self._session).pdf_path(
                released.record, run.customer.name
            )
            InvoiceDocumentWriter().write_pdf(released.document, target)
            try:
                mailer.send_pdf(
                    to=run.customer.email or "",
                    subject=f"Rechnung Nr. {released.record.number}",
                    body=composer.invoice_mail_body(released.record),
                    pdf=target,
                    sender_name=composer.issuer_name(),
                )
            except MailError:
                waiting += 1
                continue
            released.record.sent_on = today
            self._session.add(released.record)
            sent += 1
        return sent, waiting

    def _mail_weekly_backup(self, today: date) -> bool:
        """Mail the sealed database home every Monday.

        Losing the server must never mean losing the books.
        """
        if today.weekday() != 0 or self._settings.last_backup_mailed == today:
            return False
        mailer = mail.mailer_for(self._settings)
        if not mailer.is_configured():
            return False
        database = Path(str(self._session.get_bind().engine.url.database or ""))
        if not database.exists():
            return False
        self._settings.last_backup_mailed = today
        self._session.add(self._settings)
        passphrase = ensure_backup_passphrase(self._session, self._settings)
        try:
            mailer.send_attachment(
                to=mailbox_address_of(self._settings),
                subject=f"Datenbank-Backup {today:%d.%m.%Y}",
                body=(
                    "Guten Tag,\n\n"
                    "anbei die wöchentliche Kopie der Rechnungsdatenbank. Entpacken "
                    "mit dem Backup-Passwort aus den Einstellungen.\n"
                ),
                content=sealed_sqlite_copy(database, passphrase),
                file_name=f"invoicing-{today}.zip",
                subtype="zip",
            )
        except MailError:
            return False
        return True

    def _newly_overdue(self, today: date) -> list[tuple[IssuedInvoice, str]]:
        unpaid = self._session.exec(
            select(IssuedInvoice).where(IssuedInvoice.paid_on == None)  # noqa: E711
        ).all()
        return [
            (record, record.customer.name)
            for record in unpaid
            if record.days_overdue(self._settings.payment_days, today) == 1
        ]
