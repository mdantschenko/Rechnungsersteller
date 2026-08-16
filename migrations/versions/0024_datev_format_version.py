"""The booking batch format version the Lexware import dialog expects.

Revision ID: 0024_datev_format_version
Revises: 0023_datev_client
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_datev_format_version"
down_revision: str | None = "0023_datev_client"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "datev_format_version",
            sa.Integer(),
            nullable=False,
            server_default="12",
        ),
    )


def downgrade() -> None:
    pass
