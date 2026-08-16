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
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from sqlmodel import Session, col, select

from invoicing.constant import CLOSING_DAY_OF_MONTH, ONE_DAY, ValueKind
from invoicing.data_classes import (
    Address,
    BillingPeriod,
    BillingRun,
    ExtraColumn,
    ExtraColumnValue,
    Invoice,
    InvoiceTerms,
    Issuer,
    LineItem,
    ReleasedInvoice,
    TaughtLesson,
)
from invoicing.domain.billing_period import BillingCalendar
from invoicing.domain.extra_column_rules import ExtraColumnRules
from invoicing.domain.invoice import InvoiceBuilder
from invoicing.domain.invoice_numbers import NumberSequence
from invoicing.storage import models
from invoicing.utils import hours_per_unit, parse_german_amount, round_quantity


def draft_for(
    session: Session,
    customer: models.Customer,
    closing_day: date,
    issued_on: date,
) -> BillingRun:
    """Collect a customer's lessons for the period closing on ``closing_day``."""
    terms = _terms_of(session, customer)
    period = BillingCalendar(terms.cycle).period_closing_on(closing_day)
    return _run(session, customer, terms, period, closing_day, issued_on)


def manual_draft(
    session: Session,
    customer: models.Customer,
    first_day: date,
    last_day: date,
    issued_on: date,
) -> BillingRun:
    """Collect the lessons of a hand-picked stretch, outside any cycle."""
    terms = _terms_of(session, customer)
    period = BillingPeriod(
        printed_from=first_day, first_day=first_day, last_day=last_day
    )
    return _run(session, customer, terms, period, last_day, issued_on)


def _run(
    session: Session,
    customer: models.Customer,
    terms: models.BillingTemplate,
    period: BillingPeriod,
    closing_day: date,
    issued_on: date,
) -> BillingRun:
    lessons = _lessons_in(session, customer, period)
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
            else _build(session, customer, terms, period, billable, issued_on)
        ),
        unanswered=unanswered,
        billable=billable,
    )


def last_closing_day(session: Session, customer: models.Customer, today: date) -> date:
    """The most recent day up to ``today`` on which this customer's period closed."""
    day_of_month = CLOSING_DAY_OF_MONTH[_terms_of(session, customer).cycle]
    if today.day >= day_of_month:
        return today.replace(day=day_of_month)
    return (today - relativedelta(months=1)).replace(day=day_of_month)


def open_runs(
    session: Session, customer: models.Customer, today: date
) -> list[BillingRun]:
    """Every closed period that still holds lessons, oldest first.

    Missing a month must not strand the lessons before it, so the search starts
    at the oldest lesson that has not been billed rather than at the period
    that closed most recently.
    """
    oldest = _oldest_unbilled(session, customer)
    if oldest is None:
        return []
    calendar = BillingCalendar(_terms_of(session, customer).cycle)
    latest = last_closing_day(session, customer, today)
    closing = calendar.next_closing_day(calendar.period_containing(oldest).last_day)
    runs: list[BillingRun] = []
    while closing <= latest:
        run = draft_for(session, customer, closing, today)
        if run.billable or run.unanswered:
            runs.append(run)
        closing = calendar.next_closing_day(closing + ONE_DAY)
    return runs


def _oldest_unbilled(session: Session, customer: models.Customer) -> date | None:
    statement = (
        select(models.Lesson)
        .where(models.Lesson.customer_id == customer.id)
        .where(models.Lesson.invoice_id == None)  # noqa: E711
        .where(models.Lesson.status != models.LessonStatus.CANCELLED)
        .order_by(col(models.Lesson.taught_on))
    )
    lesson = session.exec(statement).first()
    return None if lesson is None else lesson.taught_on


def release(session: Session, run: BillingRun) -> ReleasedInvoice:
    """Give the draft its number, freeze it, and mark its lessons as billed.

    Raises:
        ValueError: if the run produced no draft to release.
    """
    if run.invoice is None:
        raise ValueError(
            f"nothing to release for {run.customer.name}: "
            f"{len(run.unanswered)} lessons still unanswered"
        )
    issued = replace(run.invoice, number=_take_next_number(session))
    record = _as_record(issued, run.customer)
    session.add(record)
    session.flush()
    for lesson in run.billable:
        lesson.invoice_id = record.id
        session.add(lesson)
    return ReleasedInvoice(document=issued, record=record)


def _build(
    session: Session,
    customer: models.Customer,
    terms: models.BillingTemplate,
    period: BillingPeriod,
    billable: tuple[models.Lesson, ...],
    issued_on: date,
) -> Invoice:
    return InvoiceBuilder(domain_template(terms)).build_invoice(
        number=_peek_next_number(session),
        issued_on=issued_on,
        issuer=_issuer_of(session),
        recipient=Address(
            name=customer.name, street=customer.street, city=customer.city
        ),
        period=period,
        lessons=[domain_lesson(terms, lesson) for lesson in billable],
    )


def domain_template(terms: models.BillingTemplate) -> InvoiceTerms:
    """The customer's stored terms as the domain template that prices rows."""
    return InvoiceTerms(
        unit_price=terms.unit_price,
        unit=terms.unit,
        description=terms.description,
        columns=stored_columns(terms),
    )


