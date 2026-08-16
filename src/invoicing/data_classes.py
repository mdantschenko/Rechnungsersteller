"""Every dataclass of the application, in one place as the house rules ask.

Database tables are not dataclasses; they live in ``storage/models.py``. The
order below is dependency-safe: each class only uses what stands above it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from invoicing.constant import (
    DEFAULT_BILLING_UNIT,
    DEFAULT_LESSON_DESCRIPTION,
    EXTRA_COLUMN_PLACEHOLDER,
    ZERO,
    TotalRule,
    ValueKind,
    ValueSource,
)

# The one sanctioned exception: storage.models is imported for annotations
# only — never at runtime, so no cycle.
if TYPE_CHECKING:
    from invoicing.storage import models

ExtraColumnValue = Decimal | str | None


@dataclass(frozen=True, slots=True)
class ExtraColumn:
    """One configurable column between unit price and row total.

    Existing invoices show one such column in three shapes: a travel cost
    column printing ``0 €`` on every row, the same column printing ``/`` for
    another customer, and an exercise sheet column carrying a different amount
    per lesson. All three differ only in source, default value and
    placeholder.
    """

    label: str
    source: ValueSource = ValueSource.FIXED
    kind: ValueKind = ValueKind.MONEY
    total_rule: TotalRule = TotalRule.EXCLUDED
    default_value: ExtraColumnValue = None
    placeholder: str = EXTRA_COLUMN_PLACEHOLDER


@dataclass(frozen=True, slots=True)
class BillingPeriod:
    """A closed billing stretch, ready to be invoiced.

    ``printed_from`` and ``last_day`` are what the document says. ``first_day``
    is where the period really begins, which for a mid-month cycle is the day
    after the printed start because that day was already billed.
    """

    printed_from: date
    first_day: date
    last_day: date

    def covers(self, day: date) -> bool:
        return self.first_day <= day <= self.last_day


@dataclass(frozen=True, slots=True)
class Address:
    """A postal address as it appears in the address field."""

    name: str
    street: str
    city: str


@dataclass(frozen=True, slots=True)
class Issuer:
    """Everything about the sender that appears on the letterhead and footer."""

    address: Address
    country: str
    bank: str
    iban: str
    bic: str
    tax_number: str
    email: str
    paypal: str

    @property
    def return_address_line(self) -> str:
        """The small underlined line above the recipient's address."""
        return f"{self.address.name} – {self.address.street} - {self.address.city}"


