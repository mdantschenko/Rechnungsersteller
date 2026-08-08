"""The unit does the arithmetic now; the flat-rate switch goes again.

"1,5h" as the unit prices per ninety minutes, which covers what the
short-lived flat_rate column was for.

Revision ID: 0015_unit_math
Revises: 0014_flat_rate
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015_unit_math"
down_revision: str | None = "0014_flat_rate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("billing_template", "flat_rate")


def downgrade() -> None:
    pass
