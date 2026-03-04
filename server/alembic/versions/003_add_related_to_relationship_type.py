"""add related_to to relationship_type_enum

Revision ID: 003
Revises: 002
Create Date: 2026-02-27

Adds 'related_to' for semantic/keyword-suggested concept relationships.
"""

from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None

OLD_ENUM = sa.Enum(
    "proves", "depends_on", "generalizes", "is_special_case_of",
    "contradicts", "cited_by", "equivalent_to", "extends",
    name="relationship_type_enum",
)
NEW_ENUM = sa.Enum(
    "proves", "depends_on", "generalizes", "is_special_case_of",
    "contradicts", "cited_by", "equivalent_to", "extends", "related_to",
    name="relationship_type_enum",
)


def upgrade() -> None:
    with op.batch_alter_table("concept_relationships", schema=None) as batch_op:
        batch_op.alter_column(
            "relationship_type",
            existing_type=OLD_ENUM,
            type_=NEW_ENUM,
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("concept_relationships", schema=None) as batch_op:
        batch_op.alter_column(
            "relationship_type",
            existing_type=NEW_ENUM,
            type_=OLD_ENUM,
            existing_nullable=False,
        )
