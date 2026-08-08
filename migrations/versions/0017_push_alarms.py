"""The app rings on its own: push subscriptions and per-lesson alarm state.

The calendar feed's token goes with it — the phone no longer needs a
calendar subscription to be woken.

Revision ID: 0017_push_alarms
Revises: 0016_password_confirmation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_push_alarms"
down_revision: str | None = "0016_password_confirmation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "push_subscription",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("endpoint", sa.String(), nullable=False, unique=True),
        sa.Column("p256dh", sa.String(), nullable=False),
        sa.Column("auth", sa.String(), nullable=False),
    )
    op.create_table(
        "lesson_alarm",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "lesson_id",
            sa.Integer(),
            sa.ForeignKey("lesson.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("rings", sa.Integer(), nullable=False),
        sa.Column("last_rung_at", sa.DateTime(), nullable=True),
        sa.Column("acknowledged", sa.Boolean(), nullable=False),
    )
    op.add_column(
        "app_settings", sa.Column("vapid_private_key", sa.String(), nullable=True)
    )
    op.add_column(
        "app_settings", sa.Column("vapid_public_key", sa.String(), nullable=True)
    )
    op.drop_column("app_settings", "calendar_token")


def downgrade() -> None:
    pass
