"""When a paid invoice was taken off the list.

Revision ID: 0026_paid_invoice_hidden
Revises: 0025_series_occurrence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_paid_invoice_hidden"
down_revision: str | None = "0025_series_occurrence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "issued_invoice", sa.Column("taken_off_the_list_on", sa.Date(), nullable=True)
    )


def downgrade() -> None:
    pass
