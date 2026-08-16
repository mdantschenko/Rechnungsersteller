"""The Jinja filters the web pages and the PDF documents share.

Both environments print money, quantities and dates the German way. One
registration keeps a page and the invoice it previews from ever formatting
the same amount differently.
"""

from __future__ import annotations

from jinja2 import Environment

from invoicing.constant import (
    TEMPLATE_FILTER_EURO,
    TEMPLATE_FILTER_GERMAN_DATE,
    TEMPLATE_FILTER_QUANTITY,
)
from invoicing.domain.dates import german_date
from invoicing.domain.money import format_euro, format_quantity


def install_german_filters(environment: Environment) -> None:
    environment.filters[TEMPLATE_FILTER_EURO] = format_euro
    environment.filters[TEMPLATE_FILTER_QUANTITY] = format_quantity
    environment.filters[TEMPLATE_FILTER_GERMAN_DATE] = german_date
