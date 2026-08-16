"""The bookkeeping behind the customer pages."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlmodel import Session, col, select

from invoicing.constant import (
    DEFAULT_LESSON_UNIT_PRICE,
    BillingCycle,
    TotalRule,
    ValueKind,
    ValueSource,
)
from invoicing.data_classes import LessonStats
from invoicing.german_formatter import german_formatter
from invoicing.lesson_series import LessonSeriesMaterialiser
from invoicing.storage.models import (
    BillingTemplate,
    Customer,
    CustomerStatus,
    ExamGrade,
    InvoiceDelivery,
    IssuedInvoice,
    Lesson,
    LessonSeries,
    LessonStatus,
    TemplateColumn,
)
from invoicing.utils import (
    parse_german_amount,
    parse_optional_clock_time,
    planning_horizon,
)
from invoicing.web.earnings import EarningsLedger
from invoicing.web.store_queries import StoreQueries


class CustomerAdministration:
    """Creates, edits and describes customers, their terms and their series."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._store = StoreQueries(session)

    def detail_context(self, customer_id: int) -> dict[str, object]:
        customer = self._store.customer(customer_id)
        earnings_rows, earnings_total = EarningsLedger(self._session).monthly_earnings(
            customer
        )
        return {
            "customer": customer,
            "grades": self._session.exec(
                select(ExamGrade)
                .where(ExamGrade.customer_id == customer_id)
                .order_by(col(ExamGrade.written_on).desc())
            ).all(),
            "stats": self.lesson_stats(customer_id),
            "terms": self.billing_template_of(customer_id),
            "series": self._session.exec(
                select(LessonSeries).where(LessonSeries.customer_id == customer_id)
            ).all(),
            "invoices": self._session.exec(
                select(IssuedInvoice)
                .where(IssuedInvoice.customer_id == customer_id)
                .order_by(col(IssuedInvoice.number).desc())
            ).all(),
            "history": self.lesson_history(customer_id),
            "earnings": earnings_rows,
            "earnings_total": earnings_total,
            "cycles": list(BillingCycle),
            "sources": list(ValueSource),
            "kinds": list(ValueKind),
            "rules": list(TotalRule),
        }

    def create(self, name: str, street: str, city: str) -> Customer:
        customer = Customer(
            name=name, street=street, city=city, status=CustomerStatus.ACTIVE
        )
        self._session.add(customer)
        self._session.flush()
        self._session.add(
            BillingTemplate(
                customer_id=customer.id or 0, unit_price=DEFAULT_LESSON_UNIT_PRICE
            )
        )
        return customer

    def save(
        self,
        customer_id: int,
        name: str,
        street: str,
        city: str,
        email: str,
        phone: str,
        status: CustomerStatus,
        delivery: InvoiceDelivery,
        student_name: str,
        student_grade: str,
        lesson_address: str,
        online: str,
        mail_text: str,
        reminder_text: str,
    ) -> None:
        customer = self._store.customer(customer_id)
        customer.name = name
        customer.street = street
        customer.city = city
        customer.email = email or None
        customer.phone = phone or None
        customer.status = status
        customer.delivery = delivery
        customer.student_name = student_name.strip() or None
        customer.student_grade = student_grade.strip() or None
        customer.lesson_address = lesson_address.strip() or None
        customer.online = bool(online)
        customer.mail_text = mail_text.strip() or None
        customer.reminder_text = reminder_text.strip() or None
        self._session.add(customer)

    def save_terms(
        self,
        customer_id: int,
        unit_price: Decimal,
        unit: str,
        description: str,
        cycle: BillingCycle,
    ) -> None:
        terms = self.billing_template_of(customer_id)
        terms.unit_price = unit_price
        terms.unit = unit
        terms.description = description
        terms.cycle = cycle
        self._session.add(terms)

    def add_column(
        self,
        customer_id: int,
        label: str,
        source: ValueSource,
        kind: ValueKind,
        total_rule: TotalRule,
        default_value: str,
        placeholder: str,
    ) -> str | None:
        """Add an extra column; the returned text is the complaint, if any."""
        terms = self.billing_template_of(customer_id)
        try:
            stored_default = self._parsed_default_value(default_value, kind)
        except ValueError:
            return "Der Standardwert muss eine Zahl sein, zum Beispiel 20,00."
        self._session.add(
            TemplateColumn(
                template_id=terms.id,
                ordinal=len(terms.columns),
                label=label,
                source=source,
                kind=kind,
                total_rule=total_rule,
                default_value=stored_default,
                placeholder=placeholder,
            )
        )
        return None

    def edit_column(
        self,
        column_id: int,
        label: str,
        source: ValueSource,
        total_rule: TotalRule,
        default_value: str,
        placeholder: str,
    ) -> str | None:
        """Rewrite an extra column; the returned text is the complaint, if any."""
        column = self._session.get(TemplateColumn, column_id)
        if column is None:
            return None
        try:
            stored_default = self._parsed_default_value(default_value, column.kind)
        except ValueError:
            return "Der Betrag muss eine Zahl sein, zum Beispiel 25,00."
        column.label = label.strip()
        column.source = source
        column.total_rule = total_rule
        column.default_value = stored_default
        column.placeholder = placeholder or "/"
        self._session.add(column)
        return None

    def remove_column(self, column_id: int) -> None:
        column = self._session.get(TemplateColumn, column_id)
        if column is not None:
            self._session.delete(column)

    @staticmethod
    def _parsed_default_value(default_value: str, kind: ValueKind) -> str | None:
        """The default as it is stored.

        Raises:
            ValueError: if a number column got something that is no number.
        """
        stored_default = default_value.strip() or None
        if stored_default is not None and kind is not ValueKind.TEXT:
            parsed = parse_german_amount(stored_default)
            if parsed is None:
                raise ValueError(f"not a German amount: {stored_default}")
            stored_default = str(parsed)
        return stored_default

    def add_series(
        self,
        customer_id: int,
        recurrence: str,
        quantity: Decimal,
        starts_on: date,
        starts_at: str,
        reminder_at: str,
    ) -> None:
        self._session.add(
            LessonSeries(
                customer_id=customer_id,
                recurrence=recurrence,
                quantity=quantity,
                starts_on=starts_on,
                starts_at=parse_optional_clock_time(starts_at),
            )
        )
        self.remember_reminder(customer_id, reminder_at)

    def change_series(
        self,
        customer_id: int,
        series_id: int,
        recurrence: str,
        quantity: Decimal,
        starts_at: str,
        reminder_at: str,
    ) -> None:
        """Rewrite the series from today on.

        Lessons that are already answered or billed stay exactly as they are;
        only the open ones from today onwards are written out anew.
        """
        series = self._session.get(LessonSeries, series_id)
        if series is None or not series.active:
            return
        self.remember_reminder(customer_id, reminder_at)
        today = date.today()
        series.recurrence = recurrence
        series.quantity = quantity
        series.starts_at = parse_optional_clock_time(starts_at)
        series.starts_on = max(series.starts_on, today)
        self._session.add(series)

        replaceable = (
            select(Lesson)
            .where(Lesson.series_id == series_id)
            .where(Lesson.taught_on >= today)
            .where(Lesson.status == LessonStatus.PLANNED)
            .where(Lesson.invoice_id == None)  # noqa: E711
        )
        for lesson in self._session.exec(replaceable).all():
            self._session.delete(lesson)
        self._session.flush()

        LessonSeriesMaterialiser(self._session).materialise_all_active(
            until=planning_horizon(self._store.app_settings(), today)
        )

    def stop_series(self, series_id: int) -> None:
        series = self._session.get(LessonSeries, series_id)
        if series is not None:
            series.active = False
            self._session.add(series)

    def remember_reminder(self, customer_id: int, reminder_at: str) -> None:
        """Remember the reminder time on the customer.

        One wake-up call per pupil, however many series they have.
        """
        customer = self._store.customer(customer_id)
        customer.reminder_at = parse_optional_clock_time(reminder_at)
        self._session.add(customer)

    def billing_template_of(self, customer_id: int) -> BillingTemplate:
        terms = self._session.exec(
            select(BillingTemplate).where(BillingTemplate.customer_id == customer_id)
        ).first()
        if terms is None:
            terms = BillingTemplate(
                customer_id=customer_id, unit_price=DEFAULT_LESSON_UNIT_PRICE
            )
            self._session.add(terms)
            self._session.flush()
        return terms

    def lesson_stats(self, customer_id: int) -> LessonStats:
        lessons = self._session.exec(
            select(Lesson).where(Lesson.customer_id == customer_id)
        ).all()
        taught = [lesson for lesson in lessons if lesson.status is LessonStatus.DONE]
        cancelled = [
            lesson for lesson in lessons if lesson.status is LessonStatus.CANCELLED
        ]
        return LessonStats(
            taught_hours=sum((lesson.quantity for lesson in taught), Decimal("0")),
            taught_count=len(taught),
            cancelled_count=len(cancelled),
        )

    def lesson_history(self, customer_id: int) -> list[tuple[str, list[Lesson]]]:
        """The customer's past lessons, newest month first."""
        lessons = self._session.exec(
            select(Lesson)
            .where(Lesson.customer_id == customer_id)
            .where(Lesson.taught_on <= date.today())
            .where(Lesson.status != LessonStatus.PLANNED)
            .order_by(col(Lesson.taught_on).desc())
        ).all()
        months: list[tuple[str, list[Lesson]]] = []
        for lesson in lessons:
            label = (
                f"{german_formatter.month_name(lesson.taught_on)} "
                f"{lesson.taught_on.year}"
            )
            if not months or months[-1][0] != label:
                months.append((label, []))
            months[-1][1].append(lesson)
        return months
