"""The fingerprint that tells whether a backup is worth mailing.

Revision ID: 0022_backup_digest
Revises: 0021_offsite_backup
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_backup_digest"
down_revision: str | None = "0021_offsite_backup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings", sa.Column("backup_digest", sa.String(), nullable=True)
    )


def downgrade() -> None:
    pass
