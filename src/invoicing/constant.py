"""Every constant of the application lives here, grouped by topic.

Only the standard library is imported, so any module can use this file freely.
The enum string values are stored in the database and never change.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, time, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

PACKAGE_DIRECTORY = Path(__file__).resolve().parent
PROJECT_ROOT_DIRECTORY = PACKAGE_DIRECTORY.parents[1]

# --- Locale and formatting ---

GERMAN_LOCALE = "de_DE"
GERMAN_WEEKDAY_NAMES = {
    "MO": "Montag",
    "TU": "Dienstag",
    "WE": "Mittwoch",
    "TH": "Donnerstag",
    "FR": "Freitag",
    "SA": "Samstag",
    "SU": "Sonntag",
}
WEEK_STARTS_ON_MONDAY = 0
TEMPLATE_FILTER_EURO = "euro"
TEMPLATE_FILTER_QUANTITY = "quantity"
TEMPLATE_FILTER_GERMAN_DATE = "german_date"

# --- Money ---

CENT = Decimal("0.01")
TEN_THOUSANDTH = Decimal("0.0001")
ZERO = Decimal("0.00")

# --- Domain enums ---


class ValueSource(StrEnum):
    """Where a column takes its value from."""

    FIXED = "fixed"
    PER_LESSON = "per_lesson"


class ValueKind(StrEnum):
    """How a value is rendered, and whether it can count towards a total."""

    MONEY = "money"
    QUANTITY = "quantity"
    TEXT = "text"


class TotalRule(StrEnum):
    """How a column enters the row total."""

    EXCLUDED = "excluded"
    ADD_PER_ROW = "add_per_row"
    MULTIPLY_BY_QUANTITY = "multiply_by_quantity"


class BillingCycle(StrEnum):
    """Which day of the month a customer's invoice is drawn up on."""

    MONTH_START = "month_start"
    MONTH_MIDPOINT = "month_midpoint"


CLOSING_DAY_OF_MONTH = {
    BillingCycle.MONTH_START: 1,
    BillingCycle.MONTH_MIDPOINT: 15,
}
ONE_DAY = timedelta(days=1)

# --- Business defaults ---

EXTRA_COLUMN_PLACEHOLDER = "/"
DEFAULT_BILLING_UNIT = "h"
DEFAULT_LESSON_DESCRIPTION = "Mathe Nachhilfe"
DEFAULT_LESSON_UNIT_PRICE = Decimal("30.00")
DEFAULT_ISSUER_COUNTRY = "Deutschland"
DEFAULT_INVOICE_FOLDER = "data/invoices"
DEFAULT_LESSON_HORIZON_DAYS = 60
DEFAULT_SMTP_PORT = 587
DEFAULT_REMINDER_MINUTES = 60
DEFAULT_PAYMENT_DAYS = 14

# --- Alarms and the daily round ---

ALARM_RING_EVERY = timedelta(minutes=2)
ALARM_RINGS_AT_MOST = 8
ALARM_CATCH_UP_WINDOW = timedelta(hours=1)
ALARM_CHECK_INTERVAL_SECONDS = 30
MORNING_ROUND_STARTS_AT = time(7, 0)

DeliverPushMessage = Callable[[dict[str, str]], object]

# --- Backup change detection ---

