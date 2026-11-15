"""port faceplate label

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-15 19:35:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("switch_ports", sa.Column("faceplate_label", sa.String(length=32), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("switch_ports", "faceplate_label")
