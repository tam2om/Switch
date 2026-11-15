"""hardware validation evidence

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-15 20:00:00
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("switch_models", sa.Column("hardware_evidence", postgresql.JSONB(astext_type=sa.Text()),
                                             nullable=False, server_default="{}"))
    op.create_table(
        "hardware_validations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("switch_id", sa.Integer(), nullable=True),
        sa.Column("hostname", sa.String(length=128), nullable=False),
        sa.Column("product_number", sa.String(length=32), nullable=False),
        sa.Column("firmware", sa.String(length=32), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["switch_id"], ["switches.id"], name=op.f("fk_hardware_validations_switch_id_switches"),
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hardware_validations")),
    )
    op.create_index(op.f("ix_hardware_validations_switch_id"), "hardware_validations", ["switch_id"])
    op.create_index(op.f("ix_hardware_validations_product_number"), "hardware_validations", ["product_number"])


def downgrade() -> None:
    op.drop_table("hardware_validations")
    op.drop_column("switch_models", "hardware_evidence")
