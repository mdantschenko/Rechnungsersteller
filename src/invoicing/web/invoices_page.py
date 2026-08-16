"""Drafts waiting to be released, and the invoices already issued.

A draft is rebuilt on every visit rather than stored, so it always reflects the
lessons as they stand right now. Only releasing writes anything down.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlmodel import Session, col, select
from starlette.responses import FileResponse, RedirectResponse, Response

from invoicing import mail
from invoicing.billing import BillingRunOrchestrator
from invoicing.constant import INVOICE_PDF_FILE_NAME_PATTERN
from invoicing.data_classes import BillingRun
from invoicing.german_formatter import german_formatter
from invoicing.pdf import preview
from invoicing.pdf.invoice_document import to_html, write_pdf
from invoicing.storage.models import (
    Customer,
    CustomerStatus,
    InvoiceDelivery,
    IssuedInvoice,
    Issuer,
    PaymentReminder,
)
from invoicing.utils import notice_redirect, whatsapp_number
from invoicing.web.earnings import monthly_earnings
from invoicing.web.page import (
    active_customers,
    customer_of,
    database,
    settings_of,
    templates,
)

router = APIRouter()


@router.get("/rechnungen")
def invoice_list(request: Request, session: Session = Depends(database)) -> Response:
    today = date.today()
    everyone = session.exec(select(Customer)).all()
    issued = session.exec(
        select(IssuedInvoice).order_by(col(IssuedInvoice.number).desc())
    ).all()
    unpaid = [record for record in issued if record.paid_on is None]
    signature = issuer_name(session)
    earnings_rows, earnings_total = monthly_earnings(session)
    return templates.TemplateResponse(
        request,
        "invoices.html",
        {
            "today": today,
            "due": due_runs(session, today),
            "issued": unpaid,
            "paid": [record for record in issued if record.paid_on is not None],
            "reminders": _reminder_days(session),
            "mail_bodies": {
                record.number: invoice_mail_body(session, record, signature)
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
            "customers": active_customers(session),
            "earnings": earnings_rows,
            "earnings_total": earnings_total,
            "overdue": _overdue_days(unpaid, settings_of(session).payment_days),
            "paid_years": _paid_years(issued),
        },
    )


def _reminder_days(session: Session) -> dict[int, list[date]]:
    days: dict[int, list[date]] = {}
    rows = session.exec(
        select(PaymentReminder).order_by(col(PaymentReminder.sent_on))
    ).all()
    for row in rows:
        days.setdefault(row.invoice_id, []).append(row.sent_on)
    return days


def _overdue_days(unpaid: Sequence[IssuedInvoice], due_days: int) -> dict[int, int]:
    """Days past the due date, per unpaid invoice number."""
    today = date.today()
    late = {record.number: record.days_overdue(due_days, today) for record in unpaid}
    return {number: days for number, days in late.items() if days > 0}


def _paid_years(issued: Sequence[IssuedInvoice]) -> list[int]:
    years = {record.paid_on.year for record in issued if record.paid_on is not None}
    return sorted(years, reverse=True)


@router.get("/rechnungen/finanzamt/{year}.zip")
def tax_office_zip(year: int, session: Session = Depends(database)) -> Response:
    """Every invoice whose payment arrived in ``year``, as one ZIP."""
    records = session.exec(
        select(IssuedInvoice)
        .where(col(IssuedInvoice.paid_on) >= date(year, 1, 1))
        .where(col(IssuedInvoice.paid_on) <= date(year, 12, 31))
    ).all()
    if not records:
        raise HTTPException(
            status_code=404,
            detail=f"keine bezahlte Rechnung mit Zahlungseingang in {year}",
        )
    return _zip_response(session, list(records), f"Rechnungen-{year}.zip")


@router.get("/kunden/{customer_id}/rechnungen.zip")
def customer_zip(customer_id: int, session: Session = Depends(database)) -> Response:
    """Every invoice of one customer, as one ZIP."""
    records = session.exec(
        select(IssuedInvoice).where(IssuedInvoice.customer_id == customer_id)
    ).all()
    if not records:
        raise HTTPException(status_code=404, detail="keine Rechnung für diesen Kunden")
    name = customer_of(session, customer_id).name
    return _zip_response(session, list(records), f"Rechnungen {name}.zip")


def _zip_response(
    session: Session, records: list[IssuedInvoice], file_name: str
) -> Response:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for record in records:
            pdf = find_pdf(session, record, record.customer.name)
            if pdf is None:
                continue
            archive.write(pdf, arcname=pdf.name)
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


@router.post("/rechnungen/manuell")
def release_manual_invoice(
    request: Request,
    customer_id: int = Form(...),
    first_day: date = Form(...),
    last_day: date = Form(...),
    session: Session = Depends(database),
) -> Response:
    """Bill a hand-picked stretch of days, outside the usual cycle."""
    if last_day < first_day:
        return notice_redirect(
            request, "/rechnungen", "Das „Bis“-Datum liegt vor dem „Von“-Datum."
        )
    customer = customer_of(session, customer_id)
    orchestrator = BillingRunOrchestrator(session)
    run = orchestrator.manual_draft(customer, first_day, last_day, date.today())
    if run.is_blocked:
        return notice_redirect(
            request,
            "/rechnungen",
            f"{len(run.unanswered)} Termin(e) im Zeitraum sind noch offen — "
            "bitte erst im Kalender beantworten.",
        )
    if run.invoice is None:
        return notice_redirect(
            request,
            "/rechnungen",
            "Keine abgehakten, noch nicht abgerechneten Stunden in diesem Zeitraum.",
        )
    released = orchestrator.release(run)
    session.flush()
    write_pdf(released.document, pdf_path(session, released.record, customer.name))
    return notice_redirect(
        request,
        "/rechnungen",
        f"Rechnung Nr. {released.record.number} für {customer.name} erzeugt.",
    )


@router.get("/rechnungen/{number}/ansehen")
def view_invoice(
    number: int, request: Request, session: Session = Depends(database)
) -> Response:
    """The invoice's pages as images inside the app's own chrome."""
    path = _stored_pdf(session, number)
    pages = preview.page_count(path) if path else 0
    return templates.TemplateResponse(
        request,
        "pdf_view.html",
        {
            "heading": f"Rechnung Nr. {number}",
            "pdf_url": f"/rechnungen/{number}.pdf",
            "page_urls": [
                f"/rechnungen/{number}/seite/{index}.png" for index in range(pages)
            ],
            "kind": "pdf",
        },
    )


@router.get("/rechnungen/{number}/seite/{index}.png")
def invoice_page_image(
    number: int, index: int, session: Session = Depends(database)
) -> Response:
    path = _stored_pdf(session, number)
    image = preview.page_png(path, index) if path else None
    if image is None:
        raise HTTPException(status_code=404)
    return Response(image, media_type="image/png")


def _stored_pdf(session: Session, number: int) -> Path | None:
    record = session.exec(
        select(IssuedInvoice).where(IssuedInvoice.number == number)
    ).first()
    if record is None:
        return None
    return find_pdf(session, record, record.customer.name)


@router.get("/rechnungen/vorschau-ansicht")
def view_due_preview(
    customer_id: int,
    closing_day: date,
    request: Request,
) -> Response:
    return templates.TemplateResponse(
        request,
        "pdf_view.html",
        {
            "heading": "Vorschau",
            "pdf_url": (
                f"/rechnungen/vorschau?customer_id={customer_id}"
                f"&closing_day={closing_day}"
            ),
            "frame_url": (
                f"/rechnungen/vorschau.html?customer_id={customer_id}"
                f"&closing_day={closing_day}"
            ),
            "kind": "html",
        },
    )


@router.get("/rechnungen/vorschau-manuell-ansicht")
def view_manual_preview(
    customer_id: int,
    first_day: date,
    last_day: date,
    request: Request,
) -> Response:
    return templates.TemplateResponse(
        request,
        "pdf_view.html",
        {
            "heading": "Vorschau",
            "pdf_url": (
                f"/rechnungen/vorschau-manuell?customer_id={customer_id}"
                f"&first_day={first_day}&last_day={last_day}"
            ),
            "frame_url": (
                f"/rechnungen/vorschau-manuell.html?customer_id={customer_id}"
                f"&first_day={first_day}&last_day={last_day}"
            ),
            "kind": "html",
        },
    )


@router.get("/rechnungen/vorschau")
def preview_due_invoice(
    customer_id: int, closing_day: date, session: Session = Depends(database)
) -> Response:
    """The draft as PDF, exactly as releasing would print it — nothing is written."""
    run = BillingRunOrchestrator(session).draft_for(
        customer_of(session, customer_id), closing_day, date.today()
    )
    return _draft_pdf(run)


@router.get("/rechnungen/vorschau-manuell")
def preview_manual_invoice(
    customer_id: int,
    first_day: date,
    last_day: date,
    session: Session = Depends(database),
) -> Response:
    customer = customer_of(session, customer_id)
    run = BillingRunOrchestrator(session).manual_draft(
        customer, first_day, last_day, date.today()
    )
    return _draft_pdf(run)


@router.get("/rechnungen/vorschau.html")
def preview_due_html(
    customer_id: int, closing_day: date, session: Session = Depends(database)
) -> Response:
    """The same draft as HTML: the phone can zoom it with two fingers."""
    run = BillingRunOrchestrator(session).draft_for(
        customer_of(session, customer_id), closing_day, date.today()
    )
    return _draft_html(run)


@router.get("/rechnungen/vorschau-manuell.html")
def preview_manual_html(
    customer_id: int,
    first_day: date,
    last_day: date,
    session: Session = Depends(database),
) -> Response:
    customer = customer_of(session, customer_id)
    run = BillingRunOrchestrator(session).manual_draft(
        customer, first_day, last_day, date.today()
    )
    return _draft_html(run)


def _draft_html(run: BillingRun) -> Response:
    if run.invoice is None:
        raise HTTPException(
            status_code=404,
            detail="In diesem Zeitraum gibt es keine fertige Rechnung — offene "
            "Termine beantworten oder Stunden abhaken.",
        )
    return Response(to_html(run.invoice), media_type="text/html; charset=utf-8")


def _draft_pdf(run: BillingRun) -> Response:
    if run.invoice is None:
        raise HTTPException(
            status_code=404,
            detail="In diesem Zeitraum gibt es keine fertige Rechnung — offene "
            "Termine beantworten oder Stunden abhaken.",
        )
    with TemporaryDirectory() as folder:
        rendered = write_pdf(run.invoice, Path(folder) / "Vorschau.pdf")
        content = rendered.read_bytes()
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="Vorschau.pdf"'},
    )


@router.post("/rechnungen/{customer_id}/freigeben")
def release_invoice(
    customer_id: int,
    closing_day: date = Form(...),
    session: Session = Depends(database),
) -> Response:
    customer = customer_of(session, customer_id)
    orchestrator = BillingRunOrchestrator(session)
    run = orchestrator.draft_for(customer, closing_day, date.today())
    released = orchestrator.release(run)
    session.flush()
    write_pdf(released.document, pdf_path(session, released.record, customer.name))
    return RedirectResponse("/rechnungen", status_code=303)


@router.post("/rechnungen/{number}/senden")
def send_invoice(
    number: int, request: Request, session: Session = Depends(database)
) -> Response:
    """Email the issued invoice to its customer, PDF attached."""
    record = session.exec(
        select(IssuedInvoice).where(IssuedInvoice.number == number)
    ).first()
    if record is None:
        return notice_redirect(
            request, "/rechnungen", f"Es gibt keine Rechnung Nr. {number}."
        )
    customer = session.get(Customer, record.customer_id)
    if customer is None or not customer.email:
        return notice_redirect(
            request,
            "/rechnungen",
            "Für diesen Kunden ist keine E-Mail-Adresse hinterlegt — "
            "bitte auf der Kundenseite eintragen.",
        )
    pdf = find_pdf(session, record, customer.name)
    if pdf is None:
        return notice_redirect(
            request, "/rechnungen", f"Die PDF zu Rechnung Nr. {number} fehlt."
        )
    try:
        mail.send_pdf(
            settings_of(session),
            to=customer.email,
            subject=f"Rechnung Nr. {number}",
            body=invoice_mail_body(session, record),
            pdf=pdf,
            sender_name=issuer_name(session),
        )
    except mail.MailError as error:
        return notice_redirect(request, "/rechnungen", str(error))
    record.sent_on = date.today()
    session.add(record)
    return notice_redirect(
        request, "/rechnungen", f"Rechnung Nr. {number} an {customer.email} geschickt."
    )


@router.post("/rechnungen/{number}/gesendet")
def mark_sent(
    number: int, request: Request, session: Session = Depends(database)
) -> Response:
    record = _issued(session, number)
    if record is not None:
        record.sent_on = date.today()
        session.add(record)
    return notice_redirect(
        request, "/rechnungen", f"Rechnung Nr. {number} als gesendet vermerkt."
    )


def issuer_name(session: Session) -> str:
    issuer = session.exec(select(Issuer)).first()
    return issuer.name if issuer else ""


def invoice_mail_body(
    session: Session, record: IssuedInvoice, signature: str | None = None
) -> str:
    """The letter accompanying the invoice; ``signature`` may be preloaded
    so a page listing many invoices asks for the sender only once."""
    if signature is None:
        signature = issuer_name(session)
    customer = session.get(Customer, record.customer_id)
    if customer is not None and customer.mail_text:
        return _filled_in(customer.mail_text, record, customer, signature)
    return (
        f"Guten Tag,\n\n"
        f"anbei die Rechnung Nr. {record.number} über "
        f"{german_formatter.format_euro(record.printed_total)} für den Zeitraum "
        f"{german_formatter.format_german_date(record.period_printed_from)} bis "
        f"{german_formatter.format_german_date(record.period_printed_to)}.\n\n"
        f"Mit freundlichen Grüßen\n{signature}\n"
    )


def _filled_in(
    text: str, record: IssuedInvoice, customer: Customer, signature: str
) -> str:
    """The customer's own letter, its placeholders replaced with the facts."""
    values = {
        "MONAT": german_formatter.month_name(record.period_printed_from),
        "JAHR": str(record.period_printed_from.year),
        "BETRAG": german_formatter.format_euro(record.printed_total),
        "NUMMER": str(record.number),
        "ZEITRAUM": (
            f"{german_formatter.format_german_date(record.period_printed_from)} bis "
            f"{german_formatter.format_german_date(record.period_printed_to)}"
        ),
        "NAME": customer.name,
        "SCHUELER": customer.pupil_name,
        "ABSENDER": signature,
    }
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


