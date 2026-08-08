"""Let the application send invoices by email.

The SMTP account lives in the settings row like everything else the
application is configured with, so it can be entered on the settings screen
and never reaches the repository.

Revision ID: 0004_smtp
Revises: 0003_settings
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0004_smtp"
down_revision: str | None = "0003_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("smtp_host", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.add_column(
        "app_settings",
        sa.Column("smtp_port", sa.Integer(), nullable=False, server_default="587"),
    )
    op.add_column(
        "app_settings",
        sa.Column("smtp_user", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.add_column(
        "app_settings",
        sa.Column("smtp_password", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.add_column(
        "app_settings",
        sa.Column("smtp_from", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "smtp_from")
    op.drop_column("app_settings", "smtp_password")
    op.drop_column("app_settings", "smtp_user")
    op.drop_column("app_settings", "smtp_port")
    op.drop_column("app_settings", "smtp_host")
