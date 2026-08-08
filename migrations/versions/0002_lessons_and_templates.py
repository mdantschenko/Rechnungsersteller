"""Add billing templates, recurring series and individual lessons.

Revision ID: 0002_lessons
Revises: 0001_initial
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

from invoicing.storage.models import ExactDecimal

revision: str = "0002_lessons"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "issuer",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("street", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("city", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("country", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("bank", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("iban", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("bic", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("tax_number", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("email", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("paypal", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "billing_template",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("unit_price", ExactDecimal(), nullable=False),
        sa.Column("unit", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "cycle",
            sa.Enum("MONTH_START", "MONTH_MIDPOINT", name="billingcycle"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("billing_template", schema=None) as batch:
        batch.create_index(
            batch.f("ix_billing_template_customer_id"), ["customer_id"], unique=True
        )

    op.create_table(
        "template_column",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("label", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "source", sa.Enum("FIXED", "PER_LESSON", name="valuesource"), nullable=False
        ),
        sa.Column(
            "kind",
            sa.Enum("MONEY", "QUANTITY", "TEXT", name="valuekind"),
            nullable=False,
        ),
        sa.Column(
            "total_rule",
            sa.Enum(
                "EXCLUDED", "ADD_PER_ROW", "MULTIPLY_BY_QUANTITY", name="totalrule"
            ),
            nullable=False,
        ),
        sa.Column("default_value", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("placeholder", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["billing_template.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("template_column", schema=None) as batch:
        batch.create_index(
            batch.f("ix_template_column_template_id"), ["template_id"], unique=False
        )

    op.create_table(
        "lesson_series",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("recurrence", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("quantity", ExactDecimal(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("starts_at", sa.Time(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("lesson_series", schema=None) as batch:
        batch.create_index(batch.f("ix_lesson_series_active"), ["active"], unique=False)
        batch.create_index(
            batch.f("ix_lesson_series_customer_id"), ["customer_id"], unique=False
        )

    op.create_table(
        "lesson",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("series_id", sa.Integer(), nullable=True),
        sa.Column("taught_on", sa.Date(), nullable=False),
        sa.Column("starts_at", sa.Time(), nullable=True),
        sa.Column("quantity", ExactDecimal(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PLANNED", "DONE", "CANCELLED", name="lessonstatus"),
            nullable=False,
        ),
        sa.Column("note", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("column_values", sa.JSON(), nullable=True),
        sa.Column("invoice_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["issued_invoice.id"]),
        sa.ForeignKeyConstraint(["series_id"], ["lesson_series.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("lesson", schema=None) as batch:
        batch.create_index(
            batch.f("ix_lesson_customer_id"), ["customer_id"], unique=False
        )
        batch.create_index(
            batch.f("ix_lesson_invoice_id"), ["invoice_id"], unique=False
        )
        batch.create_index(batch.f("ix_lesson_series_id"), ["series_id"], unique=False)
        batch.create_index(batch.f("ix_lesson_status"), ["status"], unique=False)
        batch.create_index(batch.f("ix_lesson_taught_on"), ["taught_on"], unique=False)


def downgrade() -> None:
    op.drop_table("lesson")
    op.drop_table("lesson_series")
    op.drop_table("template_column")
    op.drop_table("billing_template")
    op.drop_table("issuer")
    for enum in (
        "lessonstatus",
        "totalrule",
        "valuekind",
        "valuesource",
        "billingcycle",
    ):
        sa.Enum(name=enum).drop(op.get_bind(), checkfirst=True)