@router.post("/rechnungen/{number}/bezahlt")
def mark_paid(
    number: int, request: Request, session: Session = Depends(database)
) -> Response:
    record = _issued(session, number)
    if record is None:
        return notice_redirect(
            request, "/rechnungen", f"Es gibt keine Rechnung Nr. {number}."
        )
    record.paid_on = date.today()
    session.add(record)
    return notice_redirect(
        request, "/rechnungen", f"Rechnung Nr. {number} ist bezahlt. 🎉"
    )


@router.post("/rechnungen/{number}/unbezahlt")
def mark_unpaid(
    number: int, request: Request, session: Session = Depends(database)
) -> Response:
    record = _issued(session, number)
    if record is not None:
        record.paid_on = None
        session.add(record)
    return notice_redirect(
        request, "/rechnungen", f"Rechnung Nr. {number} ist wieder offen."
    )


@router.post("/rechnungen/{number}/erinnern")
def send_payment_reminder(
    number: int, request: Request, session: Session = Depends(database)
) -> Response:
    """Send (or record) one more payment reminder for an unpaid invoice."""
    record = _issued(session, number)
    if record is None or record.id is None:
        return notice_redirect(
            request, "/rechnungen", f"Es gibt keine Rechnung Nr. {number}."
        )
    customer = session.get(Customer, record.customer_id)
    count = 1 + len(
        session.exec(
            select(PaymentReminder).where(PaymentReminder.invoice_id == record.id)
        ).all()
    )
    if (
        customer is not None
        and customer.delivery is InvoiceDelivery.EMAIL
        and customer.email
    ):
        pdf = find_pdf(session, record, customer.name)
        if pdf is None:
            return notice_redirect(
                request, "/rechnungen", f"Die PDF zu Rechnung Nr. {number} fehlt."
            )
        try:
            mail.send_pdf(
                settings_of(session),
                to=customer.email,
                subject=f"Zahlungserinnerung zur Rechnung Nr. {number}",
                body=_reminder_mail_body(session, record, count),
                pdf=pdf,
                sender_name=issuer_name(session),
            )
        except mail.MailError as error:
            return notice_redirect(request, "/rechnungen", str(error))
        message = f"{count}. Erinnerung an {customer.email} geschickt."
    else:
        message = (
            f"{count}. Erinnerung vermerkt — die PDF kannst du per WhatsApp teilen."
        )
    session.add(PaymentReminder(invoice_id=record.id, sent_on=date.today()))
    return notice_redirect(request, "/rechnungen", message)


