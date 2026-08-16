"""Checks against two invoices that were actually sent, no. 114 and no. 70."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from invoicing.constant import BillingCycle, TotalRule, ValueSource
from invoicing.domain.billing_period import period_closing_on
from invoicing.domain.columns import Column
from invoicing.domain.invoice import (
    Address,
    BillingTemplate,
    Invoice,
    Issuer,
    Lesson,
    build_invoice,
)

ISSUER = Issuer(
    address=Address(name="Max Mustermann", street="Musterstraße 1", city="12345 Ort"),
    country="Deutschland",
    bank="Musterbank",
    iban="DE00 0000 0000 0000 0000 00",
    bic="MUSTDEFFXXX",
    tax_number="000/0000/0000",
    email="max@example.com",
    paypal="info@example.com",
)

RECIPIENT = Address(name="Erika Beispiel", street="Beispielweg 2", city="54321 Stadt")

TRAVEL_COST = Column(
    label="Anfahrtskosten",
    total_rule=TotalRule.ADD_PER_ROW,
    placeholder="0 €",
)

EXERCISE_SHEETS = Column(
    label="Übungsaufgaben",
    source=ValueSource.PER_LESSON,
    total_rule=TotalRule.ADD_PER_ROW,
    default_value=Decimal("20.00"),
)


def invoice_for(
    template: BillingTemplate,
    period_closes_on: date,
    lessons: Sequence[Lesson],
    cycle: BillingCycle,
) -> Invoice:
    return build_invoice(
        number=1,
        issued_on=period_closes_on,
        issuer=ISSUER,
        recipient=RECIPIENT,
        template=template,
        period=period_closing_on(cycle, period_closes_on),
        lessons=lessons,
    )


def test_reproduces_invoice_114() -> None:
    invoice = invoice_for(
        BillingTemplate(unit_price=Decimal("33.33"), columns=(TRAVEL_COST,)),
        date(2026, 6, 15),
        [
            Lesson(taught_on=date(2026, 5, 20), quantity=Decimal("1")),
            Lesson(taught_on=date(2026, 6, 5), quantity=Decimal("1")),
        ],
        BillingCycle.MONTH_MIDPOINT,
    )

    assert [item.total for item in invoice.line_items] == [
        Decimal("33.33"),
        Decimal("33.33"),
    ]
    assert invoice.total == Decimal("66.66")


def test_reproduces_invoice_70_with_its_per_lesson_surcharges() -> None:
    invoice = invoice_for(
        BillingTemplate(unit_price=Decimal("26.67"), columns=(EXERCISE_SHEETS,)),
        date(2025, 6, 1),
        [
            Lesson(taught_on=date(2025, 5, 5), quantity=Decimal("2")),
            Lesson(
                taught_on=date(2025, 5, 7),
                quantity=Decimal("1"),
                column_values={"Übungsaufgaben": None},
            ),
            Lesson(taught_on=date(2025, 5, 12), quantity=Decimal("1")),
            Lesson(taught_on=date(2025, 5, 19), quantity=Decimal("1")),
            Lesson(
                taught_on=date(2025, 5, 19),
                quantity=Decimal("0.5"),
                column_values={"Übungsaufgaben": None},
            ),
        ],
        BillingCycle.MONTH_START,
    )

    assert [item.total for item in invoice.line_items] == [
        Decimal("73.34"),
        Decimal("26.67"),
        Decimal("46.67"),
        Decimal("46.67"),
        Decimal("13.34"),
    ]
    assert invoice.total == Decimal("206.69")


def test_rounding_per_row_beats_rounding_the_exact_sum() -> None:
    invoice = invoice_for(
        BillingTemplate(unit_price=Decimal("33.333"), columns=()),
        date(2026, 6, 15),
        [
            Lesson(taught_on=date(2026, 5, 20), quantity=Decimal("1")),
            Lesson(taught_on=date(2026, 6, 5), quantity=Decimal("1")),
        ],
        BillingCycle.MONTH_MIDPOINT,
    )

    assert invoice.total == Decimal("66.66")
    assert invoice.total == sum(item.total for item in invoice.line_items)


def test_lessons_outside_the_period_are_left_out() -> None:
    invoice = invoice_for(
        BillingTemplate(unit_price=Decimal("25.00"), columns=()),
        date(2026, 6, 15),
        [
            Lesson(taught_on=date(2026, 5, 15), quantity=Decimal("1")),
            Lesson(taught_on=date(2026, 5, 16), quantity=Decimal("1")),
            Lesson(taught_on=date(2026, 6, 15), quantity=Decimal("1")),
            Lesson(taught_on=date(2026, 6, 16), quantity=Decimal("1")),
        ],
        BillingCycle.MONTH_MIDPOINT,
    )

    assert [item.taught_on for item in invoice.line_items] == [
        date(2026, 5, 16),
        date(2026, 6, 15),
    ]


def test_rows_come_out_in_date_order() -> None:
    invoice = invoice_for(
        BillingTemplate(unit_price=Decimal("25.00"), columns=()),
        date(2026, 6, 15),
        [
            Lesson(taught_on=date(2026, 6, 5), quantity=Decimal("1")),
            Lesson(taught_on=date(2026, 5, 20), quantity=Decimal("1")),
        ],
        BillingCycle.MONTH_MIDPOINT,
    )

    assert [item.taught_on for item in invoice.line_items] == [
        date(2026, 5, 20),
        date(2026, 6, 5),
    ]


def test_an_empty_period_yields_an_invoice_without_rows() -> None:
    invoice = invoice_for(
        BillingTemplate(unit_price=Decimal("25.00"), columns=()),
        date(2026, 6, 15),
        [],
        BillingCycle.MONTH_MIDPOINT,
    )

    assert invoice.line_items == ()
    assert invoice.total == Decimal("0.00")


def test_the_row_label_carries_description_and_date() -> None:
    invoice = invoice_for(
        BillingTemplate(unit_price=Decimal("25.00"), columns=()),
        date(2026, 6, 15),
        [Lesson(taught_on=date(2026, 5, 20), quantity=Decimal("1"))],
        BillingCycle.MONTH_MIDPOINT,
    )

    assert invoice.line_items[0].label == "Mathe Nachhilfe / 20.05.2026"


def test_the_return_address_line_matches_the_printed_wording() -> None:
    assert ISSUER.return_address_line == "Max Mustermann – Musterstraße 1 - 12345 Ort"
