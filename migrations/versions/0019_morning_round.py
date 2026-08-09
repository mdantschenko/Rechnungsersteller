"""The server gets a morning round: auto-sent invoices and daily pushes.

Revision ID: 0019_morning_round
Revises: 0018_reminder_text
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_morning_round"
down_revision: str | None = "0018_reminder_text"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "auto_send_invoices",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "app_settings", sa.Column("last_daily_round", sa.Date(), nullable=True)
    )


def downgrade() -> None:
    pass