def _issued(session: Session, number: int) -> IssuedInvoice | None:
    return session.exec(
        select(IssuedInvoice).where(IssuedInvoice.number == number)
    ).first()


def _reminder_mail_body(session: Session, record: IssuedInvoice, count: int) -> str:
    signature = issuer_name(session)
    customer = session.get(Customer, record.customer_id)
    if customer is not None and customer.reminder_text:
        text = _filled_in(customer.reminder_text, record, customer, signature)
        return text.replace("{ANZAHL}", str(count))
    return (
        f"Guten Tag,\n\n"
        f"dies ist die {count}. Zahlungserinnerung zur Rechnung Nr. "
        f"{record.number} über {german_formatter.format_euro(record.printed_total)} "
        f"vom {german_formatter.format_german_date(record.issued_on)} — anbei noch "
        f"einmal als PDF. "
        f"Falls die Zahlung schon unterwegs ist, betrachte diese Nachricht "
        f"bitte als gegenstandslos.\n\n"
        f"Mit freundlichen Grüßen\n{signature}\n"
    )


@router.get("/rechnungen/{number}.pdf")
def invoice_pdf(
    number: int, herunterladen: bool = False, session: Session = Depends(database)
) -> Response:
    """The stored PDF: shown in place by default, a download only on request."""
    path = _stored_pdf(session, number)
    if path is None:
        raise HTTPException(
            status_code=404, detail=f"keine PDF zu Rechnung Nr. {number}"
        )
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=path.name,
        content_disposition_type="attachment" if herunterladen else "inline",
    )


