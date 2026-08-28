"""What a series lesson was written out for, and which dates were dropped.

Revision ID: 0025_series_occurrence
Revises: 0024_datev_format_version
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_series_occurrence"
down_revision: str | None = "0024_datev_format_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("lesson", sa.Column("series_occurrence_on", sa.Date(), nullable=True))
    op.add_column(
        "lesson_series", sa.Column("skipped_occurrences", sa.JSON(), nullable=True)
    )
    op.execute(
        "UPDATE lesson SET series_occurrence_on = taught_on WHERE series_id IS NOT NULL"
    )
    op.execute("UPDATE lesson_series SET skipped_occurrences = '[]'")


def downgrade() -> None:
    pass
