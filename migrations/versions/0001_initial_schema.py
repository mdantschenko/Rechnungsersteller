"""Create the customer, issued invoice and numbering tables.

Revision ID: 0001_initial
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

from invoicing.storage.models import ExactDecimal

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customer",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("street", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("city", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "ARCHIVED", name="customerstatus"),
            nullable=False,
        ),
        sa.Column("email", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("phone", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("customer", schema=None) as batch:
        batch.create_index(batch.f("ix_customer_name"), ["name"], unique=True)
        batch.create_index(batch.f("ix_customer_status"), ["status"], unique=False)

    op.create_table(
        "number_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("last_assigned", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "issued_invoice",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("period_printed_from", sa.Date(), nullable=False),
        sa.Column("period_printed_to", sa.Date(), nullable=False),
        sa.Column("column_labels", sa.JSON(), nullable=True),
        sa.Column("printed_total", ExactDecimal(), nullable=False),
        sa.Column("computed_total", ExactDecimal(), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=True),
        sa.Column("source_file", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("issued_invoice", schema=None) as batch:
        batch.create_index(
            batch.f("ix_issued_invoice_customer_id"), ["customer_id"], unique=False
        )
        batch.create_index(batch.f("ix_issued_invoice_number"), ["number"], unique=True)

    op.create_table(
        "issued_invoice_line",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("taught_on", sa.Date(), nullable=False),
        sa.Column("quantity", ExactDecimal(), nullable=False),
        sa.Column("unit", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("unit_price", ExactDecimal(), nullable=False),
        sa.Column("extra_values", sa.JSON(), nullable=True),
        sa.Column("total", ExactDecimal(), nullable=False),
        sa.ForeignKeyConstraint(["invoice_id"], ["issued_invoice.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("issued_invoice_line", schema=None) as batch:
        batch.create_index(
            batch.f("ix_issued_invoice_line_invoice_id"), ["invoice_id"], unique=False
        )


def downgrade() -> None:
    op.drop_table("issued_invoice_line")
    op.drop_table("issued_invoice")
    op.drop_table("number_state")
    op.drop_table("customer")
    sa.Enum(name="customerstatus").drop(op.get_bind(), checkfirst=True)
