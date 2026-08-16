from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine
from sqlmodel import Session, select

from invoicing.billing import draft_for, release
from invoicing.domain.extra_column_rules import ExtraColumnRules
from invoicing.storage.models import (
    Customer,
    IssuedInvoice,
    Lesson,
    LessonStatus,
    NumberState,
)

ISSUED_ON = date(2026, 6, 18)


def _customer(session: Session) -> Customer:
    return session.exec(select(Customer)).one()


def _lesson(
    session: Session,
    taught_on: date,
    status: LessonStatus = LessonStatus.DONE,
    **overrides: object,
) -> Lesson:
    lesson = Lesson(
        customer_id=_customer(session).id or 0,
        taught_on=taught_on,
        quantity=Decimal("1"),
        status=status,
        **overrides,  # type: ignore[arg-type]
    )
    session.add(lesson)
    session.commit()
    return lesson


def test_bills_the_lessons_that_were_ticked_off(
    ready_to_bill: Engine, closing_day: date
) -> None:
    with Session(ready_to_bill) as session:
        _lesson(session, date(2026, 5, 20))
        _lesson(session, date(2026, 6, 5))

        run = draft_for(session, _customer(session), closing_day, ISSUED_ON)

        assert run.invoice is not None
        assert run.invoice.total == Decimal("66.66")
        assert [item.taught_on for item in run.invoice.line_items] == [
            date(2026, 5, 20),
            date(2026, 6, 5),
        ]


def test_an_unanswered_lesson_blocks_the_run(
    ready_to_bill: Engine, closing_day: date
) -> None:
    with Session(ready_to_bill) as session:
        _lesson(session, date(2026, 5, 20))
        _lesson(session, date(2026, 6, 5), status=LessonStatus.PLANNED)

        run = draft_for(session, _customer(session), closing_day, ISSUED_ON)

        assert run.is_blocked
        assert run.invoice is None
        assert [lesson.taught_on for lesson in run.unanswered] == [date(2026, 6, 5)]


def test_a_cancelled_lesson_is_not_billed(
    ready_to_bill: Engine, closing_day: date
) -> None:
    with Session(ready_to_bill) as session:
        _lesson(session, date(2026, 5, 20))
        _lesson(session, date(2026, 6, 5), status=LessonStatus.CANCELLED)

        run = draft_for(session, _customer(session), closing_day, ISSUED_ON)

        assert run.invoice is not None
        assert run.invoice.total == Decimal("33.33")


def test_lessons_outside_the_period_are_left_for_another_invoice(
    ready_to_bill: Engine, closing_day: date
) -> None:
    with Session(ready_to_bill) as session:
        _lesson(session, date(2026, 5, 15))
        _lesson(session, date(2026, 5, 16))
        _lesson(session, date(2026, 6, 15))
        _lesson(session, date(2026, 6, 16))

        run = draft_for(session, _customer(session), closing_day, ISSUED_ON)

        assert run.invoice is not None
        assert [item.taught_on for item in run.invoice.line_items] == [
            date(2026, 5, 16),
            date(2026, 6, 15),
        ]


def test_a_period_without_lessons_produces_no_draft(
    ready_to_bill: Engine, closing_day: date
) -> None:
    with Session(ready_to_bill) as session:
        run = draft_for(session, _customer(session), closing_day, ISSUED_ON)

        assert run.invoice is None
        assert not run.is_blocked


def test_the_extra_column_reaches_the_document(
    ready_to_bill: Engine, closing_day: date
) -> None:
    with Session(ready_to_bill) as session:
        _lesson(session, date(2026, 5, 20))

        run = draft_for(session, _customer(session), closing_day, ISSUED_ON)

        assert run.invoice is not None
        (column,) = run.invoice.columns
        assert column.label == "Anfahrtskosten"
        first_cell = run.invoice.line_items[0].column_values[0]
        assert ExtraColumnRules(column).display(first_cell) == "0 €"


def test_a_draft_only_peeks_at_the_next_number(
    ready_to_bill: Engine, closing_day: date
) -> None:
    with Session(ready_to_bill) as session:
        session.add(NumberState(start=115))
        session.commit()
        _lesson(session, date(2026, 5, 20))

        first = draft_for(session, _customer(session), closing_day, ISSUED_ON)
        second = draft_for(session, _customer(session), closing_day, ISSUED_ON)

        assert first.invoice is not None
        assert second.invoice is not None
        assert first.invoice.number == second.invoice.number == 115


def test_releasing_hands_out_the_number_and_freezes_the_record(
    ready_to_bill: Engine, closing_day: date
) -> None:
    with Session(ready_to_bill) as session:
        session.add(NumberState(start=115))
        session.commit()
        _lesson(session, date(2026, 5, 20))
        run = draft_for(session, _customer(session), closing_day, ISSUED_ON)

        released = release(session, run)
        session.commit()

        assert released.document.number == 115
        assert released.record.number == 115
        assert released.record.printed_total == Decimal("33.33")
        assert released.record.column_labels == ["Anfahrtskosten"]
        assert released.record.lines[0].extra_values == {"Anfahrtskosten": "0 €"}


def test_a_released_lesson_is_not_billed_again(
    ready_to_bill: Engine, closing_day: date
) -> None:
    with Session(ready_to_bill) as session:
        _lesson(session, date(2026, 5, 20))
        release(session, draft_for(session, _customer(session), closing_day, ISSUED_ON))
        session.commit()

        again = draft_for(session, _customer(session), closing_day, ISSUED_ON)

        assert again.invoice is None
        assert len(session.exec(select(IssuedInvoice)).all()) == 1


def test_the_next_release_continues_the_numbering(
    ready_to_bill: Engine, closing_day: date
) -> None:
    with Session(ready_to_bill) as session:
        session.add(NumberState(start=115))
        session.commit()
        _lesson(session, date(2026, 5, 20))
        release(session, draft_for(session, _customer(session), closing_day, ISSUED_ON))
        session.commit()
        _lesson(session, date(2026, 6, 5))

        run = draft_for(session, _customer(session), closing_day, ISSUED_ON)

        assert run.invoice is not None
        assert run.invoice.number == 116


def test_releasing_a_blocked_run_is_refused(
    ready_to_bill: Engine, closing_day: date
) -> None:
    with Session(ready_to_bill) as session:
        _lesson(session, date(2026, 5, 20), status=LessonStatus.PLANNED)
        run = draft_for(session, _customer(session), closing_day, ISSUED_ON)

        with pytest.raises(ValueError, match="unanswered"):
            release(session, run)


def test_a_customer_without_terms_cannot_be_billed(
    ready_to_bill: Engine, closing_day: date
) -> None:
    with Session(ready_to_bill) as session:
        stranger = Customer(name="Ohne Vorlage", street="Weg 1", city="00000 Ort")
        session.add(stranger)
        session.commit()

        with pytest.raises(ValueError, match="no billing template"):
            draft_for(session, stranger, closing_day, ISSUED_ON)
