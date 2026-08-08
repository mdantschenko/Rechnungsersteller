"""Changing the password now waits for a code from the mailbox.

The parked hash, the code and its expiry live beside the real hash; nothing
changes until the code from the e-mail confirms the swap.

Revision ID: 0016_password_confirmation
Revises: 0015_unit_math
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_password_confirmation"
down_revision: str | None = "0015_unit_math"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings", sa.Column("pending_password_hash", sa.String(), nullable=True)
    )
    op.add_column(
        "app_settings", sa.Column("pending_password_code", sa.String(), nullable=True)
    )
    op.add_column(
        "app_settings",
        sa.Column("pending_password_until", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    pass
