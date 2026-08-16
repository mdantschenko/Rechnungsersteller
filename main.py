"""Command line entry point for the invoicing application."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path

from invoicing.constant import (
    DEFAULT_DATABASE_LOCATION,
    DEFAULT_SAMPLE_PDF_PATH,
    DEFAULT_WEB_PORT,
    PDF_RENDERER_AUTOMATIC,
)
from invoicing.data_classes import ImportReport, RevenueRow
from invoicing.german_formatter import german_formatter
from invoicing.legacy.history_importer import HistoryImporter
from invoicing.pdf import InvoiceDocumentWriter
from invoicing.reports import RevenueReport
from invoicing.sample import SampleInvoice
from invoicing.storage.invoice_database import InvoiceDatabase
from invoicing.web.password_gate import PasswordGate


class InvoicingCommandLine:
    """The subcommands behind ``python main.py``, reporting through ``output``."""

    def __init__(self, output: Callable[[str], object] = print) -> None:
        self._output = output

    def parse_arguments(self) -> argparse.Namespace:
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
        sample.set_defaults(run=self.render_sample)

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
        history.set_defaults(run=self.import_history)

        summary = commands.add_parser(
            "summary", help="show revenue per year and customer"
        )
        summary.add_argument("--database", type=Path, default=DEFAULT_DATABASE_LOCATION)
        summary.add_argument("--csv", type=Path, default=None)
        summary.set_defaults(run=self.show_summary)

        password = commands.add_parser(
            "set-password", help="set the password guarding the web interface"
        )
        password.add_argument("password")
        password.add_argument(
            "--database", type=Path, default=DEFAULT_DATABASE_LOCATION
        )
        password.set_defaults(run=self.set_password)

        serve = commands.add_parser("serve", help="run the web interface")
        serve.add_argument("--database", type=Path, default=DEFAULT_DATABASE_LOCATION)
        serve.add_argument("--host", default="127.0.0.1")
        serve.add_argument("--port", type=int, default=DEFAULT_WEB_PORT)
        serve.set_defaults(run=self.serve)

        return parser.parse_args()

    def render_sample(self, arguments: argparse.Namespace) -> None:
        written_to = InvoiceDocumentWriter(arguments.renderer).write_pdf(
            SampleInvoice.build(), arguments.destination
        )
        self._output(f"Written: {written_to.resolve()}")

    def import_history(self, arguments: argparse.Namespace) -> None:
        with InvoiceDatabase(arguments.database).session() as session:
            report = HistoryImporter(session).import_from(
                arguments.directory, arguments.next_number
            )
        self.describe_import(report)

    def show_summary(self, arguments: argparse.Namespace) -> None:
        with InvoiceDatabase(arguments.database).session() as session:
            rows = RevenueReport(session).rows()
        self.describe_revenue(rows)
        if arguments.csv is not None:
            written = RevenueReport.write_csv(rows, arguments.csv)
            self._output(f"\nWritten: {written.resolve()}")

    def set_password(self, arguments: argparse.Namespace) -> None:
        with InvoiceDatabase(arguments.database).session() as session:
            PasswordGate(session).set_password(arguments.password)
        self._output("Password set. Start the app with: uv run python main.py serve")

    def serve(self, arguments: argparse.Namespace) -> None:
        import uvicorn

        from invoicing.web import create_app

        with InvoiceDatabase(arguments.database).session() as session:
            if not PasswordGate(session).is_configured():
                self._output(
                    "No password set yet. Run: uv run python main.py set-password ..."
                )
                return
        uvicorn.run(
            create_app(arguments.database), host=arguments.host, port=arguments.port
        )

    def describe_import(self, report: ImportReport) -> None:
        self._output(f"Imported:          {report.imported}")
        self._output(f"Already known:     {report.already_known}")
        self._output(f"Customers created: {report.customers_created}")
        if report.lowest_number is not None:
            self._output(
                f"Numbers:           {report.lowest_number} to {report.highest_number}"
            )

        if report.conflicts:
            self._output(f"\nSame number read differently ({len(report.conflicts)}):")
            for conflict in report.conflicts:
                self._output(
                    f"  no. {conflict.number}: {conflict.first_source} "
                    f"and {conflict.second_source}"
                )

        if not report.anomalies:
            self._output("\nNo anomalies found in the imported documents.")
            return
        self._output(
            f"\nAnomalies in the imported documents ({len(report.anomalies)}):"
        )
        for anomaly in report.anomalies:
            self._output(f"  no. {anomaly.number}: {anomaly.description}")
        self._output(
            "\nNothing was corrected. The documents are stored as they were printed."
        )

    def describe_revenue(self, rows: Sequence[RevenueRow]) -> None:
        if not rows:
            self._output("No invoices stored yet.")
            return
        width = max(len(row.customer) for row in rows)
        for row in rows:
            self._output(
                f"{row.year}  {row.customer:<{width}}  {row.invoice_count:>3}x  "
                f"{german_formatter.format_euro(row.total):>12}"
            )
        self._output("")
        for year, total in sorted(RevenueReport.yearly_totals(rows).items()):
            self._output(
                f"{year}  {'total':<{width}}  {'':>3}   "
                f"{german_formatter.format_euro(total):>12}"
            )


def main() -> None:
    """A free function because the script entry needs no object of its own."""
    arguments = InvoicingCommandLine().parse_arguments()
    arguments.run(arguments)


if __name__ == "__main__":
    main()
