"""The customer's own letter says where an older open invoice is named."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from test_web import _add_customer, _add_lesson, _set_terms

from invoicing.german_formatter import german_formatter
from invoicing.storage.invoice_database import InvoiceDatabase
from invoicing.storage.models import (
    Customer,
    CustomerStatus,
    IssuedInvoice,
    Lesson,
    PaymentReminder,
)
from invoicing.utils import parse_german_amount
from invoicing.web.invoice_mail_composer import InvoiceMailComposer

NON_BREAKING_SPACE = "\N{NO-BREAK SPACE}"
EURO_SIGN = "\N{EURO SIGN}"


def _as_the_app_prints_money(letter: str) -> str:
    """The letter with the non-breaking space every printed amount carries."""
    return letter.replace(f" {EURO_SIGN}", f"{NON_BREAKING_SPACE}{EURO_SIGN}")


MARKERS_AT_THE_LINE_END = """Guten Tag {NAME},

anbei ist die Rechnung für den {MONAT}, vielen Dank für den Ausgleich!\
{WENN OFFEN} Außerdem ist im Anhang noch die letzte Rechnung {ALTER MONAT}.{ENDE}

Zusammenfassung:
Rechnung Nr. {NUMMER}: {BETRAG}{WENN OFFEN}
Rechnung Nr. {ALTE RECHNUNG}: {ALTER BETRAG}
SUMME: {SUMME}{ENDE}
PayPal: info@matheganzeinfach.com
IBAN: DE88 3005 0110 1008 9208 50

Liebe Grüße
Michael
"""

MARKERS_ON_LINES_OF_THEIR_OWN = """Guten Tag {NAME},

anbei ist die Rechnung für den {MONAT}, vielen Dank für den Ausgleich!\
{WENN OFFEN} Außerdem ist im Anhang noch die letzte Rechnung {ALTER MONAT}.{ENDE}

Zusammenfassung:
Rechnung Nr. {NUMMER}: {BETRAG}
{WENN OFFEN}
Rechnung Nr. {ALTE RECHNUNG}: {ALTER BETRAG}
SUMME: {SUMME}
{ENDE}
PayPal: info@matheganzeinfach.com
IBAN: DE88 3005 0110 1008 9208 50

Liebe Grüße
Michael
"""

MARKERS_STARTING_A_LINE = """Guten Tag {NAME},

anbei ist die Rechnung für den {MONAT}, vielen Dank für den Ausgleich!\
{WENN OFFEN} Außerdem ist im Anhang noch die letzte Rechnung {ALTER MONAT}.{ENDE}

Zusammenfassung:
Rechnung Nr. {NUMMER}: {BETRAG}
{WENN OFFEN}Rechnung Nr. {ALTE RECHNUNG}: {ALTER BETRAG}
SUMME: {SUMME}
{ENDE}PayPal: info@matheganzeinfach.com
IBAN: DE88 3005 0110 1008 9208 50

Liebe Grüße
Michael
"""

LETTER_WITH_AN_OPEN_INVOICE = _as_the_app_prints_money("""Guten Tag Frank,

anbei ist die Rechnung für den August, vielen Dank für den Ausgleich! \
Außerdem ist im Anhang noch die letzte Rechnung Juli.

Zusammenfassung:
Rechnung Nr. 120: 140,01 €
Rechnung Nr. 119: 120,00 €
SUMME: 260,01 €
PayPal: info@matheganzeinfach.com
IBAN: DE88 3005 0110 1008 9208 50

Liebe Grüße
Michael
""")

LETTER_WITHOUT_AN_OPEN_INVOICE = _as_the_app_prints_money("""Guten Tag Frank,

anbei ist die Rechnung für den August, vielen Dank für den Ausgleich!

Zusammenfassung:
Rechnung Nr. 120: 140,01 €
PayPal: info@matheganzeinfach.com
IBAN: DE88 3005 0110 1008 9208 50

