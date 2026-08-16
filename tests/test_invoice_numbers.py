from __future__ import annotations

import pytest

from invoicing.domain.invoice_number_sequence import InvoiceNumberSequence


def test_starts_at_the_configured_number() -> None:
    sequence = InvoiceNumberSequence(start=115)

    assert sequence.peek() == 115
    assert sequence.assign() == 115


def test_hands_out_consecutive_numbers() -> None:
    sequence = InvoiceNumberSequence(start=115)

    assert [sequence.assign() for _ in range(3)] == [115, 116, 117]


def test_peeking_does_not_consume_a_number() -> None:
    sequence = InvoiceNumberSequence(start=115)

    assert sequence.peek() == sequence.peek() == 115
    assert sequence.assign() == 115


def test_the_start_can_be_moved_before_anything_was_assigned() -> None:
    sequence = InvoiceNumberSequence(start=115)

    sequence.restart_at(200)

    assert sequence.peek() == 200


def test_the_start_cannot_reuse_an_assigned_number() -> None:
    sequence = InvoiceNumberSequence(start=115)
    sequence.assign()
    sequence.assign()

    with pytest.raises(ValueError, match="already assigned"):
        sequence.restart_at(116)


def test_raising_the_start_skips_the_numbers_in_between() -> None:
    sequence = InvoiceNumberSequence(start=115)
    sequence.assign()

    sequence.restart_at(300)

    assert sequence.peek() == 300
    assert sequence.assign() == 300
    assert sequence.assign() == 301
