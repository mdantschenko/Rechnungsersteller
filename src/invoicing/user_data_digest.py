"""One fingerprint over everything the user actually entered.

The weekly backup mail compares this fingerprint with the one stored after
the last successful backup, so that bookkeeping noise — alarm counters,
daily-round markers, lessons merely written out from a series — never
triggers a backup on its own.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence

from sqlmodel import Session, SQLModel, select

from invoicing.constant import (
    USER_DATA_LESSON_COLUMNS,
    USER_DATA_SETTINGS_COLUMNS,
    USER_DATA_TABLE_COLUMNS,
)
from invoicing.storage.models import (
    AppSettings,
    BillingTemplate,
    Customer,
    ExamGrade,
    IssuedInvoice,
    IssuedInvoiceLine,
    Issuer,
    Lesson,
    LessonSeries,
    LessonStatus,
    NumberState,
    PaymentReminder,
    TemplateColumn,
)


class UserDataDigest:
    """Hashes every record the user entered into one comparable value.

    Table and column names flow into the hash material, so a schema change
    causes exactly one additional backup — deliberately.
    """

    _FULLY_HASHED_MODELS: tuple[type[SQLModel], ...] = (
        Customer,
        IssuedInvoice,
        IssuedInvoiceLine,
        PaymentReminder,
        Issuer,
        BillingTemplate,
        TemplateColumn,
        LessonSeries,
        ExamGrade,
        NumberState,
    )

    def __init__(self, session: Session) -> None:
        self._session = session

    def value(self) -> str:
        """The SHA-256 fingerprint of all user data, as a hex string."""
        material = hashlib.sha256()
        for table_name, columns, records in self._canonical_dump():
            material.update(json.dumps([table_name, *columns]).encode())
            for record in records:
                row = [self._as_text(getattr(record, name)) for name in columns]
                material.update(json.dumps(row).encode())
        return material.hexdigest()

    def _canonical_dump(
        self,
    ) -> Iterator[tuple[str, tuple[str, ...], Sequence[SQLModel]]]:
        for model in self._FULLY_HASHED_MODELS:
            table_name = str(model.__tablename__)
            columns = USER_DATA_TABLE_COLUMNS[table_name]
            yield table_name, columns, self._rows_by_id(model)
        yield "lesson", USER_DATA_LESSON_COLUMNS, self._lessons_beyond_their_series()
        yield "app_settings", USER_DATA_SETTINGS_COLUMNS, self._rows_by_id(AppSettings)

    def _rows_by_id(self, model: type[SQLModel]) -> Sequence[SQLModel]:
        id_column = SQLModel.metadata.tables[str(model.__tablename__)].c.id
        return self._session.exec(select(model).order_by(id_column)).all()

    def _lessons_beyond_their_series(self) -> list[Lesson]:
        series_by_id = {
            series.id: series
            for series in self._session.exec(select(LessonSeries)).all()
        }
        telling = [
            lesson
            for lesson in self._session.exec(select(Lesson)).all()
            if self._says_more_than_its_series(
                lesson, series_by_id.get(lesson.series_id)
            )
        ]
        return sorted(telling, key=lambda lesson: lesson.id or 0)

    @staticmethod
    def _says_more_than_its_series(lesson: Lesson, series: LessonSeries | None) -> bool:
        if series is None:
            return True
        return (
            lesson.status is not LessonStatus.PLANNED
            or bool(lesson.note)
            or lesson.invoice_id is not None
            or bool(lesson.column_values)
            or lesson.quantity != series.quantity
            or lesson.starts_at != series.starts_at
        )

    @staticmethod
    def _as_text(value: object) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(value, sort_keys=True)
        return str(value)
