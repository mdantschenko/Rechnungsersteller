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
from invoicing.german_formatter import GermanFormatter


class GermanTemplateFilters:
    """Puts one formatter's methods behind the shared template filter names.

    The filter names are a contract with the templates.
    """

    def __init__(self, formatter: GermanFormatter) -> None:
        self.formatter = formatter

    def install_into(self, environment: Environment) -> None:
        environment.filters[TEMPLATE_FILTER_EURO] = self.formatter.format_euro
        environment.filters[TEMPLATE_FILTER_QUANTITY] = self.formatter.format_quantity
        environment.filters[TEMPLATE_FILTER_GERMAN_DATE] = (
            self.formatter.format_german_date
        )