USER_DATA_TABLE_COLUMNS = {
    "customer": (
        "id",
        "name",
        "street",
        "city",
        "status",
        "email",
        "phone",
        "delivery",
        "student_name",
        "student_grade",
        "lesson_address",
        "reminder_at",
        "online",
        "mail_text",
        "reminder_text",
    ),
    "issued_invoice": (
        "id",
        "number",
        "customer_id",
        "issued_on",
        "period_printed_from",
        "period_printed_to",
        "column_labels",
        "printed_total",
        "computed_total",
        "paid_on",
        "sent_on",
        "source_file",
    ),
    "issued_invoice_line": (
        "id",
        "invoice_id",
        "ordinal",
        "taught_on",
        "quantity",
        "unit",
        "description",
        "unit_price",
        "extra_values",
        "total",
    ),
    "payment_reminder": ("id", "invoice_id", "sent_on"),
    "issuer": (
        "id",
        "name",
        "street",
        "city",
        "country",
        "bank",
        "iban",
        "bic",
        "tax_number",
        "email",
        "paypal",
    ),
    "billing_template": (
        "id",
        "customer_id",
        "unit_price",
        "unit",
        "description",
        "cycle",
    ),
    "template_column": (
        "id",
        "template_id",
        "ordinal",
        "label",
        "source",
        "kind",
        "total_rule",
        "default_value",
        "placeholder",
    ),
    "lesson_series": (
        "id",
        "customer_id",
        "recurrence",
        "quantity",
        "starts_on",
        "ends_on",
        "starts_at",
        "active",
    ),
    "exam_grade": ("id", "customer_id", "written_on", "label", "grade"),
    "number_state": ("id", "start", "last_assigned"),
}

USER_DATA_LESSON_COLUMNS = (
    "id",
    "customer_id",
    "series_id",
    "taught_on",
    "starts_at",
    "quantity",
    "status",
    "note",
    "column_values",
    "invoice_id",
)

USER_DATA_SETTINGS_COLUMNS = (
    "password_hash",
    "invoice_folder",
    "lesson_horizon_days",
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_password",
    "smtp_from",
    "reminder_minutes",
    "vapid_private_key",
    "vapid_public_key",
    "show_public_holidays",
    "show_school_holidays",
    "holiday_states",
    "payment_days",
    "auto_send_invoices",
    "backup_passphrase",
)

# --- Holidays ---

GERMAN_FEDERAL_STATES = {
    "BW": "Baden-Württemberg",
    "BY": "Bayern",
    "BE": "Berlin",
    "BB": "Brandenburg",
    "HB": "Bremen",
    "HH": "Hamburg",
    "HE": "Hessen",
    "MV": "Mecklenburg-Vorpommern",
    "NI": "Niedersachsen",
    "NW": "Nordrhein-Westfalen",
    "RP": "Rheinland-Pfalz",
    "SL": "Saarland",
    "SN": "Sachsen",
    "ST": "Sachsen-Anhalt",
    "SH": "Schleswig-Holstein",
    "TH": "Thüringen",
}

FEDERAL_STATE_COLORS = {
    "BW": "#e6550d",
    "BY": "#3182bd",
    "BE": "#31a354",
    "BB": "#756bb1",
    "HB": "#dd1c77",
    "HH": "#fd8d3c",
    "HE": "#e6ab02",
    "MV": "#6baed6",
    "NI": "#74c476",
    "NW": "#2563eb",
    "RP": "#9e9ac8",
    "SL": "#a6761d",
    "SN": "#66a61e",
    "ST": "#e7298a",
    "SH": "#7570b3",
    "TH": "#1b9e77",
}

OPENHOLIDAYS_SCHOOL_HOLIDAYS_URL = "https://openholidaysapi.org/SchoolHolidays"
HOLIDAY_API_TIMEOUT_SECONDS = 20

FetchSchoolHolidays = Callable[[str, date, date], list[dict]]

# --- Mail ---

SMTP_SSL_PORT = 465
IMAP_SSL_PORT = 993
SMTP_TIMEOUT_SECONDS = 30
SENT_FOLDER_CANDIDATES = ("Sent", "Sent Items", "Gesendete Objekte", "INBOX.Sent")
MAIL_NOT_CONFIGURED_MESSAGE = (
    "Der E-Mail-Versand ist noch nicht eingerichtet. Trage Server, "
    "Benutzername und Passwort in den Einstellungen ein."
)

# --- Push ---

PUSH_SUBSCRIPTION_DEAD_STATUS_CODES = (403, 404, 410)
PUSH_MESSAGE_TTL_SECONDS = 3600
PUSH_SEND_TIMEOUT_SECONDS = 10
PUSH_ENDPOINT_LOG_PREFIX_LENGTH = 40

# --- Reports ---

REVENUE_CSV_HEADER = ("Jahr", "Kunde", "Rechnungen", "Summe")

