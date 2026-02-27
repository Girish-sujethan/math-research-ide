"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-02-26
"""

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "papers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_type",
            sa.Enum("arxiv", "scholar", "wolfram", "mathworld", "dlmf", "other", name="source_type_enum"),
            nullable=False,
        ),
        sa.Column("arxiv_id", sa.String(64), unique=True, nullable=True),
        sa.Column("doi", sa.String(256), unique=True, nullable=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("authors", sa.JSON, nullable=False),
        sa.Column("abstract", sa.Text, nullable=True),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("msc_codes", sa.JSON, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "concepts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column(
            "concept_type",
            sa.Enum(
                "theorem", "definition", "lemma", "axiom",
                "conjecture", "corollary", "proposition",
                name="concept_type_enum",
            ),
            nullable=False,
        ),
        sa.Column("latex_statement", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("msc_codes", sa.JSON, nullable=False),
        sa.Column("source_paper_id", sa.String(36), sa.ForeignKey("papers.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "lean_verification_status",
            sa.Enum("unverified", "pending", "verified", "failed", name="lean_status_enum"),
            nullable=False,
        ),
        sa.Column("lean_output", sa.Text, nullable=True),
        sa.Column("chroma_embedding_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "concept_relationships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_concept_id", sa.String(36), sa.ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_concept_id", sa.String(36), sa.ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "relationship_type",
            sa.Enum(
                "proves", "depends_on", "generalizes", "is_special_case_of",
                "contradicts", "cited_by", "equivalent_to", "extends",
                name="relationship_type_enum",
            ),
            nullable=False,
        ),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("weight", sa.Float, nullable=False),
        sa.Column("source_paper_id", sa.String(36), sa.ForeignKey("papers.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("source_concept_id", "target_concept_id", "relationship_type", name="uq_concept_relationship"),
    )

    op.create_table(
        "discoveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("base_concept_id", sa.String(36), sa.ForeignKey("concepts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("modified_latex_statement", sa.Text, nullable=False),
        sa.Column("modification_description", sa.Text, nullable=False),
        sa.Column(
            "sympy_check_status",
            sa.Enum("unchecked", "passed", "failed", name="sympy_status_enum"),
            nullable=False,
        ),
        sa.Column("sympy_check_output", sa.Text, nullable=True),
        sa.Column(
            "lean_verification_status",
            sa.Enum("unverified", "pending", "verified", "failed", name="lean_discovery_status_enum"),
            nullable=False,
        ),
        sa.Column("lean_output", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "discovery_impacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("discovery_id", sa.String(36), sa.ForeignKey("discoveries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("affected_concept_id", sa.String(36), sa.ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "impact_type",
            sa.Enum("extends", "contradicts", "generalizes", "enables", "invalidates", name="impact_type_enum"),
            nullable=False,
        ),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("confidence_score", sa.Float, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("discovery_impacts")
    op.drop_table("discoveries")
    op.drop_table("concept_relationships")
    op.drop_table("concepts")
    op.drop_table("papers")
