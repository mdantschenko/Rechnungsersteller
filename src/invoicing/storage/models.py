"""The tables the application keeps its records in.

An issued invoice is stored exactly as it was printed, never reinterpreted.
Older documents contain mistakes, so nothing is quietly corrected on the way
in and nothing is derived from them. Where a document contradicts itself the
printed figure is kept and the recomputed one is kept beside it, which is what
lets the import report the difference instead of hiding it.
"""

# No "from __future__ import annotations" here: it would turn the relationship
# annotations into plain strings, which SQLAlchemy cannot resolve into classes.

from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Dialect, String, TypeDecorator
from sqlmodel import Column, Field, Relationship, SQLModel

from invoicing.domain.billing_period import BillingCycle
from invoicing.domain.columns import TotalRule, ValueKind, ValueSource


class ExactDecimal(TypeDecorator[Decimal]):
    """Stores a Decimal as text so that no value passes through a float.

    SQLite has no decimal column type, and SQLAlchemy's Numeric round-trips
    through float on this backend. That is precisely the precision loss the
    money module exists to avoid.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> str | None:
        return None if value is None else str(value)

    def process_result_value(
        self, value: str | None, dialect: Dialect
    ) -> Decimal | None:
        return None if value is None else Decimal(value)


def money_field(**keywords: Any) -> Any:
    return Field(sa_type=ExactDecimal, **keywords)


# The table names are spelled out rather than left to SQLModel, which would
# derive "issuedinvoiceline". SQLAlchemy declares __tablename__ as a
# declared_attr, so a plain string needs the pragma below.
class CustomerStatus(StrEnum):
    """Whether a customer still takes lessons."""

    ACTIVE = "active"
    ARCHIVED = "archived"
    """Kept only so their invoice history has an owner."""


class InvoiceDelivery(StrEnum):
    """How this customer's invoices leave the house."""

    EMAIL = "email"
    WHATSAPP = "whatsapp"
    NONE = "none"
    """No invoice at all: the lessons serve as a reminder only."""


class Customer(SQLModel, table=True):
    """Someone invoices are addressed to."""

    __tablename__ = "customer"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    street: str
    city: str
    status: CustomerStatus = Field(default=CustomerStatus.ARCHIVED, index=True)
    email: str | None = None
    phone: str | None = None
    delivery: InvoiceDelivery = Field(default=InvoiceDelivery.EMAIL)

    student_name: str | None = None
    """The pupil, when the invoice goes to someone else, usually a parent."""
    student_grade: str | None = None
    lesson_address: str | None = None
    """Where the lessons happen, when that differs from the billing address."""
    reminder_at: time | None = None
    """When on the lesson day the phone should ring for this pupil. Empty
    falls back to the lead time on the settings screen."""
    online: bool = False
    """Lessons happen over video, so the calendar shows no address."""
    mail_text: str | None = None
    """The letter accompanying this customer's invoices. May carry
    placeholders such as {MONAT} and {BETRAG}; empty falls back to the
    built-in wording."""

    invoices: list["IssuedInvoice"] = Relationship(back_populates="customer")


class IssuedInvoice(SQLModel, table=True):
    """An invoice that has been sent out and can no longer change."""

    __tablename__ = "issued_invoice"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    number: int = Field(index=True, unique=True)
    customer_id: int = Field(foreign_key="customer.id", index=True)
    issued_on: date
    period_printed_from: date
    period_printed_to: date
    column_labels: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    """The extra columns this invoice carried, in the order they were printed."""

    printed_total: Decimal = money_field()
    computed_total: Decimal = money_field()
    paid_on: date | None = None
    sent_on: date | None = None
    """When the invoice actually went out to the customer."""
    source_file: str | None = None

    customer: Customer = Relationship(back_populates="invoices")
    lines: list["IssuedInvoiceLine"] = Relationship(
        back_populates="invoice",
        sa_relationship_kwargs={"order_by": "IssuedInvoiceLine.ordinal"},
    )

    @property
    def totals_disagree(self) -> bool:
        """Whether the document contradicts the sum of its own rows."""
        return self.printed_total != self.computed_total


class IssuedInvoiceLine(SQLModel, table=True):
    """One row of an issued invoice, frozen with the document."""

    __tablename__ = "issued_invoice_line"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    invoice_id: int | None = Field(
        default=None, foreign_key="issued_invoice.id", index=True, nullable=False
    )
    """Filled in when the invoice it belongs to is written, never left empty."""

    ordinal: int
    taught_on: date
    quantity: Decimal = money_field()
    unit: str
    description: str
    unit_price: Decimal = money_field()
    extra_values: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    """What stood in each extra column, placeholders such as "/" included."""

    total: Decimal = money_field()

    invoice: IssuedInvoice = Relationship(back_populates="lines")


