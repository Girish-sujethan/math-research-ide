"""add upload to source_type_enum

Revision ID: 002
Revises: 001
Create Date: 2026-02-27

Adds 'upload' to papers.source_type enum so PDF-uploaded papers load without LookupError.
"""

from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

OLD_ENUM = sa.Enum("arxiv", "scholar", "wolfram", "mathworld", "dlmf", "other", name="source_type_enum")
NEW_ENUM = sa.Enum("arxiv", "scholar", "wolfram", "mathworld", "dlmf", "other", "upload", name="source_type_enum")


def upgrade() -> None:
    with op.batch_alter_table("papers", schema=None) as batch_op:
        batch_op.alter_column(
            "source_type",
            existing_type=OLD_ENUM,
            type_=NEW_ENUM,
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("papers", schema=None) as batch_op:
        batch_op.alter_column(
            "source_type",
            existing_type=NEW_ENUM,
            type_=OLD_ENUM,
            existing_nullable=False,
        )
