"""The work behind the settings screen."""

from __future__ import annotations

from datetime import date

from sqlmodel import Session, select

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
from invoicing.utils import ensure_backup_passphrase
from invoicing.web.security import PasswordGate
from invoicing.web.store_queries import StoreQueries


class SettingsService:
    """Reads and saves everything the settings screen offers."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._store = StoreQueries(session)

    def form_context(self) -> dict[str, object]:
        settings = self._store.app_settings()
        ensure_backup_passphrase(self._session, settings)
        numbering = self._session.exec(select(NumberState)).first()
        return {
            "issuer": self._session.exec(select(Issuer)).first(),
            "numbering": numbering,
            "next_number": (
                BillingRunOrchestrator.number_sequence_from_state(numbering).peek()
            ),
            "settings": settings,
            "states": GERMAN_FEDERAL_STATES,
            "chosen_states": HolidayCalendar.chosen_states(settings),
            "pending_password": PasswordGate(self._session).has_pending_change(),
        }

    def save_holidays(
        self, show_public_holidays: str, show_school_holidays: str, states: list[str]
    ) -> str:
        settings = self._store.app_settings()
        settings.show_public_holidays = bool(show_public_holidays)
        settings.show_school_holidays = bool(show_school_holidays)
        chosen = [code for code in states if code in GERMAN_FEDERAL_STATES]
        settings.holiday_states = ",".join(chosen)
        self._session.add(settings)
        if not (settings.show_school_holidays and chosen):
            return "Gespeichert."
        try:
            count = HolidayCalendar(self._session).refresh_school_holidays(
                chosen, date.today()
            )
        except HolidayFetchError as error:
            return f"Gespeichert, aber: {error}"
        return f"Gespeichert — {count} Ferienzeiträume geladen."

    def save_automation(self, auto_send_invoices: str) -> str:
        settings = self._store.app_settings()
        settings.auto_send_invoices = bool(auto_send_invoices)
        self._session.add(settings)
        return "Automatik gespeichert."

    def save_payment_terms(self, payment_days: int) -> str:
        settings = self._store.app_settings()
        settings.payment_days = max(0, min(payment_days, PAYMENT_DAYS_MAXIMUM))
        self._session.add(settings)
        return "Zahlungsziel gespeichert."

    def save_reminders(self, reminder_minutes: int) -> str:
        settings = self._store.app_settings()
        settings.reminder_minutes = max(
            0, min(reminder_minutes, REMINDER_MINUTES_MAXIMUM)
        )
        self._session.add(settings)
        return "Erinnerungen gespeichert."

    def save_issuer(
        self,
        name: str,
        street: str,
        city: str,
        country: str,
        bank: str,
        iban: str,
        bic: str,
        tax_number: str,
        email: str,
        paypal: str,
    ) -> None:
        issuer = self._session.exec(select(Issuer)).first() or Issuer(
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
        self._session.add(issuer)

    def save_mail_account(
        self,
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_password: str,
        smtp_from: str,
    ) -> str:
        settings = self._store.app_settings()
        settings.smtp_host = smtp_host.strip() or None
        settings.smtp_port = smtp_port
        settings.smtp_user = smtp_user.strip() or None
        if smtp_password.strip():
            settings.smtp_password = smtp_password.strip()
        settings.smtp_from = smtp_from.strip() or None
        self._session.add(settings)
        return "E-Mail-Einstellungen gespeichert."

    def forget_mail_account(self) -> str:
        """Remove the whole SMTP account, the stored password included."""
        settings = self._store.app_settings()
        settings.smtp_host = None
        settings.smtp_user = None
        settings.smtp_password = None
        settings.smtp_from = None
        self._session.add(settings)
        return "Zugangsdaten gelöscht."

    def send_test_invoice(self, to: str) -> str:
        """Render the sample invoice, send it to ``to`` and say how it went."""
        mailer = mail.mailer_for(self._store.app_settings())
        if not mailer.is_configured():
            return (
                "Der E-Mail-Versand ist noch nicht eingerichtet. Trage Server, "
                "Benutzername und Passwort ein und speichere zuerst."
            )
        issuer = self.stored_issuer_as_domain()
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
            return str(error)
        return f"Testrechnung an {to} geschickt."

    def stored_issuer_as_domain(self) -> DomainIssuer | None:
        """The stored sender details, so the test invoice looks like a real one.

        None when the settings screen has not been filled in yet; the sample
        then falls back to its invented sender.
        """
        stored = self._session.exec(select(Issuer)).first()
        return (
            None if stored is None else BillingRunOrchestrator.as_domain_issuer(stored)
        )

    def save_numbering(self, next_number: int) -> str:
        """Move the sequence so the next release gets exactly this number."""
        state = self._session.exec(select(NumberState)).first() or NumberState(
            start=next_number
        )
        sequence = BillingRunOrchestrator.number_sequence_from_state(state)
        try:
            sequence.restart_at(next_number)
        except ValueError:
            return (
                f"Nummer {next_number} ist schon vergeben — zuletzt: "
                f"{state.last_assigned}. Es geht erst ab {sequence.peek()} weiter."
            )
        state.start = sequence.start
        self._session.add(state)
        return f"Die nächste Rechnung bekommt Nummer {next_number}."

    def save_filing(self, invoice_folder: str, lesson_horizon_days: int) -> None:
        settings = self._store.app_settings()
        settings.invoice_folder = invoice_folder
        settings.lesson_horizon_days = lesson_horizon_days
        self._session.add(settings)
