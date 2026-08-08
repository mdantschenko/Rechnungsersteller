"""Add the single row the application is configured with.

Revision ID: 0003_settings
Revises: 0002_lessons
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0003_settings"
down_revision: str | None = "0002_lessons"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("password_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("session_secret", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("invoice_folder", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("lesson_horizon_days", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
