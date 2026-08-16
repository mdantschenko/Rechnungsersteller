"""Reading invoices that were written in Word and exported as Markdown.

The export is not consistent. The same row turns up as a full pipe table, as a
half-collapsed one, and as plain text separated by runs of spaces. Stripping
the pipes and collapsing whitespace flattens all three into one shape that a
single pattern matches.

Nothing here is tied to a particular sender. An invoice is located by its
number, its recipient is read from the lines above that number, and the
sender's own return address is recognised only by the en dash it contains.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from invoicing.constant import (
    EN_DASH,
    LEGACY_AMOUNT_PATTERN,
    LEGACY_EXTRA_COLUMN_PATTERN,
    LEGACY_INVOICE_NUMBER_PATTERN,
    LEGACY_ISSUE_DATE_PATTERN,
    LEGACY_LINE_ITEM_PATTERN,
    LEGACY_PERIOD_PATTERN,
    LEGACY_PRINTED_TOTAL_PATTERN,
    LEGACY_RECIPIENT_LINE_COUNT,
    LEGACY_SETTLED_PATTERN,
    ZERO,
)
from invoicing.domain.invoice import Address
from invoicing.domain.money import round_to_cents


@dataclass(frozen=True, slots=True)
class ParsedLine:
    """One row of an old invoice, exactly as it was printed."""

    taught_on: date
    quantity: Decimal
    unit: str
    description: str
    unit_price: Decimal
    extra_printed: str
    extra_amount: Decimal | None
    total: Decimal


@dataclass(frozen=True, slots=True)
class ParsedInvoice:
    """An old invoice, read back from its document."""

    number: int
    issued_on: date
    recipient: Address
    printed_from: date
    printed_to: date
    extra_column_label: str | None
    lines: tuple[ParsedLine, ...]
    printed_total: Decimal
    paid_on: date | None
    source_file: str

    @property
    def computed_total(self) -> Decimal:
        """What the printed rows add up to, which is not always the printed total."""
        return sum((line.total for line in self.lines), start=ZERO)

    def lessons_outside_the_printed_period(self) -> tuple[ParsedLine, ...]:
        """Rows whose date lies outside the range the document itself states.

        Both ends count as inside. The point is to find plain mistakes, such as
        the three lessons on invoice 40 that carry the wrong year, without
        taking a position on which invoice a boundary day belongs to.
        """
        return tuple(
            line
            for line in self.lines
            if not self.printed_from <= line.taught_on <= self.printed_to
        )


@dataclass(frozen=True, slots=True)
class NumberConflict:
    """The same invoice number read differently from two documents."""

    number: int
    first_source: str
    second_source: str


@dataclass(frozen=True, slots=True)
class ArchiveReading:
    """Everything found in a folder of old invoices."""

    invoices: tuple[ParsedInvoice, ...]
    conflicts: tuple[NumberConflict, ...]


def read_archive(directory: Path) -> ArchiveReading:
    """Read every Markdown invoice below `directory`, keeping each number once.

    The same invoice usually exists both on its own and inside a collected
    file. Repeats are dropped; repeats that disagree are reported instead.
    """
    by_number: dict[int, ParsedInvoice] = {}
    conflicts: list[NumberConflict] = []
    for document in sorted(directory.rglob("*.md")):
        for invoice in read_document(document):
            _record_invoice(invoice, by_number, conflicts)
    return ArchiveReading(
        invoices=tuple(by_number[number] for number in sorted(by_number)),
        conflicts=tuple(conflicts),
    )


def _record_invoice(
    invoice: ParsedInvoice,
    by_number: dict[int, ParsedInvoice],
    conflicts: list[NumberConflict],
) -> None:
    seen = by_number.get(invoice.number)
    if seen is None:
        by_number[invoice.number] = invoice
        return
    if _describe_same_invoice(seen, invoice):
        return
    conflicts.append(
        NumberConflict(invoice.number, seen.source_file, invoice.source_file)
    )


def read_document(document: Path) -> Iterator[ParsedInvoice]:
    """Read every invoice contained in one Markdown file."""
    lines = [_flatten(raw) for raw in document.read_text(encoding="utf-8").splitlines()]
    anchors = [
        index
        for index, line in enumerate(lines)
        if LEGACY_INVOICE_NUMBER_PATTERN.search(line)
    ]
    for position, anchor in enumerate(anchors):
        end = anchors[position + 1] if position + 1 < len(anchors) else len(lines)
        yield _read_invoice(lines, anchor, end, document.name)


def _read_invoice(
    lines: Sequence[str], anchor: int, end: int, source: str
) -> ParsedInvoice:
    number = int(
        _require(LEGACY_INVOICE_NUMBER_PATTERN.search(lines[anchor]), source).group(1)
    )
    body = "\n".join(lines[anchor:end])
    period = _require(LEGACY_PERIOD_PATTERN.search(body), f"{source}, invoice {number}")
    extra_column = LEGACY_EXTRA_COLUMN_PATTERN.search(body)
    total = _require(
        LEGACY_PRINTED_TOTAL_PATTERN.search(body), f"{source}, invoice {number}"
    )
    settled = LEGACY_SETTLED_PATTERN.search(body)
    return ParsedInvoice(
        number=number,
        issued_on=_issue_date_above(lines, anchor, number, source),
        recipient=_recipient_above(lines, anchor, number, source),
        printed_from=_german_date(period.group(1)),
        printed_to=_german_date(period.group(2)),
        extra_column_label=extra_column.group(1).strip() if extra_column else None,
        lines=tuple(_read_lines(lines[anchor:end])),
        printed_total=_amount(total.group(1)),
        paid_on=_german_date(settled.group(1)) if settled else None,
        source_file=source,
    )


def _read_lines(block: Sequence[str]) -> Iterator[ParsedLine]:
    for line in block:
        match = LEGACY_LINE_ITEM_PATTERN.match(line)
        if match is None:
            continue
        extra_printed = match.group(6).strip()
        yield ParsedLine(
            taught_on=_german_date(match.group(4)),
            quantity=_amount(match.group(1)),
            unit=match.group(2),
            description=match.group(3).strip(),
            unit_price=_amount(match.group(5)),
            extra_printed=extra_printed,
            extra_amount=_extra_amount(extra_printed),
            total=_amount(match.group(7)),
        )


def _issue_date_above(
    lines: Sequence[str], anchor: int, number: int, source: str
) -> date:
    for index in range(anchor, -1, -1):
        found = LEGACY_ISSUE_DATE_PATTERN.search(lines[index])
        if found:
            return _german_date(found.group(1))
        if EN_DASH in lines[index]:
            break
    raise ValueError(f"no issue date above invoice {number} in {source}")


def _recipient_above(
    lines: Sequence[str], anchor: int, number: int, source: str
) -> Address:
    collected: list[str] = []
    for index in range(anchor - 1, -1, -1):
        line = lines[index]
        if EN_DASH in line:
            break
        if not line or _is_rule(line) or LEGACY_ISSUE_DATE_PATTERN.search(line):
            continue
        collected.append(line)
    if len(collected) != LEGACY_RECIPIENT_LINE_COUNT:
        raise ValueError(
            f"expected {LEGACY_RECIPIENT_LINE_COUNT} address lines above invoice "
            f"{number} in {source}, found {collected}"
        )
    city, street, name = collected
    return Address(name=name, street=street, city=city)


def _describe_same_invoice(one: ParsedInvoice, other: ParsedInvoice) -> bool:
    return (
        one.recipient == other.recipient
        and one.printed_from == other.printed_from
        and one.printed_to == other.printed_to
        and one.printed_total == other.printed_total
        and one.lines == other.lines
    )


def _extra_amount(printed: str) -> Decimal | None:
    match = LEGACY_AMOUNT_PATTERN.match(printed)
    return _amount(match.group(1)) if match else None


def _flatten(raw: str) -> str:
    return re.sub(r"\s+", " ", raw.replace("|", " ")).strip()


def _is_rule(line: str) -> bool:
    return set(line) <= set("- ")


def _german_date(text: str) -> date:
    day, month, year = (int(part) for part in text.split("."))
    return date(year, month, day)


def _amount(text: str) -> Decimal:
    return round_to_cents(text.replace(".", "").replace(",", "."))


def _require(match: re.Match[str] | None, where: str) -> re.Match[str]:
    if match is None:
        raise ValueError(f"unreadable invoice in {where}")
    return match
