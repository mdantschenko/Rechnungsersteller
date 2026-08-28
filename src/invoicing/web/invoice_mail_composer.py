"""The letters that travel with an invoice or ask for its payment.

A new invoice and an older unpaid one go out as one mail, so the customer
never gets two letters on the same day.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlmodel import Session, col, select

from invoicing.german_formatter import german_formatter
from invoicing.storage.models import Customer, IssuedInvoice, Issuer
from invoicing.web.store_queries import StoreQueries


class InvoiceMailComposer:
    """Writes the mail bodies around the stored invoice facts."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def issuer_name(self) -> str:
        issuer = self._session.exec(select(Issuer)).first()
        return issuer.name if issuer else ""

    def invoice_mail_body(
        self, record: IssuedInvoice, signature: str | None = None
    ) -> str:
        """The letter accompanying the invoice.

        ``signature`` may be preloaded so a page listing many invoices asks
        for the sender only once.
        """
        if signature is None:
            signature = self.issuer_name()
        customer = self._session.get(Customer, record.customer_id)
        if customer is not None and customer.mail_text:
            return self.fill_letter_placeholders(
                customer.mail_text, record, customer, signature
            )
        return self._letter_with_greeting_and_signature(
            f"anbei die Rechnung Nr. {record.number} über "
            f"{german_formatter.format_euro(record.printed_total)} für den Zeitraum "
            f"{german_formatter.format_german_date(record.period_printed_from)} bis "
            f"{german_formatter.format_german_date(record.period_printed_to)}.",
            signature,
        )

    def reminder_mail_body(self, record: IssuedInvoice, count: int) -> str:
        signature = self.issuer_name()
        customer = self._session.get(Customer, record.customer_id)
        if customer is not None and customer.reminder_text:
            text = self.fill_letter_placeholders(
                customer.reminder_text, record, customer, signature
            )
            return text.replace("{ANZAHL}", str(count))
        return self._letter_with_greeting_and_signature(
            f"dies ist die {count}. Zahlungserinnerung zur Rechnung Nr. "
            f"{record.number} über "
            f"{german_formatter.format_euro(record.printed_total)} "
            f"vom {german_formatter.format_german_date(record.issued_on)} — anbei "
            f"noch einmal als PDF. "
            f"Falls die Zahlung schon unterwegs ist, betrachte diese Nachricht "
            f"bitte als gegenstandslos.",
            signature,
        )

    def still_unpaid_and_overdue(
        self, record: IssuedInvoice, today: date
    ) -> list[IssuedInvoice]:
        """The customer's other invoices whose payment window has run out.

        These ride along with the new invoice instead of asking for their
        money in a letter of their own.
        """
        payment_days = StoreQueries(self._session).app_settings().payment_days
        others = self._session.exec(
            select(IssuedInvoice)
            .where(IssuedInvoice.customer_id == record.customer_id)
            .where(IssuedInvoice.id != record.id)
            .where(col(IssuedInvoice.paid_on).is_(None))
            .order_by(col(IssuedInvoice.number))
        ).all()
        return [
            other for other in others if other.days_overdue(payment_days, today) > 0
        ]

    def subject_for(
        self, record: IssuedInvoice, still_open: Sequence[IssuedInvoice]
    ) -> str:
        """The subject line, naming the open invoices that travel along."""
        if not still_open:
            return f"Rechnung Nr. {record.number}"
        if len(still_open) == 1:
            return (
                f"Rechnung Nr. {record.number} und offene Rechnung "
                f"Nr. {still_open[0].number}"
            )
        return f"Rechnung Nr. {record.number} und {len(still_open)} offene Rechnungen"

    def invoice_mail_with_open_invoices(
        self,
        record: IssuedInvoice,
        still_open: Sequence[IssuedInvoice],
        signature: str | None = None,
    ) -> str:
        """The invoice letter, followed by a note about what is still open.

        The note goes after the closing, as a postscript, so a customer's own
        letter keeps its wording and its signature stays at the end.
        """
        letter = self.invoice_mail_body(record, signature)
        if not still_open:
            return letter
        return f"{letter}\n{self.open_invoices_postscript(still_open)}"

    @staticmethod
    def open_invoices_postscript(still_open: Sequence[IssuedInvoice]) -> str:
        """The postscript listing every invoice that is still waiting."""
        named = ", ".join(
            f"Nr. {invoice.number} vom "
            f"{german_formatter.format_german_date(invoice.issued_on)} über "
            f"{german_formatter.format_euro(invoice.printed_total)}"
            for invoice in still_open
        )
        opening = (
            "P.S.: Offen ist außerdem noch die Rechnung "
            if len(still_open) == 1
            else "P.S.: Offen sind außerdem noch die Rechnungen "
        )
        closing = (
            "sie hängt ebenfalls an."
            if len(still_open) == 1
            else "sie hängen ebenfalls an."
        )
        return f"{opening}{named} — {closing}\n"

    def fill_letter_placeholders(
        self, text: str, record: IssuedInvoice, customer: Customer, signature: str
    ) -> str:
        """The customer's own letter, its placeholders replaced with the facts."""
        values = {
            "MONAT": german_formatter.months_covered(
                record.period_printed_from, record.period_printed_to
            ),
            "JAHR": str(record.period_printed_from.year),
            "BETRAG": german_formatter.format_euro(record.printed_total),
            "NUMMER": str(record.number),
            "ZEITRAUM": (
                f"{german_formatter.format_german_date(record.period_printed_from)} "
                f"bis "
                f"{german_formatter.format_german_date(record.period_printed_to)}"
            ),
            "NAME": customer.name,
            "SCHUELER": customer.pupil_name,
            "ABSENDER": signature,
        }
        for key, value in values.items():
            text = text.replace("{" + key + "}", value)
        return text

    @staticmethod
    def _letter_with_greeting_and_signature(message: str, signature: str) -> str:
        return f"Guten Tag,\n\n{message}\n\nMit freundlichen Grüßen\n{signature}\n"
