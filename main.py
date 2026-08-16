"""Command line entry point for the invoicing application."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from invoicing.constant import (
    DEFAULT_DATABASE_LOCATION,
    DEFAULT_SAMPLE_PDF_PATH,
    DEFAULT_WEB_PORT,
    PDF_RENDERER_AUTOMATIC,
)
from invoicing.data_classes import ImportReport, RevenueRow
from invoicing.german_formatter import german_formatter
from invoicing.legacy.import_history import HistoryImporter
from invoicing.pdf import InvoiceDocumentWriter
from invoicing.reports import RevenueReport
from invoicing.sample import SampleInvoice
from invoicing.storage.database import InvoiceDatabase
from invoicing.web.security import PasswordGate


def main() -> None:
    arguments = _parse_arguments()
    arguments.run(arguments)


def _render_sample(arguments: argparse.Namespace) -> None:
    written_to = InvoiceDocumentWriter(arguments.renderer).write_pdf(
        SampleInvoice.build(), arguments.destination
    )
    _report(f"Written: {written_to.resolve()}")


def _import_history(arguments: argparse.Namespace) -> None:
    with InvoiceDatabase(arguments.database).session() as session:
        report = HistoryImporter(session).import_from(
            arguments.directory, arguments.next_number
        )
    _describe_import(report)


def _show_summary(arguments: argparse.Namespace) -> None:
    with InvoiceDatabase(arguments.database).session() as session:
        rows = RevenueReport(session).rows()
    _describe_revenue(rows)
    if arguments.csv is not None:
        written = RevenueReport.write_csv(rows, arguments.csv)
        _report(f"\nWritten: {written.resolve()}")


def _describe_import(report: ImportReport) -> None:
    _report(f"Imported:          {report.imported}")
    _report(f"Already known:     {report.already_known}")
    _report(f"Customers created: {report.customers_created}")
    if report.lowest_number is not None:
        _report(f"Numbers:           {report.lowest_number} to {report.highest_number}")

    if report.conflicts:
        _report(f"\nSame number read differently ({len(report.conflicts)}):")
        for conflict in report.conflicts:
            _report(
                f"  no. {conflict.number}: {conflict.first_source} "
                f"and {conflict.second_source}"
            )

    if not report.anomalies:
        _report("\nNo anomalies found in the imported documents.")
        return
    _report(f"\nAnomalies in the imported documents ({len(report.anomalies)}):")
    for anomaly in report.anomalies:
        _report(f"  no. {anomaly.number}: {anomaly.description}")
    _report("\nNothing was corrected. The documents are stored as they were printed.")


def _describe_revenue(rows: Sequence[RevenueRow]) -> None:
    if not rows:
        _report("No invoices stored yet.")
        return
    width = max(len(row.customer) for row in rows)
    for row in rows:
        _report(
            f"{row.year}  {row.customer:<{width}}  {row.invoice_count:>3}x  "
            f"{german_formatter.format_euro(row.total):>12}"
        )
    _report("")
    for year, total in sorted(RevenueReport.yearly_totals(rows).items()):
        _report(
            f"{year}  {'total':<{width}}  {'':>3}   "
            f"{german_formatter.format_euro(total):>12}"
        )


def _set_password(arguments: argparse.Namespace) -> None:
    with InvoiceDatabase(arguments.database).session() as session:
        PasswordGate(session).set_password(arguments.password)
    _report("Password set. Start the app with: uv run python main.py serve")


def _serve(arguments: argparse.Namespace) -> None:
    import uvicorn

    from invoicing.web import create_app

    with InvoiceDatabase(arguments.database).session() as session:
        if not PasswordGate(session).is_configured():
            _report("No password set yet. Run: uv run python main.py set-password ...")
            return
    uvicorn.run(
        create_app(arguments.database), host=arguments.host, port=arguments.port
    )


def _report(message: str) -> None:
    sys.stdout.write(f"{message}\n")


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(required=True)

    sample = commands.add_parser("sample", help="render a sample invoice as PDF")
    sample.add_argument(
        "destination", type=Path, nargs="?", default=DEFAULT_SAMPLE_PDF_PATH
    )
    sample.add_argument(
        "--renderer",
        default=PDF_RENDERER_AUTOMATIC,
        choices=(PDF_RENDERER_AUTOMATIC, "weasyprint", "chromium"),
    )
    sample.set_defaults(run=_render_sample)

    history = commands.add_parser(
        "import-history", help="read old Markdown invoices into the database"
    )
    history.add_argument("directory", type=Path)
    history.add_argument("--database", type=Path, default=DEFAULT_DATABASE_LOCATION)
    history.add_argument(
        "--next-number",
        type=int,
        default=None,
        help="the number new invoices should continue from",
    )
    history.set_defaults(run=_import_history)

    summary = commands.add_parser("summary", help="show revenue per year and customer")
    summary.add_argument("--database", type=Path, default=DEFAULT_DATABASE_LOCATION)
    summary.add_argument("--csv", type=Path, default=None)
    summary.set_defaults(run=_show_summary)

    password = commands.add_parser(
        "set-password", help="set the password guarding the web interface"
    )
    password.add_argument("password")
    password.add_argument("--database", type=Path, default=DEFAULT_DATABASE_LOCATION)
    password.set_defaults(run=_set_password)

    serve = commands.add_parser("serve", help="run the web interface")
    serve.add_argument("--database", type=Path, default=DEFAULT_DATABASE_LOCATION)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=DEFAULT_WEB_PORT)
    serve.set_defaults(run=_serve)

    return parser.parse_args()


if __name__ == "__main__":
    main()
