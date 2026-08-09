"""The weekly database backup that leaves the server.

Revision ID: 0021_offsite_backup
Revises: 0020_exam_grades
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_offsite_backup"
down_revision: str | None = "0020_exam_grades"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings", sa.Column("backup_passphrase", sa.String(), nullable=True)
    )
    op.add_column(
        "app_settings", sa.Column("last_backup_mailed", sa.Date(), nullable=True)
    )


def downgrade() -> None:
    pass
