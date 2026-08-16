"""The letters that travel with an invoice or ask for its payment."""

from __future__ import annotations

from sqlmodel import Session, select

from invoicing.german_formatter import german_formatter
from invoicing.storage.models import Customer, IssuedInvoice, Issuer


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
        """The letter accompanying the invoice; ``signature`` may be preloaded
        so a page listing many invoices asks for the sender only once."""
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

    def fill_letter_placeholders(
        self, text: str, record: IssuedInvoice, customer: Customer, signature: str
    ) -> str:
        """The customer's own letter, its placeholders replaced with the facts."""
        values = {
            "MONAT": german_formatter.month_name(record.period_printed_from),
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
