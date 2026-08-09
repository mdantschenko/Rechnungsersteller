"""A pupil's exams and grades, kept beside their lessons.

Revision ID: 0020_exam_grades
Revises: 0019_morning_round
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_exam_grades"
down_revision: str | None = "0019_morning_round"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "exam_grade",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customer.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("written_on", sa.Date(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("grade", sa.String(), nullable=False),
    )


def downgrade() -> None:
    pass
