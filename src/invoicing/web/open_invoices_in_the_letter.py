"""The part of a customer's letter that speaks about invoices still unpaid.

A letter may carry a ``{WENN OFFEN} ... {ENDE}`` block: whatever stands
between the two markers is printed only when the customer still owes an
older invoice. The markers themselves never reach the customer.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal

from invoicing.constant import (
    OPEN_INVOICE_BLOCK_MARKER_PATTERN,
    OPEN_INVOICE_LAST_NUMBER_SEPARATOR,
    OPEN_INVOICE_NUMBER_SEPARATOR,
    OPEN_INVOICE_PLACEHOLDER_NAMES,
)
from invoicing.german_formatter import german_formatter
from invoicing.storage.models import IssuedInvoice
from invoicing.utils import placeholder_names_in, sum_of_cents


class OpenInvoicesInTheLetter:
    """Settles the conditional block and the placeholders that go with it."""

    def __init__(self, still_open: Sequence[IssuedInvoice]) -> None:
        self._still_open = sorted(still_open, key=lambda invoice: invoice.number)

    @staticmethod
    def is_spoken_about_in(text: str) -> bool:
        """Whether the letter uses the block or one of its own placeholders."""
        if re.search(OPEN_INVOICE_BLOCK_MARKER_PATTERN, text, re.IGNORECASE):
            return True
        return bool(placeholder_names_in(text) & set(OPEN_INVOICE_PLACEHOLDER_NAMES))

    def placeholder_values(self, new_invoice_total: Decimal) -> dict[str, str]:
        """What the open invoices put in place of their placeholders."""
        open_total = sum_of_cents(invoice.printed_total for invoice in self._still_open)
        return {
            "ALTE RECHNUNG": self._numbers_youngest_first(),
            "ALTER BETRAG": german_formatter.format_euro(open_total),
            "ALTER MONAT": self._months_covered(),
            "SUMME": german_formatter.format_euro(new_invoice_total + open_total),
        }

    def resolved(self, text: str) -> str:
        """The letter with the block kept or dropped and every marker gone."""
        keep_the_block = bool(self._still_open)
        pieces: list[str] = []
        cursor = 0
        inside_the_block = False
        for marker in re.finditer(
            OPEN_INVOICE_BLOCK_MARKER_PATTERN, text, re.IGNORECASE
        ):
            start, end = self._span_including_a_line_of_its_own(text, marker)
            if keep_the_block or not inside_the_block:
                pieces.append(text[cursor : max(start, cursor)])
            cursor = max(end, cursor)
            inside_the_block = marker.group("block_start") is not None
        if keep_the_block or not inside_the_block:
            pieces.append(text[cursor:])
        return "".join(pieces)

    def _numbers_youngest_first(self) -> str:
        numbers = [str(invoice.number) for invoice in reversed(self._still_open)]
        if not numbers:
            return ""
        if len(numbers) == 1:
            return numbers[0]
        earlier = OPEN_INVOICE_NUMBER_SEPARATOR.join(numbers[:-1])
        return f"{earlier}{OPEN_INVOICE_LAST_NUMBER_SEPARATOR}{numbers[-1]}"

    def _months_covered(self) -> str:
        if not self._still_open:
            return ""
        return german_formatter.months_covered(
            min(invoice.period_printed_from for invoice in self._still_open),
            max(invoice.period_printed_to for invoice in self._still_open),
        )

    @staticmethod
    def _span_including_a_line_of_its_own(
        text: str, marker: re.Match[str]
    ) -> tuple[int, int]:
        start, end = marker.span()
        line_start = text.rfind("\n", 0, start) + 1
        line_break = text.find("\n", end)
        rest_of_line = text[end:] if line_break < 0 else text[end:line_break]
        stands_alone = not text[line_start:start].strip() and not rest_of_line.strip()
        if not stands_alone:
            return start, end
        return line_start, len(text) if line_break < 0 else line_break + 1
