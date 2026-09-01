"""Drafts waiting to be released, and the invoices already issued.

A draft is rebuilt on every visit rather than stored, so it always reflects the
lessons as they stand right now. Only releasing writes anything down.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlmodel import Session, col, select
from starlette.responses import FileResponse, RedirectResponse, Response

from invoicing import mail
from invoicing.billing import BillingRunOrchestrator
from invoicing.constant import DATEV_CSV_MEDIA_TYPE
from invoicing.datev_export import DatevBookingBatchExport
from invoicing.datev_export_error import DatevExportError
from invoicing.mail_error import MailError
from invoicing.pdf import InvoiceDocumentWriter, PdfPreview
from invoicing.storage.models import (
    Customer,
    InvoiceDelivery,
    IssuedInvoice,
    PaymentReminder,
)
from invoicing.utils import notice_redirect
from invoicing.web.dependencies import database_session
from invoicing.web.invoice_list_view import InvoiceListViewBuilder
from invoicing.web.invoice_mail_composer import InvoiceMailComposer
from invoicing.web.invoice_pdf_archive import InvoicePdfArchive
from invoicing.web.store_queries import StoreQueries
from invoicing.web.template_renderer import template_renderer

router = APIRouter()


@router.get("/rechnungen")
def invoice_list(
    request: Request, session: Session = Depends(database_session)
) -> Response:
    return template_renderer.render(
        request, "invoices.html", InvoiceListViewBuilder(session).list_context()
    )


@router.get("/rechnungen/finanzamt/{year}.zip")
def tax_office_zip(year: int, session: Session = Depends(database_session)) -> Response:
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
    return InvoicePdfArchive(session).zip_of(list(records), f"Rechnungen-{year}.zip")


@router.get("/rechnungen/datev/{year}.csv")
def datev_booking_batch(
    year: int, request: Request, session: Session = Depends(database_session)
) -> Response:
    """Every invoice issued in ``year`` as a DATEV booking batch for Lexware.

    The year is the year of the invoice date, unlike the tax office ZIP,
    which goes by the payment date.
    """
    export = DatevBookingBatchExport(session)
    try:
        payload = export.csv_bytes(year)
    except DatevExportError as error:
        return notice_redirect(request, "/rechnungen", str(error))
    file_name = export.file_name(year)
    return Response(
        payload,
        media_type=DATEV_CSV_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


@router.get("/kunden/{customer_id}/rechnungen.zip")
def customer_zip(
    customer_id: int, session: Session = Depends(database_session)
) -> Response:
    """Every invoice of one customer, as one ZIP."""
    records = session.exec(
        select(IssuedInvoice).where(IssuedInvoice.customer_id == customer_id)
    ).all()
    if not records:
        raise HTTPException(status_code=404, detail="keine Rechnung für diesen Kunden")
    name = StoreQueries(session).customer(customer_id).name
    return InvoicePdfArchive(session).zip_of(list(records), f"Rechnungen {name}.zip")


@router.post("/rechnungen/manuell")
def release_manual_invoice(
    request: Request,
    customer_id: int = Form(...),
    first_day: date = Form(...),
    last_day: date = Form(...),
    session: Session = Depends(database_session),
) -> Response:
    """Bill a hand-picked stretch of days, outside the usual cycle."""
    if last_day < first_day:
        return notice_redirect(
            request, "/rechnungen", "Das „Bis“-Datum liegt vor dem „Von“-Datum."
        )
    customer = StoreQueries(session).customer(customer_id)
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
    InvoiceDocumentWriter().write_pdf(
        released.document,
        InvoicePdfArchive(session).pdf_path(released.record, customer.name),
    )
    return notice_redirect(
        request,
        "/rechnungen",
        f"Rechnung Nr. {released.record.number} für {customer.name} erzeugt.",
    )


@router.get("/rechnungen/{number}/ansehen")
def view_invoice(
    number: int, request: Request, session: Session = Depends(database_session)
) -> Response:
    """The invoice's pages as images inside the app's own chrome."""
    path = InvoicePdfArchive(session).stored_pdf(number)
    pages = PdfPreview(path).page_count() if path else 0
    return template_renderer.render(
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
    number: int, index: int, session: Session = Depends(database_session)
) -> Response:
    path = InvoicePdfArchive(session).stored_pdf(number)
    image = PdfPreview(path).page_png(index) if path else None
    if image is None:
        raise HTTPException(status_code=404)
    return Response(image, media_type="image/png")


@router.get("/rechnungen/vorschau-ansicht")
def view_due_preview(
    customer_id: int,
    closing_day: date,
    request: Request,
) -> Response:
    return template_renderer.render(
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
    return template_renderer.render(
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
    customer_id: int, closing_day: date, session: Session = Depends(database_session)
) -> Response:
    """The draft as PDF, exactly as releasing would print it — nothing is written."""
    run = BillingRunOrchestrator(session).draft_for(
        StoreQueries(session).customer(customer_id), closing_day, date.today()
    )
    return InvoicePdfArchive.draft_pdf_response(run)


@router.get("/rechnungen/vorschau-manuell")
def preview_manual_invoice(
    customer_id: int,
    first_day: date,
    last_day: date,
    session: Session = Depends(database_session),
) -> Response:
    customer = StoreQueries(session).customer(customer_id)
    run = BillingRunOrchestrator(session).manual_draft(
        customer, first_day, last_day, date.today()
    )
    return InvoicePdfArchive.draft_pdf_response(run)


@router.get("/rechnungen/vorschau.html")
def preview_due_html(
    customer_id: int, closing_day: date, session: Session = Depends(database_session)
) -> Response:
    """The same draft as HTML: the phone can zoom it with two fingers."""
    run = BillingRunOrchestrator(session).draft_for(
        StoreQueries(session).customer(customer_id), closing_day, date.today()
    )
    return InvoicePdfArchive.draft_html_response(run)


@router.get("/rechnungen/vorschau-manuell.html")
def preview_manual_html(
    customer_id: int,
    first_day: date,
    last_day: date,
    session: Session = Depends(database_session),
) -> Response:
    customer = StoreQueries(session).customer(customer_id)
    run = BillingRunOrchestrator(session).manual_draft(
        customer, first_day, last_day, date.today()
    )
    return InvoicePdfArchive.draft_html_response(run)


@router.post("/rechnungen/{customer_id}/freigeben")
def release_invoice(
    customer_id: int,
    closing_day: date = Form(...),
    session: Session = Depends(database_session),
) -> Response:
    customer = StoreQueries(session).customer(customer_id)
    orchestrator = BillingRunOrchestrator(session)
    run = orchestrator.draft_for(customer, closing_day, date.today())
    released = orchestrator.release(run)
    session.flush()
    InvoiceDocumentWriter().write_pdf(
        released.document,
        InvoicePdfArchive(session).pdf_path(released.record, customer.name),
    )
    return RedirectResponse("/rechnungen", status_code=303)


@router.post("/rechnungen/{number}/senden")
def send_invoice(
    number: int, request: Request, session: Session = Depends(database_session)
) -> Response:
    """Email the issued invoice to its customer, PDF attached."""
    record = StoreQueries(session).issued_invoice_by_number(number)
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
    pdf = InvoicePdfArchive(session).find_pdf(record, customer.name)
    if pdf is None:
        return notice_redirect(
            request, "/rechnungen", f"Die PDF zu Rechnung Nr. {number} fehlt."
        )
    composer = InvoiceMailComposer(session)
    archive = InvoicePdfArchive(session)
    today = date.today()
    outgoing = composer.mail_to_send(record, today)
    try:
        mail.mailer_for(StoreQueries(session).app_settings()).send_pdf(
            to=customer.email,
            subject=outgoing.subject,
            body=outgoing.body,
            pdf=pdf,
            sender_name=composer.issuer_name(),
            more_pdfs=archive.pdfs_of(outgoing.rides_along, customer.name),
        )
    except MailError as error:
        return notice_redirect(request, "/rechnungen", str(error))
    record.sent_on = today
    session.add(record)
    for reminded in outgoing.to_note_as_reminded:
        session.add(PaymentReminder(invoice_id=reminded.id or 0, sent_on=today))
    return notice_redirect(
        request,
        "/rechnungen",
        _sent_message(number, customer.email, outgoing.rides_along),
    )


def _sent_message(
    number: int, address: str, still_open: Sequence[IssuedInvoice]
) -> str:
    if not still_open:
        return f"Rechnung Nr. {number} an {address} geschickt."
    reminded = ", ".join(f"Nr. {invoice.number}" for invoice in still_open)
    return (
        f"Rechnung Nr. {number} an {address} geschickt — mit Hinweis "
        f"auf {reminded} in derselben Mail."
    )


@router.post("/rechnungen/{number}/gesendet")
def mark_sent(
    number: int, request: Request, session: Session = Depends(database_session)
) -> Response:
    record = StoreQueries(session).issued_invoice_by_number(number)
    if record is not None:
        record.sent_on = date.today()
        session.add(record)
    return notice_redirect(
        request, "/rechnungen", f"Rechnung Nr. {number} als gesendet vermerkt."
    )


@router.post("/rechnungen/{number}/bezahlt")
def mark_paid(
    number: int, request: Request, session: Session = Depends(database_session)
) -> Response:
    record = StoreQueries(session).issued_invoice_by_number(number)
    if record is None:
        return notice_redirect(
            request, "/rechnungen", f"Es gibt keine Rechnung Nr. {number}."
        )
    record.paid_on = date.today()
    session.add(record)
    return notice_redirect(
        request, "/rechnungen", f"Rechnung Nr. {number} ist bezahlt. 🎉"
    )


@router.post("/rechnungen/{number}/ausblenden")
def take_paid_invoice_off_the_list(
    number: int, request: Request, session: Session = Depends(database_session)
) -> Response:
    """Tidy a paid invoice away from the list; the books keep it."""
    record = StoreQueries(session).issued_invoice_by_number(number)
    if record is None or record.paid_on is None:
        return notice_redirect(
            request, "/rechnungen", f"Rechnung Nr. {number} ist nicht bezahlt."
        )
    record.taken_off_the_list_on = date.today()
    session.add(record)
    return notice_redirect(
        request, "/rechnungen", f"Rechnung Nr. {number} ausgeblendet."
    )


@router.post("/rechnungen/bezahlt-wieder-zeigen")
def show_every_paid_invoice_again(
    request: Request, session: Session = Depends(database_session)
) -> Response:
    hidden = session.exec(
        select(IssuedInvoice).where(
            col(IssuedInvoice.taken_off_the_list_on).is_not(None)
        )
    ).all()
    for record in hidden:
        record.taken_off_the_list_on = None
        session.add(record)
    return notice_redirect(
        request, "/rechnungen", f"{len(hidden)} Rechnung(en) wieder eingeblendet."
    )


@router.post("/rechnungen/{number}/unbezahlt")
def mark_unpaid(
    number: int, request: Request, session: Session = Depends(database_session)
) -> Response:
    record = StoreQueries(session).issued_invoice_by_number(number)
    if record is not None:
        record.paid_on = None
        record.taken_off_the_list_on = None
        session.add(record)
    return notice_redirect(
        request, "/rechnungen", f"Rechnung Nr. {number} ist wieder offen."
    )


@router.get("/rechnungen/{number}/erinnerung")
def preview_payment_reminder(
    number: int, request: Request, session: Session = Depends(database_session)
) -> Response:
    """Show the reminder letter exactly as it would leave the house."""
    record = StoreQueries(session).issued_invoice_by_number(number)
    if record is None or record.id is None:
        return notice_redirect(
            request, "/rechnungen", f"Es gibt keine Rechnung Nr. {number}."
        )
    customer = session.get(Customer, record.customer_id)
    composer = InvoiceMailComposer(session)
    count = _reminders_so_far(session, record.id) + 1
    pdf = (
        InvoicePdfArchive(session).find_pdf(record, customer.name) if customer else None
    )
    goes_by_mail = (
        customer is not None
        and customer.delivery is InvoiceDelivery.EMAIL
        and bool(customer.email)
    )
    return template_renderer.render(
        request,
        "mail_preview.html",
        {
            "heading": f"{count}. Zahlungserinnerung",
            "subject": f"Zahlungserinnerung zur Rechnung Nr. {number}",
            "body": composer.reminder_mail_body(record, count),
            "attachments": [pdf.name] if pdf else [],
            "recipient": (
                customer.email
                if goes_by_mail and customer
                else "niemanden — für diesen Kunden ist kein E-Mail-Versand "
                "eingestellt, die Erinnerung wird nur vermerkt"
            ),
            "send_action": f"/rechnungen/{number}/erinnern",
        },
    )


def _reminders_so_far(session: Session, invoice_id: int) -> int:
    return len(
        session.exec(
            select(PaymentReminder).where(PaymentReminder.invoice_id == invoice_id)
        ).all()
    )


@router.post("/rechnungen/{number}/erinnern")
def send_payment_reminder(
    number: int, request: Request, session: Session = Depends(database_session)
) -> Response:
    """Send (or record) one more payment reminder for an unpaid invoice."""
    record = StoreQueries(session).issued_invoice_by_number(number)
    if record is None or record.id is None:
        return notice_redirect(
            request, "/rechnungen", f"Es gibt keine Rechnung Nr. {number}."
        )
    customer = session.get(Customer, record.customer_id)
    count = _reminders_so_far(session, record.id) + 1
    if (
        customer is not None
        and customer.delivery is InvoiceDelivery.EMAIL
        and customer.email
    ):
        pdf = InvoicePdfArchive(session).find_pdf(record, customer.name)
        if pdf is None:
            return notice_redirect(
                request, "/rechnungen", f"Die PDF zu Rechnung Nr. {number} fehlt."
            )
        composer = InvoiceMailComposer(session)
        try:
            mail.mailer_for(StoreQueries(session).app_settings()).send_pdf(
                to=customer.email,
                subject=f"Zahlungserinnerung zur Rechnung Nr. {number}",
                body=composer.reminder_mail_body(record, count),
                pdf=pdf,
                sender_name=composer.issuer_name(),
            )
        except MailError as error:
            return notice_redirect(request, "/rechnungen", str(error))
        message = f"{count}. Erinnerung an {customer.email} geschickt."
    else:
        message = (
            f"{count}. Erinnerung vermerkt — die PDF kannst du per WhatsApp teilen."
        )
    session.add(PaymentReminder(invoice_id=record.id, sent_on=date.today()))
    return notice_redirect(request, "/rechnungen", message)


@router.get("/rechnungen/{number}.pdf")
def invoice_pdf(
    number: int,
    herunterladen: bool = False,
    session: Session = Depends(database_session),
) -> Response:
    """The stored PDF: shown in place by default, a download only on request."""
    path = InvoicePdfArchive(session).stored_pdf(number)
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
