from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from sqlalchemy import Engine
from sqlmodel import Session, select

from invoicing.scheduling import LessonSeriesMaterialiser
from invoicing.storage.models import Lesson, LessonSeries, LessonStatus

EVERY_TUESDAY = "RRULE:FREQ=WEEKLY;BYDAY=TU"


def _series(
    session: Session, quantity: Decimal = Decimal("1"), **overrides: object
) -> LessonSeries:
    series = LessonSeries(
        customer_id=1,
        recurrence=EVERY_TUESDAY,
        quantity=quantity,
        starts_on=date(2026, 6, 2),
        starts_at=time(16, 0),
        **overrides,  # type: ignore[arg-type]
    )
    session.add(series)
    session.commit()
    return series


def test_writes_out_every_occurrence_up_to_the_horizon(ready_to_bill: Engine) -> None:
    with Session(ready_to_bill) as session:
        _series(session)

        created = LessonSeriesMaterialiser(session).materialise_all_active(
            until=date(2026, 6, 30)
        )
        session.commit()

        assert [lesson.taught_on for lesson in created] == [
            date(2026, 6, 2),
            date(2026, 6, 9),
            date(2026, 6, 16),
            date(2026, 6, 23),
            date(2026, 6, 30),
        ]


def test_carries_the_time_and_quantity_of_the_series(ready_to_bill: Engine) -> None:
    with Session(ready_to_bill) as session:
        _series(session, quantity=Decimal("1.5"))

        first, *_ = LessonSeriesMaterialiser(session).materialise_all_active(
            until=date(2026, 6, 10)
        )

        assert first.starts_at == time(16, 0)
        assert first.quantity == Decimal("1.5")
        assert first.status is LessonStatus.PLANNED


def test_stops_at_the_end_of_the_series(ready_to_bill: Engine) -> None:
    with Session(ready_to_bill) as session:
        _series(session, ends_on=date(2026, 6, 16))

        created = LessonSeriesMaterialiser(session).materialise_all_active(
            until=date(2026, 12, 31)
        )

        assert [lesson.taught_on for lesson in created] == [
            date(2026, 6, 2),
            date(2026, 6, 9),
            date(2026, 6, 16),
        ]


def test_running_it_again_creates_nothing(ready_to_bill: Engine) -> None:
    with Session(ready_to_bill) as session:
        _series(session)
        materialiser = LessonSeriesMaterialiser(session)
        materialiser.materialise_all_active(until=date(2026, 6, 30))
        session.commit()

        again = materialiser.materialise_all_active(until=date(2026, 6, 30))
        session.commit()

        assert again == ()
        assert len(session.exec(select(Lesson)).all()) == 5


def test_extending_the_horizon_adds_only_the_new_dates(ready_to_bill: Engine) -> None:
    with Session(ready_to_bill) as session:
        _series(session)
        materialiser = LessonSeriesMaterialiser(session)
        materialiser.materialise_all_active(until=date(2026, 6, 16))
        session.commit()

        added = materialiser.materialise_all_active(until=date(2026, 6, 30))

        assert [lesson.taught_on for lesson in added] == [
            date(2026, 6, 23),
            date(2026, 6, 30),
        ]


def test_a_series_that_is_switched_off_is_ignored(ready_to_bill: Engine) -> None:
    with Session(ready_to_bill) as session:
        _series(session, active=False)

        materialiser = LessonSeriesMaterialiser(session)
        assert materialiser.materialise_all_active(until=date(2026, 6, 30)) == ()


def test_a_horizon_before_the_series_starts_creates_nothing(
    ready_to_bill: Engine,
) -> None:
    with Session(ready_to_bill) as session:
        _series(session)

        materialiser = LessonSeriesMaterialiser(session)
        assert materialiser.materialise_all_active(until=date(2026, 5, 1)) == ()


def test_finds_lessons_that_are_overdue_and_still_unanswered(
    ready_to_bill: Engine,
) -> None:
    with Session(ready_to_bill) as session:
        _series(session)
        materialiser = LessonSeriesMaterialiser(session)
        lessons = materialiser.materialise_all_active(until=date(2026, 6, 30))
        lessons[0].status = LessonStatus.DONE
        session.commit()

        waiting = materialiser.unanswered_before(day=date(2026, 6, 17))

        assert [lesson.taught_on for lesson in waiting] == [
            date(2026, 6, 9),
            date(2026, 6, 16),
        ]