def domain_lesson(terms: models.BillingTemplate, lesson: models.Lesson) -> TaughtLesson:
    """The stored lesson as the domain lesson an invoice row is built from."""
    columns = stored_columns(terms)
    kinds = {column.label: column.kind for column in columns}
    return TaughtLesson(
        taught_on=lesson.taught_on,
        quantity=billable_quantity(terms, lesson),
        column_values=typed_values(kinds, lesson.column_values),
    )


def priced_line(terms: models.BillingTemplate, lesson: models.Lesson) -> LineItem:
    """One stored lesson priced exactly as its invoice row will be.

    The earnings view and the invoice must never disagree about what a
    lesson is worth, so both go through this one function.
    """
    return InvoiceBuilder(domain_template(terms)).build_line_item(
        domain_lesson(terms, lesson)
    )


def priced_columns(
    terms: models.BillingTemplate, lesson: models.Lesson
) -> tuple[tuple[ExtraColumn, ExtraColumnValue, Decimal], ...]:
    """Each extra column with its value and its share for this stored lesson."""
    return InvoiceBuilder(domain_template(terms)).column_shares(
        domain_lesson(terms, lesson)
    )


def billable_quantity(terms: models.BillingTemplate, lesson: models.Lesson) -> Decimal:
    """The lesson measured in the template's unit.

    The unit is arithmetic: "h" prices per hour, "1,5h" prices per ninety
    minutes, so a ninety-minute lesson is exactly one unit then.
    """
    return round_quantity(lesson.quantity / hours_per_unit(terms.unit))


def _lessons_in(
    session: Session, customer: models.Customer, period: BillingPeriod
) -> tuple[models.Lesson, ...]:
    statement = (
        select(models.Lesson)
        .where(models.Lesson.customer_id == customer.id)
        .where(models.Lesson.invoice_id == None)  # noqa: E711
        .where(models.Lesson.taught_on >= period.first_day)
        .where(models.Lesson.taught_on <= period.last_day)
    )
    return tuple(
        sorted(session.exec(statement).all(), key=lambda lesson: lesson.taught_on)
    )


def _terms_of(session: Session, customer: models.Customer) -> models.BillingTemplate:
    terms = session.exec(
        select(models.BillingTemplate).where(
            models.BillingTemplate.customer_id == customer.id
        )
    ).first()
    if terms is None:
        raise ValueError(f"{customer.name} has no billing template yet")
    return terms


def _issuer_of(session: Session) -> Issuer:
    issuer = session.exec(select(models.Issuer)).first()
    if issuer is None:
        raise ValueError("the sender details have not been filled in yet")
    return domain_issuer(issuer)


def domain_issuer(stored: models.Issuer) -> Issuer:
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


def stored_columns(terms: models.BillingTemplate) -> tuple[ExtraColumn, ...]:
    """The customer's extra columns as domain objects, defaults parsed."""
    return tuple(
        ExtraColumn(
            label=stored.label,
            source=stored.source,
            kind=stored.kind,
            total_rule=stored.total_rule,
            default_value=_typed(stored.kind, stored.default_value),
            placeholder=stored.placeholder,
        )
        for stored in terms.columns
    )


def typed_values(
    kinds: dict[str, ValueKind], raw: dict[str, str | None]
) -> dict[str, ExtraColumnValue]:
    return {
        label: _typed(kinds[label], value)
        for label, value in raw.items()
        if label in kinds
    }


def _typed(kind: ValueKind, value: str | None) -> ExtraColumnValue:
    if value is None:
        return None
    if kind is ValueKind.TEXT:
        return value
    # Stored values may carry a German comma or a stray currency sign from
    # older input; unreadable ones count as empty rather than crashing the
    # whole billing page.
    return parse_german_amount(value)


def sequence_of(state: models.NumberState | None) -> NumberSequence:
    """The numbering as a domain sequence; a missing row starts at one."""
    if state is None:
        return NumberSequence(start=1)
    return NumberSequence(start=state.start, last_assigned=state.last_assigned)


def _sequence(session: Session) -> tuple[NumberSequence, models.NumberState]:
    state = session.exec(select(models.NumberState)).first()
    if state is None:
        state = models.NumberState(start=1)
        session.add(state)
        session.flush()
    return sequence_of(state), state


def _peek_next_number(session: Session) -> int:
    sequence, _ = _sequence(session)
    return sequence.peek()


def _take_next_number(session: Session) -> int:
    sequence, state = _sequence(session)
    number = sequence.assign()
    state.last_assigned = number
    session.add(state)
    return number


def _as_record(issued: Invoice, customer: models.Customer) -> models.IssuedInvoice:
    return models.IssuedInvoice(
        number=issued.number,
        customer_id=_identity_of(customer),
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
                extra_values=_printed_extras(issued.columns, item.column_values),
                total=item.total,
            )
            for ordinal, item in enumerate(issued.line_items)
        ],
    )


def _printed_extras(
    columns: tuple[ExtraColumn, ...], values: tuple[ExtraColumnValue, ...]
) -> dict[str, str]:
    return {
        column.label: ExtraColumnRules(column).display(value)
        for column, value in zip(columns, values, strict=True)
    }


def _identity_of(customer: models.Customer) -> int:
    if customer.id is None:
        raise ValueError(f"customer {customer.name} was not written to the database")
    return customer.id
