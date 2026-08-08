"""Normalise column defaults that were typed the German way.

"20,00 €" in a money column crashed the billing page; stored values lose
their currency sign and thousands dots and swap the comma for a point.

Revision ID: 0013_defaults
Revises: 0012_sent_due
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013_defaults"
down_revision: str | None = "0012_sent_due"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE template_column
        SET default_value = REPLACE(REPLACE(REPLACE(REPLACE(
                default_value, '€', ''), ' ', ''), '.', ''), ',', '.')
        WHERE default_value IS NOT NULL
          AND kind IN ('MONEY', 'QUANTITY')
          AND default_value LIKE '%,%'
        """
    )
    op.execute(
        """
        UPDATE template_column
        SET default_value = TRIM(REPLACE(default_value, '€', ''))
        WHERE default_value IS NOT NULL
          AND kind IN ('MONEY', 'QUANTITY')
        """
    )


def downgrade() -> None:
    pass
