"""Customers, their billing terms, their extra columns and their series."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from sqlmodel import Session, col, select
from starlette.responses import RedirectResponse, Response

from invoicing.domain.billing_period import BillingCycle
from invoicing.domain.columns import TotalRule, ValueKind, ValueSource
from invoicing.domain.money import parse_user_amount
from invoicing.scheduling import materialise_series
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
from invoicing.web.earnings import monthly_earnings
from invoicing.web.page import (
    database,
    month_name,
    notice_redirect,
    settings_of,
    templates,
)

router = APIRouter()


@router.get("/kunden")
def customer_list(request: Request, session: Session = Depends(database)) -> Response:
    everyone = session.exec(select(Customer).order_by(col(Customer.name))).all()
    return templates.TemplateResponse(
        request,
        "customers.html",
        {
            "active": [
                customer
                for customer in everyone
                if customer.status is CustomerStatus.ACTIVE
            ],
            "archived": [
                customer
                for customer in everyone
                if customer.status is CustomerStatus.ARCHIVED
            ],
        },
    )


@router.post("/kunden/neu")
def add_customer(
    name: str = Form(...),
    street: str = Form(...),
    city: str = Form(...),
    session: Session = Depends(database),
) -> Response:
    customer = Customer(
        name=name, street=street, city=city, status=CustomerStatus.ACTIVE
    )
    session.add(customer)
    session.flush()
    session.add(
        BillingTemplate(customer_id=customer.id or 0, unit_price=Decimal("30.00"))
    )
    return RedirectResponse(f"/kunden/{customer.id}", status_code=303)


@router.get("/kunden/{customer_id}")
def customer_detail(
    customer_id: int, request: Request, session: Session = Depends(database)
) -> Response:
    customer = _customer(session, customer_id)
    earnings_rows, earnings_total = monthly_earnings(session, customer)
    return templates.TemplateResponse(
        request,
        "customer.html",
        {
            "customer": customer,
            "grades": session.exec(
                select(ExamGrade)
                .where(ExamGrade.customer_id == customer_id)
                .order_by(col(ExamGrade.written_on).desc())
            ).all(),
            "stats": _lesson_stats(session, customer_id),
            "terms": _terms(session, customer_id),
            "series": session.exec(
                select(LessonSeries).where(LessonSeries.customer_id == customer_id)
            ).all(),
            "invoices": session.exec(
                select(IssuedInvoice)
                .where(IssuedInvoice.customer_id == customer_id)
                .order_by(col(IssuedInvoice.number).desc())
            ).all(),
            "history": _lesson_history(session, customer_id),
            "earnings": earnings_rows,
            "earnings_total": earnings_total,
            "cycles": list(BillingCycle),
            "sources": list(ValueSource),
            "kinds": list(ValueKind),
            "rules": list(TotalRule),
        },
    )


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


def _lesson_stats(session: Session, customer_id: int) -> LessonStats:
    lessons = session.exec(
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


@router.post("/kunden/{customer_id}/klausur")
def add_exam_grade(
    customer_id: int,
    written_on: date = Form(...),
    label: str = Form(...),
    grade: str = Form(...),
    session: Session = Depends(database),
) -> Response:
    session.add(
        ExamGrade(
            customer_id=customer_id,
            written_on=written_on,
            label=label.strip(),
            grade=grade.strip(),
        )
    )
    return RedirectResponse(f"/kunden/{customer_id}", status_code=303)


@router.post("/kunden/{customer_id}/klausur/{grade_id}/entfernen")
def remove_exam_grade(
    customer_id: int, grade_id: int, session: Session = Depends(database)
) -> Response:
    stored = session.get(ExamGrade, grade_id)
    if stored is not None and stored.customer_id == customer_id:
        session.delete(stored)
    return RedirectResponse(f"/kunden/{customer_id}", status_code=303)


def _lesson_history(
    session: Session, customer_id: int
) -> list[tuple[str, list[Lesson]]]:
    """The customer's past lessons, newest month first."""
    lessons = session.exec(
        select(Lesson)
        .where(Lesson.customer_id == customer_id)
        .where(Lesson.taught_on <= date.today())
        .where(Lesson.status != LessonStatus.PLANNED)
        .order_by(col(Lesson.taught_on).desc())
    ).all()
    months: list[tuple[str, list[Lesson]]] = []
    for lesson in lessons:
        label = f"{month_name(lesson.taught_on)} {lesson.taught_on.year}"
        if not months or months[-1][0] != label:
            months.append((label, []))
        months[-1][1].append(lesson)
    return months


