"""Remember when an invoice went out, and when money is due.

Revision ID: 0012_sent_due
Revises: 0011_reminders
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_sent_due"
down_revision: str | None = "0011_reminders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("issued_invoice", sa.Column("sent_on", sa.Date(), nullable=True))
    op.add_column(
        "app_settings",
        sa.Column("payment_days", sa.Integer(), nullable=False, server_default="14"),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "payment_days")
    op.drop_column("issued_invoice", "sent_on")
