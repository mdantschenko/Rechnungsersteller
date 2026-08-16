"""The database lookups that more than one page needs."""

from __future__ import annotations

from sqlmodel import Session, col, select

from invoicing.storage.models import (
    AppSettings,
    Customer,
    CustomerStatus,
    IssuedInvoice,
    LessonSeries,
)
from invoicing.utils import recurrence_label


class StoreQueries:
    """Answers the questions every page asks the store."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def app_settings(self) -> AppSettings:
        """The single settings row.

        Raises:
            ValueError: if the application has not been set up yet.
        """
        settings = self._session.exec(select(AppSettings)).first()
        if settings is None:
            raise ValueError("the application has not been set up yet")
        return settings

    def customer(self, customer_id: int) -> Customer:
        """The customer behind an id.

        Raises:
            ValueError: if the id does not belong to anyone.
        """
        customer = self._session.get(Customer, customer_id)
        if customer is None:
            raise ValueError(f"no customer with id {customer_id}")
        return customer

    def active_customers(self) -> list[Customer]:
        """Everyone still taking lessons, A to Z."""
        statement = (
            select(Customer)
            .where(Customer.status == CustomerStatus.ACTIVE)
            .order_by(col(Customer.name))
        )
        return list(self._session.exec(statement).all())

    def series_labels(self) -> dict[int, str]:
        """What to print behind the repeat sign of a lesson born from a series."""
        return {
            entry.id or 0: recurrence_label(entry.recurrence)
            for entry in self._session.exec(select(LessonSeries)).all()
        }

    def issued_invoice_by_number(self, number: int) -> IssuedInvoice | None:
        return self._session.exec(
            select(IssuedInvoice).where(IssuedInvoice.number == number)
        ).first()

    def pupil_names_by_customer_id(self) -> dict[int, str]:
        """The pupil's name where one is set; the calendar is about the child."""
        return {
            customer.id or 0: customer.pupil_name
            for customer in self._session.exec(select(Customer)).all()
        }

    def lesson_places_by_customer_id(self) -> dict[int, str]:
        """What to print under the name: the lesson address, or Online."""
        return {
            customer.id or 0: customer.lesson_place
            for customer in self._session.exec(select(Customer)).all()
        }
