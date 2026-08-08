"""Let each customer say how their invoices leave the house.

Email, WhatsApp via the share sheet, or no invoice at all — for the customer
whose lessons are tracked only as a reminder.

Revision ID: 0005_delivery
Revises: 0004_smtp
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0005_delivery"
down_revision: str | None = "0004_smtp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLAlchemy's Enum column persists member NAMES, so the default must be
    # the upper-case name, not the value.
    op.add_column(
        "customer",
        sa.Column(
            "delivery",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default="EMAIL",
        ),
    )


def downgrade() -> None:
    op.drop_column("customer", "delivery")
