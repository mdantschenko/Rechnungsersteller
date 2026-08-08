"""Serve the lessons as a calendar feed the phone can subscribe to.

The feed URL carries a secret token because calendar apps cannot sign in,
and the settings row remembers how long before a lesson the phone should
speak up.

Revision ID: 0007_calendar
Revises: 0006_student
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0007_calendar"
down_revision: str | None = "0006_student"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("calendar_token", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "reminder_minutes", sa.Integer(), nullable=False, server_default="60"
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "reminder_minutes")
    op.drop_column("app_settings", "calendar_token")