@dataclass(frozen=True, slots=True)
class TaughtLesson:
    """A lesson that was taught and is therefore billable."""

    taught_on: date
    quantity: Decimal
    column_values: Mapping[str, ExtraColumnValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InvoiceTerms:
    """A customer's invoicing settings: price, wording and extra columns."""

    unit_price: Decimal
    unit: str = DEFAULT_BILLING_UNIT
    description: str = DEFAULT_LESSON_DESCRIPTION
    columns: Sequence[ExtraColumn] = ()


@dataclass(frozen=True, slots=True)
class LineItem:
    """One row of the line item table, with its total already computed."""

    taught_on: date
    quantity: Decimal
    unit: str
    description: str
    unit_price: Decimal
    column_values: tuple[ExtraColumnValue, ...]
    total: Decimal

    @property
    def label(self) -> str:
        """The text of the "Bezeichnung / Datum" column."""
        return f"{self.description} / {self.taught_on:%d.%m.%Y}"


@dataclass(frozen=True, slots=True)
class Invoice:
    """A fully computed invoice, ready to be rendered.

    Everything needed for the document is held here by value. Once released,
    an invoice must not change when the customer, template or lessons behind
    it are edited later.
    """

    number: int
    issued_on: date
    issuer: Issuer
    recipient: Address
    period: BillingPeriod
    columns: tuple[ExtraColumn, ...]
    line_items: tuple[LineItem, ...]
    total: Decimal
    paid_on: date | None = None


@dataclass(frozen=True, slots=True)
class RevenueRow:
    """What one customer was invoiced in one year."""

    year: int
    customer: str
    invoice_count: int
    total: Decimal


@dataclass(frozen=True, slots=True)
class EarningsRow:
    """One month's take: arrived, still expected, and never invoiced."""

    label: str
    received: Decimal
    outstanding: Decimal
    uninvoiced: Decimal

    @property
    def total(self) -> Decimal:
        return self.received + self.uninvoiced


@dataclass(frozen=True, slots=True)
class LessonStats:
    """What the past lessons of one pupil add up to."""

    taught_hours: Decimal
    taught_count: int
    cancelled_count: int

    @property
    def cancelled_share(self) -> int:
        answered = self.taught_count + self.cancelled_count
        if not answered:
            return 0
        return round(100 * self.cancelled_count / answered)


@dataclass(frozen=True, slots=True)
class CalendarDay:
    """One cell of the grid."""

    on: date
    inside_month: bool
    is_today: bool
    lessons: tuple[models.Lesson, ...]
    holiday: str | None = None
    vacations: tuple[tuple[str, str], ...] = ()
    """(state, name) pairs, one per federal state on holiday that day."""
    summary: str = ""
    """One line naming the day's lessons, for the long-press peek."""

    @property
    def peek(self) -> str:
        """The long-press text: holidays first, then the lessons, one per line."""
        parts = [self.holiday] if self.holiday else []
        parts.extend(f"{name} ({state})" for state, name in self.vacations)
        if self.summary:
            parts.append(self.summary)
        return "\n".join(parts)


@dataclass(frozen=True, slots=True)
class ParsedLine:
    """One row of an old invoice, exactly as it was printed."""

    taught_on: date
    quantity: Decimal
    unit: str
    description: str
    unit_price: Decimal
    extra_printed: str
    extra_amount: Decimal | None
    total: Decimal


@dataclass(frozen=True, slots=True)
class ParsedInvoice:
    """An old invoice, read back from its document."""

    number: int
    issued_on: date
    recipient: Address
    printed_from: date
    printed_to: date
    extra_column_label: str | None
    lines: tuple[ParsedLine, ...]
    printed_total: Decimal
    paid_on: date | None
    source_file: str

    @property
    def computed_total(self) -> Decimal:
        """What the printed rows add up to, which is not always the printed total."""
        return sum((line.total for line in self.lines), start=ZERO)

    def lessons_outside_the_printed_period(self) -> tuple[ParsedLine, ...]:
        """Rows whose date lies outside the range the document itself states.

        Both ends count as inside. The point is to find plain mistakes, such as
        the three lessons on invoice 40 that carry the wrong year, without
        taking a position on which invoice a boundary day belongs to.
        """
        return tuple(
            line
            for line in self.lines
            if not self.printed_from <= line.taught_on <= self.printed_to
        )


@dataclass(frozen=True, slots=True)
class NumberConflict:
    """The same invoice number read differently from two documents."""

    number: int
    first_source: str
    second_source: str


@dataclass(frozen=True, slots=True)
class ArchiveReading:
    """Everything found in a folder of old invoices."""

    invoices: tuple[ParsedInvoice, ...]
    conflicts: tuple[NumberConflict, ...]


@dataclass(frozen=True, slots=True)
class Anomaly:
    """Something in an old document that does not add up."""

    number: int
    source_file: str
    description: str


@dataclass(frozen=True, slots=True)
class ImportReport:
    """What the import found and what it changed."""

    imported: int
    already_known: int
    customers_created: int
    lowest_number: int | None
    highest_number: int | None
    conflicts: tuple[NumberConflict, ...]
    anomalies: tuple[Anomaly, ...]


@dataclass(frozen=True, slots=True)
class BillingRun:
    """What a billing run found for one customer and one period."""

    customer: models.Customer
    closing_day: date
    period: BillingPeriod
    invoice: Invoice | None
    """The draft, or nothing when the run is blocked or there is nothing to bill."""

    unanswered: tuple[models.Lesson, ...]
    billable: tuple[models.Lesson, ...]

    @property
    def is_blocked(self) -> bool:
        return bool(self.unanswered)


@dataclass(frozen=True, slots=True)
class ReleasedInvoice:
    """A released invoice, both as a document to render and as a record."""

    document: Invoice
    record: models.IssuedInvoice
