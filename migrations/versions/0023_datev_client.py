"""The Lexware client the DATEV booking batch belongs to.

Revision ID: 0023_datev_client
Revises: 0022_backup_digest
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_datev_client"
down_revision: str | None = "0022_backup_digest"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings", sa.Column("datev_advisor_number", sa.Integer(), nullable=True)
    )
    op.add_column(
        "app_settings", sa.Column("datev_client_number", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    pass
