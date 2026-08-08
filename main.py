"""Command line entry point for the invoicing application."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from invoicing.domain.money import format_euro
from invoicing.legacy.import_history import ImportReport, import_history
from invoicing.pdf.invoice_document import write_pdf
from invoicing.pdf.renderers import AUTOMATIC
from invoicing.reports import RevenueRow, revenue_rows, write_csv, yearly_totals
from invoicing.sample import sample_invoice
from invoicing.storage.database import DEFAULT_LOCATION, open_database, session_for
from invoicing.web.security import is_configured, set_password

DEFAULT_SAMPLE = Path("data/sample-invoice.pdf")
DEFAULT_PORT = 8000


def main() -> None:
    arguments = _parse_arguments()
    arguments.run(arguments)


def _render_sample(arguments: argparse.Namespace) -> None:
    written_to = write_pdf(sample_invoice(), arguments.destination, arguments.renderer)
    _report(f"Written: {written_to.resolve()}")


def _import_history(arguments: argparse.Namespace) -> None:
    engine = open_database(arguments.database)
    with session_for(engine) as session:
        report = import_history(session, arguments.directory, arguments.next_number)
    _describe_import(report)


def _show_summary(arguments: argparse.Namespace) -> None:
    engine = open_database(arguments.database)
    with session_for(engine) as session:
        rows = revenue_rows(session)
    _describe_revenue(rows)
    if arguments.csv is not None:
        _report(f"\nWritten: {write_csv(rows, arguments.csv).resolve()}")


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
            f"{format_euro(row.total):>12}"
        )
    _report("")
    for year, total in sorted(yearly_totals(rows).items()):
        _report(f"{year}  {'total':<{width}}  {'':>3}   {format_euro(total):>12}")


def _set_password(arguments: argparse.Namespace) -> None:
    engine = open_database(arguments.database)
    with session_for(engine) as session:
        set_password(session, arguments.password)
    _report("Password set. Start the app with: uv run python main.py serve")


def _serve(arguments: argparse.Namespace) -> None:
    import uvicorn

    from invoicing.web import create_app

    engine = open_database(arguments.database)
    with session_for(engine) as session:
        if not is_configured(session):
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
    sample.add_argument("destination", type=Path, nargs="?", default=DEFAULT_SAMPLE)
    sample.add_argument(
        "--renderer", default=AUTOMATIC, choices=(AUTOMATIC, "weasyprint", "chromium")
    )
    sample.set_defaults(run=_render_sample)

    history = commands.add_parser(
        "import-history", help="read old Markdown invoices into the database"
    )
    history.add_argument("directory", type=Path)
    history.add_argument("--database", type=Path, default=DEFAULT_LOCATION)
    history.add_argument(
        "--next-number",
        type=int,
        default=None,
        help="the number new invoices should continue from",
    )
    history.set_defaults(run=_import_history)

    summary = commands.add_parser("summary", help="show revenue per year and customer")
    summary.add_argument("--database", type=Path, default=DEFAULT_LOCATION)
    summary.add_argument("--csv", type=Path, default=None)
    summary.set_defaults(run=_show_summary)

    password = commands.add_parser(
        "set-password", help="set the password guarding the web interface"
    )
    password.add_argument("password")
    password.add_argument("--database", type=Path, default=DEFAULT_LOCATION)
    password.set_defaults(run=_set_password)

    serve = commands.add_parser("serve", help="run the web interface")
    serve.add_argument("--database", type=Path, default=DEFAULT_LOCATION)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.set_defaults(run=_serve)

    return parser.parse_args()


if __name__ == "__main__":
    main()
