"""Turning ticked-off lessons into an invoice, and issuing it.

A lesson nobody has answered for blocks the run. Silence must never be read as
"it happened" or as "it did not"; the customer would be charged for a lesson
that never took place, or a taught lesson would quietly go unpaid.

The number is handed out at release, not while a draft is being looked at, so
a draft that is thrown away leaves no gap in the numbering.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from dateutil.relativedelta import relativedelta
from sqlmodel import Session, col, select

from invoicing.constant import CLOSING_DAY_OF_MONTH, ONE_DAY
from invoicing.data_classes import (
    Address,
    BillingPeriod,
    BillingRun,
    ExtraColumn,
    ExtraColumnValue,
    Invoice,
    Issuer,
    ReleasedInvoice,
)
from invoicing.domain.billing_period import BillingCalendar
from invoicing.domain.extra_column_rules import ExtraColumnRules
from invoicing.domain.invoice import InvoiceBuilder
from invoicing.domain.invoice_numbers import NumberSequence
from invoicing.lesson_pricing import StoredLessonPricer
from invoicing.storage import models


class BillingRunOrchestrator:
    """Collects a customer's lessons into billing runs and releases them."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def draft_for(
        self, customer: models.Customer, closing_day: date, issued_on: date
    ) -> BillingRun:
        """Collect a customer's lessons for the period closing on ``closing_day``."""
        terms = self._billing_template_of(customer)
        period = BillingCalendar(terms.cycle).period_closing_on(closing_day)
        return self._collect_run(customer, terms, period, closing_day, issued_on)

    def manual_draft(
        self,
        customer: models.Customer,
        first_day: date,
        last_day: date,
        issued_on: date,
    ) -> BillingRun:
        """Collect the lessons of a hand-picked stretch, outside any cycle."""
        terms = self._billing_template_of(customer)
        period = BillingPeriod(
            printed_from=first_day, first_day=first_day, last_day=last_day
        )
        return self._collect_run(customer, terms, period, last_day, issued_on)

    def open_runs(self, customer: models.Customer, today: date) -> list[BillingRun]:
        """Every closed period that still holds lessons, oldest first.

        Missing a month must not strand the lessons before it, so the search
        starts at the oldest lesson that has not been billed rather than at
        the period that closed most recently.
        """
        oldest = self._oldest_unbilled(customer)
        if oldest is None:
            return []
        calendar = BillingCalendar(self._billing_template_of(customer).cycle)
        latest = self.last_closing_day(customer, today)
        closing = calendar.next_closing_day(calendar.period_containing(oldest).last_day)
        runs: list[BillingRun] = []
        while closing <= latest:
            run = self.draft_for(customer, closing, today)
            if run.billable or run.unanswered:
                runs.append(run)
            closing = calendar.next_closing_day(closing + ONE_DAY)
        return runs

    def last_closing_day(self, customer: models.Customer, today: date) -> date:
        """The most recent day up to ``today`` that closed this customer's period."""
        day_of_month = CLOSING_DAY_OF_MONTH[self._billing_template_of(customer).cycle]
        if today.day >= day_of_month:
            return today.replace(day=day_of_month)
        return (today - relativedelta(months=1)).replace(day=day_of_month)

    def release(self, run: BillingRun) -> ReleasedInvoice:
        """Give the draft its number, freeze it, and mark its lessons as billed.

        Raises:
            ValueError: if the run produced no draft to release.
        """
        if run.invoice is None:
            raise ValueError(
                f"nothing to release for {run.customer.name}: "
                f"{len(run.unanswered)} lessons still unanswered"
            )
        issued = replace(run.invoice, number=self._take_next_number())
        record = self._as_record(issued, run.customer)
        self.session.add(record)
        self.session.flush()
        for lesson in run.billable:
            lesson.invoice_id = record.id
            self.session.add(lesson)
        return ReleasedInvoice(document=issued, record=record)

    @staticmethod
    def as_domain_issuer(stored: models.Issuer) -> Issuer:
        """The stored sender details as the domain issuer a document prints."""
        return Issuer(
            address=Address(name=stored.name, street=stored.street, city=stored.city),
            country=stored.country,
            bank=stored.bank,
            iban=stored.iban,
            bic=stored.bic,
            tax_number=stored.tax_number,
            email=stored.email,
            paypal=stored.paypal,
        )

    @staticmethod
    def number_sequence_from_state(state: models.NumberState | None) -> NumberSequence:
        """The numbering as a domain sequence; a missing row starts at one."""
        if state is None:
            return NumberSequence(start=1)
        return NumberSequence(start=state.start, last_assigned=state.last_assigned)

    def _collect_run(
        self,
        customer: models.Customer,
        terms: models.BillingTemplate,
        period: BillingPeriod,
        closing_day: date,
        issued_on: date,
    ) -> BillingRun:
        lessons = self._lessons_in(customer, period)
        unanswered = tuple(
            lesson for lesson in lessons if lesson.status is models.LessonStatus.PLANNED
        )
        billable = tuple(
            lesson for lesson in lessons if lesson.status is models.LessonStatus.DONE
        )
        return BillingRun(
            customer=customer,
            closing_day=closing_day,
            period=period,
            invoice=(
                None
                if unanswered or not billable
                else self._build(customer, terms, period, billable, issued_on)
            ),
            unanswered=unanswered,
            billable=billable,
        )

    def _build(
        self,
        customer: models.Customer,
        terms: models.BillingTemplate,
        period: BillingPeriod,
        billable: tuple[models.Lesson, ...],
        issued_on: date,
    ) -> Invoice:
        pricer = StoredLessonPricer(terms)
        return InvoiceBuilder(pricer.as_domain_terms()).build_invoice(
            number=self._peek_next_number(),
            issued_on=issued_on,
            issuer=self._issuer_of(),
            recipient=Address(
                name=customer.name, street=customer.street, city=customer.city
            ),
            period=period,
            lessons=[pricer.as_domain_lesson(lesson) for lesson in billable],
        )

    def _lessons_in(
        self, customer: models.Customer, period: BillingPeriod
    ) -> tuple[models.Lesson, ...]:
        statement = (
            select(models.Lesson)
            .where(models.Lesson.customer_id == customer.id)
            .where(models.Lesson.invoice_id == None)  # noqa: E711
            .where(models.Lesson.taught_on >= period.first_day)
            .where(models.Lesson.taught_on <= period.last_day)
        )
        return tuple(
            sorted(
                self.session.exec(statement).all(),
                key=lambda lesson: lesson.taught_on,
            )
        )

    def _billing_template_of(self, customer: models.Customer) -> models.BillingTemplate:
        terms = self.session.exec(
            select(models.BillingTemplate).where(
                models.BillingTemplate.customer_id == customer.id
            )
        ).first()
        if terms is None:
            raise ValueError(f"{customer.name} has no billing template yet")
        return terms

    def _issuer_of(self) -> Issuer:
        issuer = self.session.exec(select(models.Issuer)).first()
        if issuer is None:
            raise ValueError("the sender details have not been filled in yet")
        return self.as_domain_issuer(issuer)

    def _oldest_unbilled(self, customer: models.Customer) -> date | None:
        statement = (
            select(models.Lesson)
            .where(models.Lesson.customer_id == customer.id)
            .where(models.Lesson.invoice_id == None)  # noqa: E711
            .where(models.Lesson.status != models.LessonStatus.CANCELLED)
            .order_by(col(models.Lesson.taught_on))
        )
        lesson = self.session.exec(statement).first()
        return None if lesson is None else lesson.taught_on

    def _sequence(self) -> tuple[NumberSequence, models.NumberState]:
        state = self.session.exec(select(models.NumberState)).first()
        if state is None:
            state = models.NumberState(start=1)
            self.session.add(state)
            self.session.flush()
        return self.number_sequence_from_state(state), state

    def _peek_next_number(self) -> int:
        sequence, _ = self._sequence()
        return sequence.peek()

    def _take_next_number(self) -> int:
        sequence, state = self._sequence()
        number = sequence.assign()
        state.last_assigned = number
        self.session.add(state)
        return number

    def _as_record(
        self, issued: Invoice, customer: models.Customer
    ) -> models.IssuedInvoice:
        return models.IssuedInvoice(
            number=issued.number,
            customer_id=self._identity_of(customer),
            issued_on=issued.issued_on,
            period_printed_from=issued.period.printed_from,
            period_printed_to=issued.period.last_day,
            column_labels=[column.label for column in issued.columns],
            printed_total=issued.total,
            computed_total=issued.total,
            paid_on=issued.paid_on,
            lines=[
                models.IssuedInvoiceLine(
                    ordinal=ordinal,
                    taught_on=item.taught_on,
                    quantity=item.quantity,
                    unit=item.unit,
                    description=item.description,
                    unit_price=item.unit_price,
                    extra_values=self._printed_extras(
                        issued.columns, item.column_values
                    ),
                    total=item.total,
                )
                for ordinal, item in enumerate(issued.line_items)
            ],
        )

    def _printed_extras(
        self,
        columns: tuple[ExtraColumn, ...],
        values: tuple[ExtraColumnValue, ...],
    ) -> dict[str, str]:
        return {
            column.label: ExtraColumnRules(column).display(value)
            for column, value in zip(columns, values, strict=True)
        }

    def _identity_of(self, customer: models.Customer) -> int:
        if customer.id is None:
            raise ValueError(
                f"customer {customer.name} was not written to the database"
            )
        return customer.id