class PaymentReminder(SQLModel, table=True):
    """One payment reminder that went out for an unpaid invoice.

    Kept as rows rather than a counter, so the list can say which reminder
    it was and when each one was sent.
    """

    __tablename__ = "payment_reminder"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    invoice_id: int = Field(foreign_key="issued_invoice.id", index=True)
    sent_on: date


class Issuer(SQLModel, table=True):
    """The one row holding the sender details every invoice is printed with."""

    __tablename__ = "issuer"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    name: str
    street: str
    city: str
    country: str = "Deutschland"
    bank: str
    iban: str
    bic: str
    tax_number: str
    email: str
    paypal: str


class BillingTemplate(SQLModel, table=True):
    """How one customer's invoices are priced and worded."""

    __tablename__ = "billing_template"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="customer.id", unique=True, index=True)
    unit_price: Decimal = money_field()
    unit: str = "h"
    description: str = "Mathe Nachhilfe"
    cycle: BillingCycle = Field(default=BillingCycle.MONTH_START)

    columns: list["TemplateColumn"] = Relationship(
        back_populates="template",
        sa_relationship_kwargs={"order_by": "TemplateColumn.ordinal"},
    )


class TemplateColumn(SQLModel, table=True):
    """One extra column a customer's invoices carry."""

    __tablename__ = "template_column"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    template_id: int | None = Field(
        default=None, foreign_key="billing_template.id", index=True, nullable=False
    )
    ordinal: int
    label: str
    source: ValueSource = ValueSource.FIXED
    kind: ValueKind = ValueKind.MONEY
    total_rule: TotalRule = TotalRule.EXCLUDED
    default_value: str | None = None
    placeholder: str = "/"

    template: BillingTemplate = Relationship(back_populates="columns")


class LessonStatus(StrEnum):
    """Whether a lesson still needs an answer, happened, or fell through."""

    PLANNED = "planned"
    DONE = "done"
    CANCELLED = "cancelled"


class LessonSeries(SQLModel, table=True):
    """A recurring appointment, written as an iCalendar recurrence rule."""

    __tablename__ = "lesson_series"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="customer.id", index=True)
    recurrence: str
    quantity: Decimal = money_field()
    starts_on: date
    ends_on: date | None = None
    starts_at: time | None = None
    active: bool = Field(default=True, index=True)


class Lesson(SQLModel, table=True):
    """A single appointment, whether or not it has been answered for yet."""

    __tablename__ = "lesson"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="customer.id", index=True)
    series_id: int | None = Field(
        default=None, foreign_key="lesson_series.id", index=True
    )
    taught_on: date = Field(index=True)
    starts_at: time | None = None
    quantity: Decimal = money_field()
    status: LessonStatus = Field(default=LessonStatus.PLANNED, index=True)
    note: str | None = None
    column_values: dict[str, str | None] = Field(
        default_factory=dict, sa_column=Column(JSON)
    )
    """What the customer's extra columns should say for this lesson."""

    invoice_id: int | None = Field(
        default=None, foreign_key="issued_invoice.id", index=True
    )
    """Set once the lesson has been billed, which is what stops it being billed
    a second time."""


class AppSettings(SQLModel, table=True):
    """The one row holding everything the application itself is configured with.

    Kept in the database rather than in a file beside the code, so that it can
    be changed from the settings screen and never reaches the repository.
    """

    __tablename__ = "app_settings"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    password_hash: str
    session_secret: str
    pending_password_hash: str | None = None
    """A requested new password, waiting for the emailed code to confirm it."""
    pending_password_code: str | None = None
    pending_password_until: datetime | None = None

    invoice_folder: str = "data/invoices"
    lesson_horizon_days: int = 60
    """How far ahead recurring series are written out as individual lessons."""

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    """Where invoices are sent from. Empty means the user name is the sender."""

    calendar_token: str | None = None
    """The secret in the calendar feed URL, since calendar apps cannot sign in."""
    reminder_minutes: int = 60
    """How long before a lesson the phone should speak up."""

    show_public_holidays: bool = True
    show_school_holidays: bool = True
    holiday_states: str = ""
    """Comma-separated federal state codes such as "NW,BY". Empty shows none."""

    payment_days: int = 14
    """How many days after issuing a payment is due; later is overdue."""


class SchoolHoliday(SQLModel, table=True):
    """One cached school holiday stretch of one federal state.

    School holidays are decided, not computed, so they are fetched from the
    OpenHolidays API and kept here; the settings screen refreshes them.
    """

    __tablename__ = "school_holiday"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    state: str = Field(index=True)
    name: str
    first_day: date
    last_day: date


class NumberState(SQLModel, table=True):
    """The one row that remembers where the invoice numbering stands."""

    __tablename__ = "number_state"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    start: int
    last_assigned: int | None = None