Liebe Grüße
Michael
""")

JULY = (date(2026, 7, 1), date(2026, 7, 31))
JUNE = (date(2026, 6, 1), date(2026, 6, 30))
JULY_AND_AUGUST = (date(2026, 7, 1), date(2026, 8, 31))


def _older_invoice(
    number: int, period: tuple[date, date], total: str
) -> dict[str, Any]:
    return {"number": number, "period": period, "total": total}


def _letter_for(
    location: Path,
    mail_text: str,
    older: Sequence[dict[str, Any]] = (),
) -> str:
    """The invoice letter as the customer would read it."""
    with Session(InvoiceDatabase(location).open()) as session:
        _empty_the_books(session)
        customer = Customer(
            name="Frank",
            street="Beispielweg 3",
            city="12345 Beispielstadt",
            email="frank@example.com",
            status=CustomerStatus.ACTIVE,
            mail_text=mail_text,
        )
        session.add(customer)
        session.commit()
        for older_invoice in older:
            session.add(
                _invoice_row(
                    customer.id or 0,
                    older_invoice["number"],
                    older_invoice["period"],
                    older_invoice["total"],
                )
            )
        new = _invoice_row(
            customer.id or 0, 120, (date(2026, 8, 1), date(2026, 8, 31)), "140.01"
        )
        session.add(new)
        session.commit()
        composer = InvoiceMailComposer(session)
        return composer.invoice_mail_body(new, None, composer.still_unpaid(new))


def _empty_the_books(session: Session) -> None:
    """Start from nothing, so every letter is built on the same clean slate."""
    for invoice in session.exec(select(IssuedInvoice)).all():
        session.delete(invoice)
    for customer in session.exec(select(Customer)).all():
        session.delete(customer)
    session.commit()


def _invoice_row(
    customer_id: int, number: int, period: tuple[date, date], total: str
) -> IssuedInvoice:
    return IssuedInvoice(
        number=number,
        customer_id=customer_id,
        issued_on=period[1],
        period_printed_from=period[0],
        period_printed_to=period[1],
        printed_total=Decimal(total),
        computed_total=Decimal(total),
    )


def test_the_letter_names_the_open_invoice_where_the_user_put_it(
    location: Path,
) -> None:
    letter = _letter_for(
        location, MARKERS_AT_THE_LINE_END, [_older_invoice(119, JULY, "120.00")]
    )

    assert letter == LETTER_WITH_AN_OPEN_INVOICE


def test_without_an_open_invoice_the_letter_reads_as_it_always_did(
    location: Path,
) -> None:
    letter = _letter_for(location, MARKERS_AT_THE_LINE_END)

    assert letter == LETTER_WITHOUT_AN_OPEN_INVOICE


def test_both_spellings_of_the_marker_give_the_same_letter(location: Path) -> None:
    open_invoice = [_older_invoice(119, JULY, "120.00")]

    assert (
        _letter_for(location, MARKERS_ON_LINES_OF_THEIR_OWN, open_invoice)
        == LETTER_WITH_AN_OPEN_INVOICE
    )
    assert (
        _letter_for(location, MARKERS_STARTING_A_LINE, open_invoice)
        == LETTER_WITH_AN_OPEN_INVOICE
    )


def test_both_spellings_also_agree_when_nothing_is_open(location: Path) -> None:
    assert (
        _letter_for(location, MARKERS_ON_LINES_OF_THEIR_OWN)
        == LETTER_WITHOUT_AN_OPEN_INVOICE
    )
    assert (
        _letter_for(location, MARKERS_STARTING_A_LINE) == LETTER_WITHOUT_AN_OPEN_INVOICE
    )


def test_two_open_invoices_are_listed_and_added_up(location: Path) -> None:
    letter = _letter_for(
        location,
        MARKERS_AT_THE_LINE_END,
        [
            _older_invoice(118, JUNE, "100.00"),
            _older_invoice(119, JULY, "120.00"),
        ],
    )

    assert "letzte Rechnung Juni bis Juli." in letter
    assert _as_the_app_prints_money("Rechnung Nr. 119: 120,00 €") in letter
    assert _as_the_app_prints_money("Rechnung Nr. 118: 100,00 €") in letter
    assert _as_the_app_prints_money("SUMME: 360,01 €") in letter


def test_an_old_invoice_over_two_months_says_both_months(location: Path) -> None:
    letter = _letter_for(
        location,
        MARKERS_AT_THE_LINE_END,
        [_older_invoice(119, JULY_AND_AUGUST, "120.00")],
    )

    assert "letzte Rechnung Juli bis August." in letter


def test_the_sum_is_the_new_amount_plus_everything_open(location: Path) -> None:
    letter = _letter_for(
        location,
        MARKERS_AT_THE_LINE_END,
        [
            _older_invoice(118, JUNE, "0.99"),
            _older_invoice(119, JULY, "7.10"),
        ],
    )

    printed = next(line for line in letter.splitlines() if line.startswith("SUMME: "))
    assert parse_german_amount(printed.removeprefix("SUMME: ")) == Decimal(
        "140.01"
    ) + Decimal("0.99") + Decimal("7.10")


@pytest.mark.parametrize(
    "mail_text",
    [
        "Hallo {NAME},{WENN OFFEN} noch offen: {ALTE RECHNUNG} über {ALTER BETRAG}.",
        "Hallo {NAME},{ENDE} die Rechnung Nr. {NUMMER}.",
        "Hallo {NAME},{wenn offen} offen: {alte rechnung}.{ende} Schönen Tag.",
        "Hallo {NAME},\n{WENN OFFEN}\nOffen: {ALTE RECHNUNG}\nkein Ende in Sicht",
        "{ENDE}{ENDE}Hallo {NAME}.{WENN OFFEN}",
    ],
)
@pytest.mark.parametrize("open_invoices", [[], [_older_invoice(119, JULY, "120.00")]])
def test_broken_markers_never_reach_the_customer(
    location: Path, mail_text: str, open_invoices: list[dict[str, Any]]
) -> None:
    letter = _letter_for(location, mail_text, open_invoices)

    assert "WENN OFFEN" not in letter.upper()
    assert "{ENDE}" not in letter.upper()
    assert "ALTE RECHNUNG" not in letter.upper()
    assert "Frank" in letter


def test_a_name_with_braces_is_never_read_as_a_placeholder(location: Path) -> None:
    with Session(InvoiceDatabase(location).open()) as session:
        customer = Customer(
            name="{WENN OFFEN}{BETRAG}",
            street="Beispielweg 3",
            city="12345 Beispielstadt",
            status=CustomerStatus.ACTIVE,
            mail_text="Hallo {NAME}, Rechnung {NUMMER}.",
        )
        session.add(customer)
        session.commit()
        record = _invoice_row(
            customer.id or 0, 120, (date(2026, 8, 1), date(2026, 8, 31)), "140.01"
        )
        session.add(record)
        session.commit()
        letter = InvoiceMailComposer(session).invoice_mail_body(record)

    assert letter == "Hallo {WENN OFFEN}{BETRAG}, Rechnung 120."


def test_the_reminder_letter_can_use_the_block_too(location: Path) -> None:
    with Session(InvoiceDatabase(location).open()) as session:
        customer = Customer(
            name="Frank",
            street="Beispielweg 3",
            city="12345 Beispielstadt",
            status=CustomerStatus.ACTIVE,
            reminder_text=(
                "Hallo {NAME}, {ANZAHL}. Erinnerung zu Nr. {NUMMER}."
                "{WENN OFFEN} Offen ist auch Nr. {ALTE RECHNUNG}.{ENDE}"
            ),
        )
        session.add(customer)
        session.commit()
        session.add(_invoice_row(customer.id or 0, 119, JULY, "120.00"))
        record = _invoice_row(
            customer.id or 0, 120, (date(2026, 8, 1), date(2026, 8, 31)), "140.01"
        )
        session.add(record)
        session.commit()
        composer = InvoiceMailComposer(session)
        with_open = composer.reminder_mail_body(record, 2)
        session.delete(
            session.exec(select(IssuedInvoice).where(IssuedInvoice.number == 119)).one()
        )
        session.commit()
        without_open = composer.reminder_mail_body(record, 2)

    assert with_open == "Hallo Frank, 2. Erinnerung zu Nr. 120. Offen ist auch Nr. 119."
    assert without_open == "Hallo Frank, 2. Erinnerung zu Nr. 120."


def _customer_writing_the_block(client: TestClient) -> int:
    customer_id = _add_customer(client)
    _set_terms(client, customer_id)
    client.post(
        f"/kunden/{customer_id}",
        data={
            "name": "Frank",
            "street": "Beispielweg 3",
            "city": "12345 Beispielstadt",
            "email": "frank@example.com",
            "status": "active",
            "delivery": "email",
            "mail_text": MARKERS_AT_THE_LINE_END,
        },
    )
    return customer_id


def _released_invoice(
    client: TestClient,
    location: Path,
    customer_id: int,
    taught_on: date,
    closing_day: date,
) -> None:
    _add_lesson(client, customer_id, taught_on)
    client.post(f"/termine/{_lesson_id_on(location, taught_on)}/erledigt")
    client.post(
        f"/rechnungen/{customer_id}/freigeben",
        data={"closing_day": closing_day.isoformat()},
    )


def _lesson_id_on(location: Path, taught_on: date) -> int:
    with Session(InvoiceDatabase(location).open()) as session:
        lesson = session.exec(select(Lesson).where(Lesson.taught_on == taught_on)).one()
        return lesson.id or 0


def _issued_days_ago(location: Path, number: int, days: int) -> None:
    with Session(InvoiceDatabase(location).open()) as session:
        record = session.exec(
            select(IssuedInvoice).where(IssuedInvoice.number == number)
        ).one()
        record.issued_on = date.today() - timedelta(days=days)
        session.add(record)
        session.commit()


def _reminders_for(location: Path, number: int) -> int:
    with Session(InvoiceDatabase(location).open()) as session:
        record = session.exec(
            select(IssuedInvoice).where(IssuedInvoice.number == number)
        ).one()
        return len(
            session.exec(
                select(PaymentReminder).where(PaymentReminder.invoice_id == record.id)
            ).all()
        )


def _sent_by_mail(
    client: TestClient, location: Path, monkeypatch: pytest.MonkeyPatch, days_ago: int
) -> dict[str, Any]:
    sent: dict[str, Any] = {}
    monkeypatch.setattr(
        "invoicing.mail.SmtpMailer.send_pdf",
        lambda mailer, **parts: sent.update(parts),
    )
    customer_id = _customer_writing_the_block(client)
    _released_invoice(
        client, location, customer_id, date(2026, 5, 20), date(2026, 6, 15)
    )
    _issued_days_ago(location, 115, days_ago)
    _released_invoice(
        client, location, customer_id, date(2026, 6, 20), date(2026, 7, 15)
    )
    client.post("/rechnungen/116/senden")
    return sent


def test_an_unpaid_invoice_inside_its_window_is_named_but_not_reminded(
    client: TestClient, location: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _sent_by_mail(client, location, monkeypatch, days_ago=1)

    assert "Rechnung Nr. 115: " in str(sent["body"])
    assert "P.S." not in str(sent["body"])
    assert len(list(sent["more_pdfs"])) == 1
    assert _reminders_for(location, 115) == 0


def test_an_overdue_invoice_is_named_and_written_down_as_reminded(
    client: TestClient, location: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _sent_by_mail(client, location, monkeypatch, days_ago=60)

    assert "Rechnung Nr. 115: " in str(sent["body"])
    assert "P.S." not in str(sent["body"])
    assert _reminders_for(location, 115) == 1


def test_the_sum_in_the_sent_mail_adds_both_invoices_up(
    client: TestClient, location: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _sent_by_mail(client, location, monkeypatch, days_ago=60)
    body = str(sent["body"])

    amounts = [
        parse_german_amount(line.split(": ", maxsplit=1)[1])
        for line in body.splitlines()
        if line.startswith("Rechnung Nr. ")
    ]
    printed_sum = next(line for line in body.splitlines() if line.startswith("SUMME: "))
    assert parse_german_amount(printed_sum.removeprefix("SUMME: ")) == sum(
        amount for amount in amounts if amount is not None
    )
    assert german_formatter.format_euro(Decimal("66.66")) in body


def test_the_customer_page_explains_the_new_placeholders(client: TestClient) -> None:
    page = client.get(f"/kunden/{_add_customer(client)}").text

    assert "{ALTE RECHNUNG}" in page
    assert "{ALTER BETRAG}" in page
    assert "{ALTER MONAT}" in page
    assert "{SUMME}" in page
    assert "Was zwischen {WENN OFFEN} und {ENDE} steht" in page


def test_each_open_invoice_gets_its_own_line() -> None:
    """A line naming an old invoice belongs to one invoice, so it repeats."""
    from types import SimpleNamespace

    from invoicing.web.open_invoices_in_the_letter import OpenInvoicesInTheLetter

    def older(number: int, amount: str, month: int) -> Any:
        return SimpleNamespace(
            number=number,
            printed_total=Decimal(amount),
            period_printed_from=date(2026, month, 1),
            period_printed_to=date(2026, month, 28),
        )

    open_invoices = OpenInvoicesInTheLetter(
        [older(119, "120.00", 7), older(120, "140.01", 8)]
    )
    summary = "Rechnung Nr. {ALTE RECHNUNG}: {ALTER BETRAG}\nSUMME: bleibt"

    written = open_invoices.one_line_per_invoice(summary)

    assert written.split("\n") == [
        f"Rechnung Nr. 120: 140,01{NON_BREAKING_SPACE}{EURO_SIGN}",
        f"Rechnung Nr. 119: 120,00{NON_BREAKING_SPACE}{EURO_SIGN}",
        "SUMME: bleibt",
    ]


def test_the_month_of_several_open_invoices_spans_them_all() -> None:
    from types import SimpleNamespace

    from invoicing.web.open_invoices_in_the_letter import OpenInvoicesInTheLetter

    def older(number: int, month: int) -> Any:
        return SimpleNamespace(
            number=number,
            printed_total=Decimal("100.00"),
            period_printed_from=date(2026, month, 1),
            period_printed_to=date(2026, month, 28),
        )

    values = OpenInvoicesInTheLetter([older(119, 7), older(120, 8)]).placeholder_values(
        Decimal("150.00")
    )

    assert values["ALTER MONAT"] == "Juli bis August"
    assert values["SUMME"] == f"350,00{NON_BREAKING_SPACE}{EURO_SIGN}"


def test_a_line_about_an_old_invoice_disappears_when_nothing_is_open() -> None:
    from invoicing.web.open_invoices_in_the_letter import OpenInvoicesInTheLetter

    written = OpenInvoicesInTheLetter([]).one_line_per_invoice(
        "Rechnung Nr. {ALTE RECHNUNG}: {ALTER BETRAG}\nPayPal: ich@example.com"
    )

    assert written == "PayPal: ich@example.com"
