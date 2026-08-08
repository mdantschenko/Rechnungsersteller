"""A personal letter per customer, with placeholders.

Revision ID: 0010_mail_text
Revises: 0009_delivery_fix
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0010_mail_text"
down_revision: str | None = "0009_delivery_fix"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "customer",
        sa.Column("mail_text", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("customer", "mail_text")
