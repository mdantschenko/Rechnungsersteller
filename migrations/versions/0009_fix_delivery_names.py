"""Repair delivery values written by 0005's lower-case default.

SQLAlchemy's Enum column persists member names (EMAIL), but revision 0005
filled existing rows with the value spelling (email), which crashed every
read of such a customer.

Revision ID: 0009_delivery_fix
Revises: 0008_holidays
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_delivery_fix"
down_revision: str | None = "0008_holidays"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE customer SET delivery = 'EMAIL' WHERE delivery = 'email'")
    op.execute("UPDATE customer SET delivery = 'WHATSAPP' WHERE delivery = 'whatsapp'")
    op.execute("UPDATE customer SET delivery = 'NONE' WHERE delivery = 'none'")


def downgrade() -> None:
    pass
