"""Customers, their billing terms, their extra columns and their series."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from sqlmodel import Session, col, select
from starlette.responses import RedirectResponse, Response

from invoicing.constant import BillingCycle, TotalRule, ValueKind, ValueSource
from invoicing.storage.models import (
    BillingTemplate,
    Customer,
    CustomerStatus,
    ExamGrade,
    InvoiceDelivery,
    IssuedInvoice,
    Lesson,
    LessonSeries,
)
from invoicing.utils import notice_redirect
from invoicing.web.customer_administration import CustomerAdministration
from invoicing.web.page import database
from invoicing.web.store_queries import StoreQueries
from invoicing.web.template_renderer import template_renderer

router = APIRouter()


@router.get("/kunden")
def customer_list(request: Request, session: Session = Depends(database)) -> Response:
    everyone = session.exec(select(Customer).order_by(col(Customer.name))).all()
    return template_renderer.render(
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
    customer = CustomerAdministration(session).create(name, street, city)
    return RedirectResponse(f"/kunden/{customer.id}", status_code=303)


@router.get("/kunden/{customer_id}")
def customer_detail(
    customer_id: int, request: Request, session: Session = Depends(database)
) -> Response:
    return template_renderer.render(
        request,
        "customer.html",
        CustomerAdministration(session).detail_context(customer_id),
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


@router.post("/kunden/{customer_id}/loeschen")
def delete_customer(
    customer_id: int, request: Request, session: Session = Depends(database)
) -> Response:
    """Remove a customer for good — unless invoices depend on them."""
    customer = StoreQueries(session).customer(customer_id)
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
    CustomerAdministration(session).save(
        customer_id,
        name,
        street,
        city,
        email,
        phone,
        status,
        delivery,
        student_name,
        student_grade,
        lesson_address,
        online,
        mail_text,
        reminder_text,
    )
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
    CustomerAdministration(session).save_terms(
        customer_id, unit_price, unit, description, cycle
    )
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
    complaint = CustomerAdministration(session).add_column(
        customer_id, label, source, kind, total_rule, default_value, placeholder
    )
    if complaint is not None:
        return notice_redirect(request, f"/kunden/{customer_id}", complaint)
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
    complaint = CustomerAdministration(session).edit_column(
        column_id, label, source, total_rule, default_value, placeholder
    )
    if complaint is not None:
        return notice_redirect(request, f"/kunden/{customer_id}", complaint)
    return RedirectResponse(f"/kunden/{customer_id}", status_code=303)


@router.post("/kunden/{customer_id}/spalte/{column_id}/entfernen")
def remove_column(
    customer_id: int, column_id: int, session: Session = Depends(database)
) -> Response:
    CustomerAdministration(session).remove_column(column_id)
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
    CustomerAdministration(session).add_series(
        customer_id, recurrence, quantity, starts_on, starts_at, reminder_at
    )
    return RedirectResponse(f"/kunden/{customer_id}", status_code=303)


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
    CustomerAdministration(session).change_series(
        customer_id, series_id, recurrence, quantity, starts_at, reminder_at
    )
    return RedirectResponse(f"/kunden/{customer_id}", status_code=303)


@router.post("/kunden/{customer_id}/serie/{series_id}/beenden")
def stop_series(
    customer_id: int, series_id: int, session: Session = Depends(database)
) -> Response:
    CustomerAdministration(session).stop_series(series_id)
    return RedirectResponse(f"/kunden/{customer_id}", status_code=303)
