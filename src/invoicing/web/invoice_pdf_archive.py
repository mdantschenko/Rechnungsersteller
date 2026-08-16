"""Where the released invoice PDFs live, and how drafts leave as documents."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi import HTTPException
from sqlmodel import Session
from starlette.responses import Response

from invoicing.constant import INVOICE_PDF_FILE_NAME_PATTERN
from invoicing.data_classes import BillingRun
from invoicing.pdf import InvoiceDocumentWriter
from invoicing.storage.models import IssuedInvoice
from invoicing.web.store_queries import StoreQueries


class InvoicePdfArchive:
    """Finds, bundles and renders the PDFs behind the invoice records."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._store = StoreQueries(session)

    def pdf_path(self, record: IssuedInvoice, customer_name: str) -> Path:
        folder = Path(self._store.app_settings().invoice_folder) / str(
            record.issued_on.year
        )
        stem = INVOICE_PDF_FILE_NAME_PATTERN.format(number=record.number)
        return folder / f"{stem} {customer_name}.pdf"

    def find_pdf(self, record: IssuedInvoice, customer_name: str) -> Path | None:
        """The stored PDF, even if the customer was renamed after it was written.

        The file carries the name the customer had at release time, so when the
        exact path is gone the unique invoice number finds it again.
        """
        exact = self.pdf_path(record, customer_name)
        if exact.exists():
            return exact
        stem = INVOICE_PDF_FILE_NAME_PATTERN.format(number=record.number)
        return next(
            exact.parent.glob(f"{stem} *.pdf"),
            None,
        )

    def stored_pdf(self, number: int) -> Path | None:
        record = self._store.issued_invoice_by_number(number)
        if record is None:
            return None
        return self.find_pdf(record, record.customer.name)

    def zip_of(self, records: list[IssuedInvoice], file_name: str) -> Response:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for record in records:
                pdf = self.find_pdf(record, record.customer.name)
                if pdf is None:
                    continue
                archive.write(pdf, arcname=pdf.name)
        return Response(
            buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
        )

    @staticmethod
    def draft_pdf_response(run: BillingRun) -> Response:
        if run.invoice is None:
            raise HTTPException(
                status_code=404,
                detail="In diesem Zeitraum gibt es keine fertige Rechnung — offene "
                "Termine beantworten oder Stunden abhaken.",
            )
        return Response(
            InvoiceDocumentWriter().pdf_bytes(run.invoice),
            media_type="application/pdf",
            headers={"Content-Disposition": 'inline; filename="Vorschau.pdf"'},
        )

    @staticmethod
    def draft_html_response(run: BillingRun) -> Response:
        if run.invoice is None:
            raise HTTPException(
                status_code=404,
                detail="In diesem Zeitraum gibt es keine fertige Rechnung — offene "
                "Termine beantworten oder Stunden abhaken.",
            )
        return Response(
            InvoiceDocumentWriter().to_html(run.invoice),
            media_type="text/html; charset=utf-8",
        )
