"""Everything the invoice list shows, gathered in one place."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlmodel import Session, col, select

from invoicing.billing import BillingRunOrchestrator
from invoicing.data_classes import BillingRun, OpenInvoicesOfOneCustomer
from invoicing.storage.models import (
    Customer,
    CustomerStatus,
    InvoiceDelivery,
    IssuedInvoice,
    PaymentReminder,
)
from invoicing.utils import sum_of_cents, whatsapp_number
from invoicing.web.earnings import EarningsLedger
from invoicing.web.invoice_mail_composer import InvoiceMailComposer
from invoicing.web.store_queries import StoreQueries


class InvoiceListViewBuilder:
    """Builds the template context of the invoices page."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._store = StoreQueries(session)

    def open_billing_runs(self, today: date) -> list[BillingRun]:
        active = (
            select(Customer)
            .where(Customer.status == CustomerStatus.ACTIVE)
            .where(Customer.delivery != InvoiceDelivery.NONE)
            .order_by(col(Customer.name))
        )
        orchestrator = BillingRunOrchestrator(self._session)
        return [
            run
            for customer in self._session.exec(active).all()
            for run in orchestrator.open_runs(customer, today)
        ]

    def list_context(self) -> dict[str, object]:
        today = date.today()
        everyone = self._session.exec(select(Customer)).all()
        issued = self._session.exec(
            select(IssuedInvoice).order_by(col(IssuedInvoice.number).desc())
        ).all()
        unpaid = [record for record in issued if record.paid_on is None]
        paid = [record for record in issued if record.paid_on is not None]
        still_listed = [
            record for record in paid if record.taken_off_the_list_on is None
        ]
        composer = InvoiceMailComposer(self._session)
        signature = composer.issuer_name()
        earnings_rows, earnings_total = EarningsLedger(self._session).monthly_earnings()
        settings = self._store.app_settings()
        return {
            "today": today,
            "due": self.open_billing_runs(today),
            "issued": unpaid,
            "paid": still_listed,
            "hidden_paid_count": len(paid) - len(still_listed),
            "reminders": self._reminder_days(),
            "mail_bodies": {
                record.number: composer.invoice_mail_body(
                    record, signature, composer.still_unpaid(record)
                )
                for record in unpaid
            },
            "names": {customer.id or 0: customer.name for customer in everyone},
            "deliveries": {
                customer.id or 0: customer.delivery.value for customer in everyone
            },
            "whatsapp": {
                customer.id or 0: whatsapp_number(customer.phone)
                for customer in everyone
            },
            "customers": self._store.active_customers(),
            "earnings": earnings_rows,
            "earnings_total": earnings_total,
            "overdue": self._overdue_days(unpaid, settings.payment_days),
            "open_groups": self._open_invoices_by_customer(
                unpaid, self._overdue_days(unpaid, settings.payment_days)
            ),
            "paid_years": self._paid_years(issued),
            "issued_years": self._issued_years(issued),
            "datev_numbers_are_set": bool(
                settings.datev_advisor_number and settings.datev_client_number
            ),
        }

    def _reminder_days(self) -> dict[int, list[date]]:
        days: dict[int, list[date]] = {}
        rows = self._session.exec(
            select(PaymentReminder).order_by(col(PaymentReminder.sent_on))
        ).all()
        for row in rows:
            days.setdefault(row.invoice_id, []).append(row.sent_on)
        return days

    @staticmethod
    def _open_invoices_by_customer(
        unpaid: Sequence[IssuedInvoice], overdue: dict[int, int]
    ) -> list[OpenInvoicesOfOneCustomer]:
        """One card per customer, newest customer first, newest invoice first.

        The card's reminder is written about the oldest overdue invoice and
        speaks for the others, so no invoice ends up with a second reminder.
        """
        by_customer: dict[int, list[IssuedInvoice]] = {}
        for record in unpaid:
            by_customer.setdefault(record.customer_id, []).append(record)
        return [
            OpenInvoicesOfOneCustomer(
                customer_id=customer_id,
                invoices=tuple(invoices),
                open_total=sum_of_cents(record.printed_total for record in invoices),
                reminder_target=min(
                    (record for record in invoices if record.number in overdue),
                    key=lambda record: record.number,
                    default=None,
                ),
            )
            for customer_id, invoices in by_customer.items()
        ]

    @staticmethod
    def _overdue_days(unpaid: Sequence[IssuedInvoice], due_days: int) -> dict[int, int]:
        """Days past the due date, per unpaid invoice number."""
        today = date.today()
        late = {
            record.number: record.days_overdue(due_days, today) for record in unpaid
        }
        return {number: days for number, days in late.items() if days > 0}

    @staticmethod
    def _paid_years(issued: Sequence[IssuedInvoice]) -> list[int]:
        years = {record.paid_on.year for record in issued if record.paid_on is not None}
        return sorted(years, reverse=True)

    @staticmethod
    def _issued_years(issued: Sequence[IssuedInvoice]) -> list[int]:
        """The years the bookkeeping export knows, by invoice date."""
        return sorted({record.issued_on.year for record in issued}, reverse=True)
