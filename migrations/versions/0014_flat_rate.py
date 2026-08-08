"""Let a customer's price be a flat rate per lesson.

40 € for the usual ninety minutes, regardless of the clock: the lesson
keeps its real length on the calendar, the invoice bills 1 x 40 €.

Revision ID: 0014_flat_rate
Revises: 0013_defaults
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_flat_rate"
down_revision: str | None = "0013_defaults"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "billing_template",
        sa.Column("flat_rate", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("billing_template", "flat_rate")
