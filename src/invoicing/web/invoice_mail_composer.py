"""The letters that travel with an invoice or ask for its payment.

A new invoice and an older unpaid one go out as one mail, so the customer
never gets two letters on the same day. A customer's own letter may say
where the older invoice is mentioned; otherwise a postscript says it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlmodel import Session, col, select

from invoicing.data_classes import InvoiceMailToSend
from invoicing.german_formatter import german_formatter
from invoicing.storage.models import Customer, IssuedInvoice, Issuer
from invoicing.utils import replace_placeholders_once
from invoicing.web.open_invoices_in_the_letter import OpenInvoicesInTheLetter
from invoicing.web.store_queries import StoreQueries


class InvoiceMailComposer:
    """Writes the mail bodies around the stored invoice facts."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def issuer_name(self) -> str:
        issuer = self._session.exec(select(Issuer)).first()
        return issuer.name if issuer else ""

    def mail_to_send(
        self, record: IssuedInvoice, today: date, signature: str | None = None
    ) -> InvoiceMailToSend:
        """Everything one invoice mail needs, wherever it is sent from.

        A letter that mentions the open invoices itself carries all of them;
        a letter that does not keeps the postscript about the overdue ones.
        """
        still_unpaid = self.still_unpaid(record)
        if OpenInvoicesInTheLetter.is_spoken_about_in(self.customer_letter(record)):
            rides_along: Sequence[IssuedInvoice] = still_unpaid
            body = self.invoice_mail_body(record, signature, rides_along)
        else:
            rides_along = self.overdue_among(still_unpaid, today)
            body = self.invoice_mail_with_open_invoices(record, rides_along, signature)
        return InvoiceMailToSend(
            subject=self.subject_for(record, rides_along),
            body=body,
            rides_along=tuple(rides_along),
            to_note_as_reminded=tuple(self.overdue_among(rides_along, today)),
        )

    def customer_letter(self, record: IssuedInvoice) -> str:
        """The letter this customer wrote for their invoices, empty if none."""
        customer = self._session.get(Customer, record.customer_id)
        return customer.mail_text if customer and customer.mail_text else ""

    def invoice_mail_body(
        self,
        record: IssuedInvoice,
        signature: str | None = None,
        still_open: Sequence[IssuedInvoice] = (),
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
                customer.mail_text, record, customer, signature, still_open
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
            return self.fill_letter_placeholders(
                customer.reminder_text,
                record,
                customer,
                signature,
                self.still_unpaid(record),
                count,
            )
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

    def reminder_to_send(
        self, record: IssuedInvoice, count: int, today: date
    ) -> InvoiceMailToSend:
        """Everything one payment reminder needs.

        A reminder speaks for every unpaid invoice of the customer, so one
        reminder covers them all and none is left without one. A letter that
        names the open invoices itself places them; any other letter gets a
        postscript listing them.
        """
        still_open = self.still_unpaid(record)
        body = self.reminder_mail_body(record, count)
        names_them_itself = OpenInvoicesInTheLetter.is_spoken_about_in(
            self.customer_reminder_letter(record)
        )
        if still_open and not names_them_itself:
            body = f"{body}\n{self.open_invoices_postscript(still_open)}"
        return InvoiceMailToSend(
            subject=self.reminder_subject_for(record, still_open),
            body=body,
            rides_along=tuple(still_open),
            to_note_as_reminded=(record, *self.overdue_among(still_open, today)),
        )

    def customer_reminder_letter(self, record: IssuedInvoice) -> str:
        """The reminder letter this customer wrote, empty if none."""
        customer = self._session.get(Customer, record.customer_id)
        return customer.reminder_text if customer and customer.reminder_text else ""

    @staticmethod
    def reminder_subject_for(
        record: IssuedInvoice, still_open: Sequence[IssuedInvoice]
    ) -> str:
        """The subject line, naming every invoice the reminder speaks for."""
        if not still_open:
            return f"Zahlungserinnerung zur Rechnung Nr. {record.number}"
        numbers = sorted(invoice.number for invoice in (record, *still_open))
        named = ", ".join(str(number) for number in numbers[:-1])
        return f"Zahlungserinnerung zu den Rechnungen Nr. {named} und {numbers[-1]}"

    def still_unpaid(self, record: IssuedInvoice) -> list[IssuedInvoice]:
        """The customer's other invoices that nobody has paid yet.

        Whether their payment window has run out does not matter here; only
        the payment reminders care about that.
        """
        return list(
            self._session.exec(
                select(IssuedInvoice)
                .where(IssuedInvoice.customer_id == record.customer_id)
                .where(IssuedInvoice.id != record.id)
                .where(col(IssuedInvoice.paid_on).is_(None))
                .order_by(col(IssuedInvoice.number))
            ).all()
        )

    def overdue_among(
        self, invoices: Sequence[IssuedInvoice], today: date
    ) -> list[IssuedInvoice]:
        """Those of the invoices whose payment window has run out."""
        payment_days = StoreQueries(self._session).app_settings().payment_days
        return [
            invoice
            for invoice in invoices
            if invoice.days_overdue(payment_days, today) > 0
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
        letter = self.invoice_mail_body(record, signature, still_open)
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
        self,
        text: str,
        record: IssuedInvoice,
        customer: Customer,
        signature: str,
        still_open: Sequence[IssuedInvoice] = (),
        reminder_count: int | None = None,
    ) -> str:
        """The customer's own letter, its placeholders replaced with the facts.

        The conditional block is settled first, so a filled-in value can never
        be mistaken for a marker or for a placeholder of its own.
        """
        open_invoices = OpenInvoicesInTheLetter(still_open)
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
            **open_invoices.placeholder_values(record.printed_total),
        }
        if reminder_count is not None:
            values["ANZAHL"] = str(reminder_count)
        settled = open_invoices.one_line_per_invoice(open_invoices.resolved(text))
        return replace_placeholders_once(settled, values)

    @staticmethod
    def _letter_with_greeting_and_signature(message: str, signature: str) -> str:
        return f"Guten Tag,\n\n{message}\n\nMit freundlichen Grüßen\n{signature}\n"
