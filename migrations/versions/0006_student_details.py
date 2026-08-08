"""Name the pupil behind a customer.

The invoice goes to a parent, but the lessons are for the child: name,
class and, when it differs from the billing address, where the lessons
happen.

Revision ID: 0006_student
Revises: 0005_delivery
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0006_student"
down_revision: str | None = "0005_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "customer",
        sa.Column("student_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.add_column(
        "customer",
        sa.Column("student_grade", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.add_column(
        "customer",
        sa.Column("lesson_address", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("customer", "lesson_address")
    op.drop_column("customer", "student_grade")
    op.drop_column("customer", "student_name")