# --- Legacy Markdown parsing ---

EN_DASH = "–"
LEGACY_RECIPIENT_LINE_COUNT = 3

LEGACY_INVOICE_NUMBER_PATTERN = re.compile(r"Rechnung\s+Nr\.?\s*(\d+)")
LEGACY_ISSUE_DATE_PATTERN = re.compile(r"Datum:\s*(\d{2}\.\d{2}\.\d{4})")
LEGACY_PERIOD_PATTERN = re.compile(
    r"vom\s+(\d{2}\.\d{2}\.\d{4})\s+bis zum\s+(\d{2}\.\d{2}\.\d{4})"
)
LEGACY_EXTRA_COLUMN_PATTERN = re.compile(
    r"Anzahl\s+Einheit\s+Bezeichnung\s*/\s*Datum\s+Einzelpreis\s+(.*?)\s+Gesamtpreis"
)
LEGACY_LINE_ITEM_PATTERN = re.compile(
    r"^(\d+(?:,\d+)?)\s+(\w+)\s+(.*?)\s*/\s*(\d{2}\.\d{2}\.\d{4})\s+"
    r"([\d.,]+)\s*€\s+(.*?)\s+([\d.,]+)\s*€$"
)
LEGACY_PRINTED_TOTAL_PATTERN = re.compile(r"Gesamtbetrag\s+([\d.,]+)\s*€")
LEGACY_SETTLED_PATTERN = re.compile(r"wurde bereits am\s+(\d{2}\.\d{2}\.\d{4})")
LEGACY_AMOUNT_PATTERN = re.compile(r"^([\d.]+,\d{2}|\d+)\s*€$")

# --- PDF ---

PDF_RENDERER_AUTOMATIC = "auto"
PDF_PREVIEW_RENDER_SCALE = 2
INVOICE_DOCUMENT_TEMPLATES_DIRECTORY = PACKAGE_DIRECTORY / "pdf" / "documents"
INVOICE_DOCUMENT_FONTS_DIRECTORY = PACKAGE_DIRECTORY / "pdf" / "fonts"
INVOICE_DOCUMENT_FONT_FILES = (
    ("OpenSans-Regular.ttf", 400, "normal"),
    ("OpenSans-Italic.ttf", 400, "italic"),
    ("OpenSans-Bold.ttf", 700, "normal"),
)
INVOICE_PDF_FILE_NAME_PATTERN = "Rechnung Nr {number}"

# --- Storage ---

DATABASE_MIGRATIONS_DIRECTORY = PROJECT_ROOT_DIRECTORY / "migrations"
DEFAULT_DATABASE_LOCATION = Path("data/invoicing.db")

# --- Web ---

SIGN_IN_EXEMPT_PATHS = ("/anmelden", "/static", "/manifest.webmanifest", "/sw.js")
NOTICE_SESSION_KEY = "hinweis"
WEB_TEMPLATES_DIRECTORY = PACKAGE_DIRECTORY / "web" / "templates"
WEB_STATIC_DIRECTORY = PACKAGE_DIRECTORY / "web" / "static"
SIGNED_IN_SESSION_KEY = "signed_in"
SESSION_SECRET_BYTES = 32
PASSWORD_CODE_DIGITS = 6
PASSWORD_CODE_MINUTES = 15
PAYMENT_DAYS_MAXIMUM = 90
REMINDER_MINUTES_MAXIMUM = 1440
BACKUP_PASSPHRASE_LENGTH = 12

PWA_MANIFEST = {
    "name": "Rechnungsersteller",
    "short_name": "Rechnungen",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "background_color": "#ffffff",
    "theme_color": "#ffffff",
    "lang": "de",
    "icons": [
        {"src": "/static/icon-180.png", "sizes": "180x180", "type": "image/png"},
        {
            "src": "/static/icon-512.png",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "any maskable",
        },
    ],
}

# --- Command line ---

DEFAULT_SAMPLE_PDF_PATH = Path("data/sample-invoice.pdf")
DEFAULT_WEB_PORT = 8000
