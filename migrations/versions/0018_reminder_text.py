"""A customer can carry their own payment reminder letter.

Revision ID: 0018_reminder_text
Revises: 0017_push_alarms
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_reminder_text"
down_revision: str | None = "0017_push_alarms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("customer", sa.Column("reminder_text", sa.String(), nullable=True))


def downgrade() -> None:
    pass
