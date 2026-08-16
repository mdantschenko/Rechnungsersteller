"""A sample invoice for previews and tests.

The data is invented on purpose: real customer, bank and tax details belong in
the application's database, not in a repository. Structure, column count and
row count match reference invoice no. 114 so the layout can be checked against
it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from invoicing.constant import BillingCycle, TotalRule
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
    address=Address(
        name="Max Mustermann",
        street="Musterstraße 19 B",
        city="12345 Musterstadt",
    ),
    country="Deutschland",
    bank="Musterbank",
    iban="DE00 0000 0000 0000 0000 00",
    bic="MUSTDEFFXXX",
    tax_number="000/0000/0000",
    email="max@example.com",
    paypal="info@example.com",
)

RECIPIENT = Address(
    name="Erika Beispiel",
    street="Beispielstraße 21",
    city="54321 Beispielstadt",
)

TEMPLATE = BillingTemplate(
    unit_price=Decimal("33.33"),
    columns=(
        Column(
            label="Anfahrtskosten",
            total_rule=TotalRule.ADD_PER_ROW,
            placeholder="0 €",
        ),
    ),
)

LESSONS = (
    Lesson(taught_on=date(2026, 5, 20), quantity=Decimal("1")),
    Lesson(taught_on=date(2026, 6, 5), quantity=Decimal("1")),
)


def sample_invoice(issuer: Issuer | None = None) -> Invoice:
    """A fully computed invoice with two rows and one extra column.

    The recipient and the rows are always invented; the sender can be the
    real one, which is what the test mail from the settings screen uses.
    """
    return build_invoice(
        number=114,
        issued_on=date(2026, 6, 18),
        issuer=issuer or ISSUER,
        recipient=RECIPIENT,
        template=TEMPLATE,
        period=period_closing_on(BillingCycle.MONTH_MIDPOINT, date(2026, 6, 15)),
        lessons=LESSONS,
    )