def due_runs(session: Session, today: date) -> list[BillingRun]:
    active = (
        select(Customer)
        .where(Customer.status == CustomerStatus.ACTIVE)
        .where(Customer.delivery != InvoiceDelivery.NONE)
        .order_by(col(Customer.name))
    )
    orchestrator = BillingRunOrchestrator(session)
    return [
        run
        for customer in session.exec(active).all()
        for run in orchestrator.open_runs(customer, today)
    ]


def pdf_path(session: Session, record: IssuedInvoice, customer_name: str) -> Path:
    folder = Path(settings_of(session).invoice_folder) / str(record.issued_on.year)
    stem = INVOICE_PDF_FILE_NAME_PATTERN.format(number=record.number)
    return folder / f"{stem} {customer_name}.pdf"


def find_pdf(
    session: Session, record: IssuedInvoice, customer_name: str
) -> Path | None:
    """The stored PDF, even if the customer was renamed after it was written.

    The file carries the name the customer had at release time, so when the
    exact path is gone the unique invoice number finds it again.
    """
    exact = pdf_path(session, record, customer_name)
    if exact.exists():
        return exact
    stem = INVOICE_PDF_FILE_NAME_PATTERN.format(number=record.number)
    return next(
        exact.parent.glob(f"{stem} *.pdf"),
        None,
    )
