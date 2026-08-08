"""Remember every payment reminder that went out.

Revision ID: 0011_reminders
Revises: 0010_mail_text
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_reminders"
down_revision: str | None = "0010_mail_text"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_reminder",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("sent_on", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["invoice_id"], ["issued_invoice.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_payment_reminder_invoice_id", "payment_reminder", ["invoice_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_payment_reminder_invoice_id", "payment_reminder")
    op.drop_table("payment_reminder")