@router.post("/kunden/{customer_id}/loeschen")
def delete_customer(
    customer_id: int, request: Request, session: Session = Depends(database)
) -> Response:
    """Remove a customer for good — unless invoices depend on them."""
    customer = _customer(session, customer_id)
    has_invoices = session.exec(
        select(IssuedInvoice).where(IssuedInvoice.customer_id == customer_id)
    ).first()
    if has_invoices is not None:
        return notice_redirect(
            request,
            f"/kunden/{customer_id}",
            f"{customer.name} hat ausgestellte Rechnungen und kann nicht "
            "gelöscht werden — bitte stattdessen archivieren.",
        )
    for lesson in session.exec(
        select(Lesson).where(Lesson.customer_id == customer_id)
    ).all():
        session.delete(lesson)
    for series in session.exec(
        select(LessonSeries).where(LessonSeries.customer_id == customer_id)
    ).all():
        session.delete(series)
    terms = session.exec(
        select(BillingTemplate).where(BillingTemplate.customer_id == customer_id)
    ).first()
    if terms is not None:
        for column in terms.columns:
            session.delete(column)
        session.delete(terms)
    session.delete(customer)
    return notice_redirect(request, "/kunden", f"{customer.name} gelöscht.")


@router.post("/kunden/{customer_id}")
def save_customer(
    customer_id: int,
    name: str = Form(...),
    street: str = Form(...),
    city: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    status: CustomerStatus = Form(...),
    delivery: InvoiceDelivery = Form(InvoiceDelivery.EMAIL),
    student_name: str = Form(""),
    student_grade: str = Form(""),
    lesson_address: str = Form(""),
    online: str = Form(""),
    mail_text: str = Form(""),
    reminder_text: str = Form(""),
    session: Session = Depends(database),
) -> Response:
    customer = _customer(session, customer_id)
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
    session.add(customer)
    return RedirectResponse(f"/kunden/{customer_id}", status_code=303)


@router.post("/kunden/{customer_id}/vorlage")
def save_terms(
    customer_id: int,
    unit_price: Decimal = Form(...),
    unit: str = Form(...),
    description: str = Form(...),
    cycle: BillingCycle = Form(...),
    session: Session = Depends(database),
) -> Response:
    terms = _terms(session, customer_id)
    terms.unit_price = unit_price
    terms.unit = unit
    terms.description = description
    terms.cycle = cycle
    session.add(terms)
    return RedirectResponse(f"/kunden/{customer_id}", status_code=303)


