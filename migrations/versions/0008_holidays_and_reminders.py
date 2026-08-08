"""Holidays on the calendar, and a reminder clock time per customer.

Revision ID: 0008_holidays
Revises: 0007_calendar
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0008_holidays"
down_revision: str | None = "0007_calendar"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "show_public_holidays", sa.Boolean(), nullable=False, server_default="1"
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "show_school_holidays", sa.Boolean(), nullable=False, server_default="1"
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "holiday_states",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column("customer", sa.Column("reminder_at", sa.Time(), nullable=True))
    op.add_column(
        "customer",
        sa.Column("online", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.create_table(
        "school_holiday",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("state", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("first_day", sa.Date(), nullable=False),
        sa.Column("last_day", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_school_holiday_state", "school_holiday", ["state"])


def downgrade() -> None:
    op.drop_index("ix_school_holiday_state", "school_holiday")
    op.drop_table("school_holiday")
    op.drop_column("customer", "online")
    op.drop_column("customer", "reminder_at")
    op.drop_column("app_settings", "holiday_states")
    op.drop_column("app_settings", "show_school_holidays")
    op.drop_column("app_settings", "show_public_holidays")
