"""Helper functions used from several places.

Import direction is fixed: this module never imports domain, billing, pdf
or web code — only the standard library, third-party packages, the
constants and the storage models — so every layer can use it freely.
"""

from __future__ import annotations

import base64
import io
import re
import secrets
import sqlite3
from collections.abc import Iterable
from datetime import date, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from sqlmodel import Session, col, select
from starlette.responses import RedirectResponse

from invoicing.constant import (
    BACKUP_PASSPHRASE_LENGTH,
    CENT,
    GERMAN_WEEKDAY_NAMES,
    NOTICE_SESSION_KEY,
    TEN_THOUSANDTH,
    ZERO,
)
from invoicing.storage.models import BillingTemplate

if TYPE_CHECKING:
    from starlette.requests import Request

    from invoicing.storage.models import AppSettings


def round_to_cents(amount: Decimal | int | str) -> Decimal:
    """Round half up to whole cents, the way invoices are rounded."""
    return Decimal(amount).quantize(CENT, rounding=ROUND_HALF_UP)


def round_quantity(amount: Decimal) -> Decimal:
    """Round a count to four places, fine enough for fractions of an hour."""
    return amount.quantize(TEN_THOUSANDTH, rounding=ROUND_HALF_UP)


def sum_of_cents(amounts: Iterable[Decimal]) -> Decimal:
    """Sum amounts starting from the project-wide two-decimal zero."""
    return sum(amounts, start=ZERO)


def parse_german_amount(value: str) -> Decimal | None:
    """Read an amount the way a person writes it (``20,00 €``, ``1.234,56``).

    Returns:
        The parsed amount, or None when nothing readable remains.
    """
    cleaned = value.replace("€", "").replace(" ", "").strip()
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def parse_german_date(text: str) -> date:
    """Read a German date such as ``11.03.2024``."""
    day, month, year = (int(part) for part in text.split("."))
    return date(year, month, day)


def parse_optional_clock_time(value: str) -> time | None:
    """Read ``14:30`` from a form field; an empty field means no time."""
    return time.fromisoformat(value) if value else None


def collapse_table_markup(raw: str) -> str:
    """Flatten a Markdown table line into single-spaced plain text."""
    return re.sub(r"\s+", " ", raw.replace("|", " ")).strip()


def base64url_without_padding(raw: bytes) -> str:
    """Encode bytes as base64url without the trailing ``=`` padding."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def whatsapp_number(phone: str | None) -> str:
    """The digits wa.me expects: country code first, no plus, no zero."""
    digits = "".join(character for character in phone or "" if character.isdigit())
    if digits.startswith("00"):
        return digits[2:]
    if digits.startswith("0"):
        return f"49{digits[1:]}"
    return digits


def hours_per_unit(unit: str) -> Decimal:
    """How many hours one billing unit stands for: ``h`` is 1, ``1,5h`` is 1.5."""
    number = parse_german_amount(
        "".join(char for char in unit if char.isdigit() or char in ",.")
    )
    if number is None or number <= 0:
        return Decimal(1)
    return number


def recurrence_label(recurrence: str) -> str:
    """The recurrence rule as a short label: ``Wöchentlich``."""
    if "FREQ=WEEKLY" in recurrence:
        return "Alle zwei Wochen" if "INTERVAL=2" in recurrence else "Wöchentlich"
    return "Serie"


def recurrence_words(recurrence: str) -> str:
    """The recurrence rule as a German sentence: ``Jeden zweiten Dienstag``."""
    if "FREQ=WEEKLY" not in recurrence:
        return recurrence
    day = next(
        (
            name
            for code, name in GERMAN_WEEKDAY_NAMES.items()
            if f"BYDAY={code}" in recurrence
        ),
        None,
    )
    if day is None:
        return recurrence_label(recurrence)
    return f"Jeden zweiten {day}" if "INTERVAL=2" in recurrence else f"Jeden {day}"


def planning_horizon(settings: AppSettings, today: date) -> date:
    """How far ahead the series are written out as individual lessons."""
    return today + timedelta(days=settings.lesson_horizon_days)


def billing_templates_by_customer(
    session: Session, customer_ids: list[int]
) -> dict[int, BillingTemplate]:
    """The billing template of each given customer, keyed by customer id."""
    return {
        terms.customer_id: terms
        for terms in session.exec(
            select(BillingTemplate).where(
                col(BillingTemplate.customer_id).in_(customer_ids)
            )
        ).all()
    }


def mailbox_address_of(settings: AppSettings) -> str:
    """The account's own address: the From address, the login as fallback."""
    return settings.smtp_from or settings.smtp_user or ""


def ensure_backup_passphrase(session: Session, settings: AppSettings) -> str:
    """The passphrase backups are sealed with, created when first needed."""
    passphrase = settings.backup_passphrase
    if not passphrase:
        passphrase = secrets.token_urlsafe(BACKUP_PASSPHRASE_LENGTH)
        settings.backup_passphrase = passphrase
        session.add(settings)
    return passphrase


def sealed_sqlite_copy(database: Path, passphrase: str) -> bytes:
    """A consistent snapshot of the SQLite database, zipped and AES-sealed."""
    import pyzipper  # deferred so that importing utils never costs the zip stack

    with TemporaryDirectory() as folder:
        snapshot = Path(folder) / database.name
        source = sqlite3.connect(database)
        try:
            copy = sqlite3.connect(snapshot)
            try:
                source.backup(copy)
            finally:
                copy.close()
        finally:
            source.close()
        buffer = io.BytesIO()
        with pyzipper.AESZipFile(
            buffer, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES
        ) as archive:
            archive.setpassword(passphrase.encode())
            archive.write(snapshot, arcname=database.name)
        return buffer.getvalue()


def safe_back_redirect(back: str) -> RedirectResponse:
    """Back to the page a form came from, but only to paths inside the app."""
    return RedirectResponse(back if back.startswith("/") else "/", status_code=303)


def notice_redirect(request: Request, path: str, message: str) -> RedirectResponse:
    """Back to ``path`` with a toast message.

    The message travels in the session, out of reach of crafted links.
    """
    request.session[NOTICE_SESSION_KEY] = message
    return RedirectResponse(path, status_code=303)