@router.post("/kunden/{customer_id}/spalte")
def add_column(
    customer_id: int,
    request: Request,
    label: str = Form(...),
    source: ValueSource = Form(...),
    kind: ValueKind = Form(...),
    total_rule: TotalRule = Form(...),
    default_value: str = Form(""),
    placeholder: str = Form("/"),
    session: Session = Depends(database),
) -> Response:
    terms = _terms(session, customer_id)
    stored_default = default_value.strip() or None
    if stored_default is not None and kind is not ValueKind.TEXT:
        parsed = parse_user_amount(stored_default)
        if parsed is None:
            return notice_redirect(
                request,
                f"/kunden/{customer_id}",
                "Der Standardwert muss eine Zahl sein, zum Beispiel 20,00.",
            )
        stored_default = str(parsed)
    session.add(
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
    return RedirectResponse(f"/kunden/{customer_id}", status_code=303)


@router.post("/kunden/{customer_id}/spalte/{column_id}")
def edit_column(
    customer_id: int,
    column_id: int,
    request: Request,
    label: str = Form(...),
    source: ValueSource = Form(...),
    total_rule: TotalRule = Form(...),
    default_value: str = Form(""),
    placeholder: str = Form("/"),
    session: Session = Depends(database),
) -> Response:
    column = session.get(TemplateColumn, column_id)
    if column is None:
        return RedirectResponse(f"/kunden/{customer_id}", status_code=303)
    stored_default = default_value.strip() or None
    if stored_default is not None and column.kind is not ValueKind.TEXT:
        parsed = parse_user_amount(stored_default)
        if parsed is None:
            return notice_redirect(
                request,
                f"/kunden/{customer_id}",
                "Der Betrag muss eine Zahl sein, zum Beispiel 25,00.",
            )
        stored_default = str(parsed)
    column.label = label.strip()
    column.source = source
    column.total_rule = total_rule
    column.default_value = stored_default
    column.placeholder = placeholder or "/"
    session.add(column)
    return RedirectResponse(f"/kunden/{customer_id}", status_code=303)


@router.post("/kunden/{customer_id}/spalte/{column_id}/entfernen")
def remove_column(
    customer_id: int, column_id: int, session: Session = Depends(database)
) -> Response:
    column = session.get(TemplateColumn, column_id)
    if column is not None:
        session.delete(column)
    return RedirectResponse(f"/kunden/{customer_id}", status_code=303)


@router.post("/kunden/{customer_id}/serie")
def add_series(
    customer_id: int,
    recurrence: str = Form(...),
    quantity: Decimal = Form(...),
    starts_on: date = Form(...),
    starts_at: str = Form(""),
    reminder_at: str = Form(""),
    session: Session = Depends(database),
) -> Response:
    session.add(
        LessonSeries(
            customer_id=customer_id,
            recurrence=recurrence,
            quantity=quantity,
            starts_on=starts_on,
            starts_at=time.fromisoformat(starts_at) if starts_at else None,
        )
    )
    _remember_reminder(session, customer_id, reminder_at)
    return RedirectResponse(f"/kunden/{customer_id}", status_code=303)


def _remember_reminder(session: Session, customer_id: int, reminder_at: str) -> None:
    """The reminder time lives on the customer: one wake-up call per pupil,
    however many series they have."""
    customer = _customer(session, customer_id)
    customer.reminder_at = time.fromisoformat(reminder_at) if reminder_at else None
    session.add(customer)


@router.post("/kunden/{customer_id}/serie/{series_id}/anpassen")
def change_series(
    customer_id: int,
    series_id: int,
    recurrence: str = Form(...),
    quantity: Decimal = Form(...),
    starts_at: str = Form(""),
    reminder_at: str = Form(""),
    session: Session = Depends(database),
) -> Response:
    """Rewrite the series from today on.

    Lessons that are already answered or billed stay exactly as they are;
    only the open ones from today onwards are written out anew.
    """
    series = session.get(LessonSeries, series_id)
    if series is None or not series.active:
        return RedirectResponse(f"/kunden/{customer_id}", status_code=303)
    _remember_reminder(session, customer_id, reminder_at)
    today = date.today()
    series.recurrence = recurrence
    series.quantity = quantity
    series.starts_at = time.fromisoformat(starts_at) if starts_at else None
    series.starts_on = max(series.starts_on, today)
    session.add(series)

    replaceable = (
        select(Lesson)
        .where(Lesson.series_id == series_id)
        .where(Lesson.taught_on >= today)
        .where(Lesson.status == LessonStatus.PLANNED)
        .where(Lesson.invoice_id == None)  # noqa: E711
    )
    for lesson in session.exec(replaceable).all():
        session.delete(lesson)
    session.flush()

    horizon = today + timedelta(days=settings_of(session).lesson_horizon_days)
    materialise_series(session, until=horizon)
    return RedirectResponse(f"/kunden/{customer_id}", status_code=303)


@router.post("/kunden/{customer_id}/serie/{series_id}/beenden")
def stop_series(
    customer_id: int, series_id: int, session: Session = Depends(database)
) -> Response:
    series = session.get(LessonSeries, series_id)
    if series is not None:
        series.active = False
        session.add(series)
    return RedirectResponse(f"/kunden/{customer_id}", status_code=303)


def _customer(session: Session, customer_id: int) -> Customer:
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise ValueError(f"no customer with id {customer_id}")
    return customer


def _terms(session: Session, customer_id: int) -> BillingTemplate:
    terms = session.exec(
        select(BillingTemplate).where(BillingTemplate.customer_id == customer_id)
    ).first()
    if terms is None:
        terms = BillingTemplate(customer_id=customer_id, unit_price=Decimal("30.00"))
        session.add(terms)
        session.flush()
    return terms
