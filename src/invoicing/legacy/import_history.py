"""Loading the old invoices into the database as history.

Nothing is corrected on the way in. A document that contradicts itself is
stored the way it was printed and listed in the report, so its mistakes stay
visible instead of being carried forward into new invoices.

Running the import twice changes nothing: an invoice number already in the
database is left alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, select

from invoicing.legacy.markdown_invoices import (
    NumberConflict,
    ParsedInvoice,
    read_archive,
)
from invoicing.storage.models import (
    Customer,
    CustomerStatus,
    IssuedInvoice,
    IssuedInvoiceLine,
    NumberState,
)


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


def import_history(
    session: Session,
    directory: Path,
    next_number: int | None = None,
) -> ImportReport:
    """Read every old invoice below ``directory`` and store what is new.

    ``next_number`` sets where new invoices will continue. Left out, it becomes
    one past the highest number found, which is only right if these documents
    really are the most recent ones.
    """
    reading = read_archive(directory)
    known = _numbers_already_stored(session)
    customers_created = 0
    imported = 0
    anomalies: list[Anomaly] = []

    for parsed in reading.invoices:
        anomalies.extend(_anomalies_in(parsed))
        if parsed.number in known:
            continue
        customer = _find_customer(session, parsed.recipient.name)
        if customer is None:
            customer = _create_customer(session, parsed)
            customers_created += 1
        session.add(_as_issued_invoice(parsed, customer))
        imported += 1

    numbers = [parsed.number for parsed in reading.invoices]
    _remember_numbering(session, numbers, next_number)

    return ImportReport(
        imported=imported,
        already_known=len(reading.invoices) - imported,
        customers_created=customers_created,
        lowest_number=min(numbers, default=None),
        highest_number=max(numbers, default=None),
        conflicts=reading.conflicts,
        anomalies=tuple(anomalies),
    )


def _anomalies_in(parsed: ParsedInvoice) -> list[Anomaly]:
    found: list[Anomaly] = []
    if parsed.printed_total != parsed.computed_total:
        found.append(
            Anomaly(
                parsed.number,
                parsed.source_file,
                f"printed total {parsed.printed_total} but the rows add up to "
                f"{parsed.computed_total}",
            )
        )
    for line in parsed.lessons_outside_the_printed_period():
        found.append(
            Anomaly(
                parsed.number,
                parsed.source_file,
                f"lesson on {line.taught_on:%d.%m.%Y} lies outside the stated "
                f"period {parsed.printed_from:%d.%m.%Y} to "
                f"{parsed.printed_to:%d.%m.%Y}",
            )
        )
    if parsed.issued_on < parsed.printed_to:
        found.append(
            Anomaly(
                parsed.number,
                parsed.source_file,
                f"dated {parsed.issued_on:%d.%m.%Y}, before its period ended on "
                f"{parsed.printed_to:%d.%m.%Y}",
            )
        )
    return found


def _numbers_already_stored(session: Session) -> set[int]:
    return set(session.exec(select(IssuedInvoice.number)).all())


def _find_customer(session: Session, name: str) -> Customer | None:
    return session.exec(select(Customer).where(Customer.name == name)).first()


def _create_customer(session: Session, parsed: ParsedInvoice) -> Customer:
    customer = Customer(
        name=parsed.recipient.name,
        street=parsed.recipient.street,
        city=parsed.recipient.city,
        status=CustomerStatus.ARCHIVED,
    )
    session.add(customer)
    session.flush()
    return customer


def _as_issued_invoice(parsed: ParsedInvoice, customer: Customer) -> IssuedInvoice:
    return IssuedInvoice(
        number=parsed.number,
        customer_id=_identity_of(customer),
        issued_on=parsed.issued_on,
        period_printed_from=parsed.printed_from,
        period_printed_to=parsed.printed_to,
        column_labels=[parsed.extra_column_label] if parsed.extra_column_label else [],
        printed_total=parsed.printed_total,
        computed_total=parsed.computed_total,
        paid_on=parsed.paid_on,
        source_file=parsed.source_file,
        lines=[
            IssuedInvoiceLine(
                ordinal=ordinal,
                taught_on=line.taught_on,
                quantity=line.quantity,
                unit=line.unit,
                description=line.description,
                unit_price=line.unit_price,
                extra_values=(
                    {parsed.extra_column_label: line.extra_printed}
                    if parsed.extra_column_label
                    else {}
                ),
                total=line.total,
            )
            for ordinal, line in enumerate(parsed.lines)
        ],
    )


def _identity_of(customer: Customer) -> int:
    if customer.id is None:
        raise ValueError(f"customer {customer.name} was not written to the database")
    return customer.id


def _remember_numbering(
    session: Session, numbers: list[int], next_number: int | None
) -> None:
    if not numbers:
        return
    highest = max(numbers)
    state = session.exec(select(NumberState)).first()
    if state is None:
        state = NumberState(start=next_number or highest + 1, last_assigned=highest)
        session.add(state)
        return
    state.last_assigned = max(highest, state.last_assigned or highest)
    if next_number is not None:
        state.start = next_number
    session.add(state)
