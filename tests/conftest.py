"""Invented stand-ins for the Word exports, in every shape they really take.

The rows below are deliberately inconsistent: a full pipe table, a
half-collapsed one and a plain line, because the real exports mix all three
inside a single document. Names, addresses and amounts are made up.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session, select

from invoicing.constant import BillingCycle, TotalRule, ValueSource
from invoicing.storage.invoice_database import InvoiceDatabase
from invoicing.storage.models import (
    AppSettings,
    BillingTemplate,
    Customer,
    CustomerStatus,
    Issuer,
    NumberState,
    TemplateColumn,
)
from invoicing.web import create_app
from invoicing.web.password_gate import PasswordGate

COLLECTED = """\
|      Erika Muster – Musterweg 1 - 12345 Musterstadt  |     |     |
| ---------------------------------------------------- | --- | --- |

|                      |     |     |
| -------------------- | --- | --- |
|     Anna Beispiel    |     |     |
|     Beispielweg 3    |     |     |
|     54321 Beispiel   |     |     |
|                      |     |     |

Datum: 02.06.2025
Rechnung Nr. 12
Berechnung für den Zeitraum vom 01.05.2025 bis zum 31.05.2025

Anzahl  Einheit  Bezeichnung / Datum  Einzelpreis  Anfahrtskosten  Gesamtpreis
| 1   | h  Mathe Nachhilfe  / 05.05.2025  |     |     | 25,00 €  |     | 0 €  | 25,00 €  |
| --- | --------------------------------- | --- | --- | -------- | --- | ---- | -------- |
2  h  Mathe Nachhilfe  / 12.05.2025  25,00 €  0 €  50,00 €
|     | Gesamtbetrag                      |     |     |          |     |      | 75,00 €  |

Gemäß § 19 UstG enthält der Rechnungsbetrag keine Umsatzsteuer.

Zahlungsbedingungen: Zahlung innerhalb von 14 Tagen ab Rechnungseingang ohne Abzüge.


|      Erika Muster – Musterweg 1 - 12345 Musterstadt  |     |     |
| ---------------------------------------------------- | --- | --- |

|                      |     |     |
| -------------------- | --- | --- |
|     Bernd Beispiel   |     |     |
|     Beispielweg 9    |     |     |
|     54321 Beispiel   |     |     |
|                      |     |     |

Datum: 18.07.2025
| Rechnung Nr. 13  |     |     |
| ---------------- | --- | --- |
Berechnung für den Zeitraum vom 15.06.2025 bis zum 15.07.2025

Anzahl  Einheit  Bezeichnung / Datum  Einzelpreis  Übungsaufgaben  Gesamtpreis
| 2    | h   | Mathe Nachhilfe  / 16.06.2025  |     | 26,67 €  | 20,00 €  | 73,34 €  |
| 0,5  | h   | Mathe Nachhilfe  / 15.07.2025  |     | 26,67 €  | /        | 13,34 €  |
|      |     | Gesamtbetrag                   |     |          |          | 86,68 €  |

Gemäß § 19 UstG enthält der Rechnungsbetrag keine Umsatzsteuer.

Der Rechnungsbetrag in Höhe von 86,68 € wurde bereits am 20.07.2025 dankend erhalten/per
Überweisung beglichen.
"""

SELF_CONTRADICTING = """\
|      Erika Muster – Musterweg 1 - 12345 Musterstadt  |     |     |
| ---------------------------------------------------- | --- | --- |

|                      |     |     |
| -------------------- | --- | --- |
|     Carla Beispiel   |     |     |
|     Beispielweg 5    |     |     |
|     54321 Beispiel   |     |     |
|                      |     |     |

Datum: 15.03.2025
Rechnung Nr. 20
Berechnung für den Zeitraum vom 01.04.2025 bis zum 30.04.2025

Anzahl  Einheit  Bezeichnung / Datum  Einzelpreis  Anfahrtskosten  Gesamtpreis
1  h  Mathe Nachhilfe  / 07.04.2025  26,67 €  /  26,67 €
1  h  Mathe Nachhilfe  / 07.04.2024  26,67 €  /  26,67 €
|     | Gesamtbetrag                  |     |     |     |     | 53,33 €  |

Gemäß § 19 UstG enthält der Rechnungsbetrag keine Umsatzsteuer.
"""


@pytest.fixture
def collected_document() -> str:
    """Two invoices in one file, the way the yearly collection looks."""
    return COLLECTED


@pytest.fixture
def self_contradicting_document() -> str:
    """An invoice whose total and whose lesson dates are both wrong."""
    return SELF_CONTRADICTING


@pytest.fixture
def archive(tmp_path: Path, collected_document: str) -> Path:
    """A folder holding the collected document."""
    (tmp_path / "collected.md").write_text(collected_document, encoding="utf-8")
    return tmp_path


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    """An empty database with the schema brought up to date."""
    return InvoiceDatabase(tmp_path / "invoicing.db").open()


@pytest.fixture
def ready_to_bill(engine: Engine) -> Engine:
    """A database holding sender details, one active customer and their terms."""
    with Session(engine) as session:
        session.add(
            Issuer(
                name="Max Mustermann",
                street="Musterstraße 19 B",
                city="12345 Musterstadt",
                bank="Musterbank",
                iban="DE00 0000 0000 0000 0000 00",
                bic="MUSTDEFFXXX",
                tax_number="000/0000/0000",
                email="max@example.com",
                paypal="info@example.com",
            )
        )
        customer = Customer(
            name="Erika Beispiel",
            street="Beispielstraße 21",
            city="54321 Beispielstadt",
            status=CustomerStatus.ACTIVE,
        )
        session.add(customer)
        session.flush()
        template = BillingTemplate(
            customer_id=customer.id or 0,
            unit_price=Decimal("33.33"),
            cycle=BillingCycle.MONTH_MIDPOINT,
        )
        session.add(template)
        session.flush()
        session.add(
            TemplateColumn(
                template_id=template.id,
                ordinal=0,
                label="Anfahrtskosten",
                source=ValueSource.FIXED,
                total_rule=TotalRule.ADD_PER_ROW,
                placeholder="0 €",
            )
        )
        session.commit()
    return engine


@pytest.fixture
def password() -> str:
    """The password the test application is locked with."""
    return "ein-gutes-passwort"


@pytest.fixture
def location(tmp_path: Path, password: str) -> Path:
    """A database ready for the web application: password, sender, numbers."""
    place = tmp_path / "invoicing.db"
    engine = InvoiceDatabase(place).open()
    with Session(engine) as session:
        PasswordGate(session).set_password(password)
        settings = session.exec(select(AppSettings)).one()
        settings.invoice_folder = str(tmp_path / "invoices")
        session.add(settings)
        session.add(NumberState(start=115))
        session.add(
            Issuer(
                name="Max Mustermann",
                street="Musterstraße 19 B",
                city="12345 Musterstadt",
                bank="Musterbank",
                iban="DE00 0000 0000 0000 0000 00",
                bic="MUSTDEFFXXX",
                tax_number="000/0000/0000",
                email="max@example.com",
                paypal="info@example.com",
            )
        )
        session.commit()
    return place


@pytest.fixture
def stranger(location: Path) -> TestClient:
    """A browser that has not signed in."""
    return TestClient(create_app(location))


@pytest.fixture
def client(stranger: TestClient, password: str) -> TestClient:
    """A browser that has signed in."""
    stranger.post("/anmelden", data={"password": password})
    return stranger


@pytest.fixture
def closing_day() -> date:
    """The day the sample customer's period closes."""
    return date(2026, 6, 15)
