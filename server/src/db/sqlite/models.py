"""SQLAlchemy models — stores metadata and extracted knowledge only.
Full paper content is never persisted; it is fetched on demand.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Papers — metadata only, no content stored
# ---------------------------------------------------------------------------

class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_type: Mapped[str] = mapped_column(
        Enum("arxiv", "scholar", "wolfram", "mathworld", "dlmf", "other", "upload", name="source_type_enum"),
        nullable=False,
    )
    arxiv_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    doi: Mapped[Optional[str]] = mapped_column(String(256), unique=True, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    abstract: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    msc_codes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    concepts: Mapped[list["Concept"]] = relationship("Concept", back_populates="source_paper")


# ---------------------------------------------------------------------------
# Concepts — extracted mathematical knowledge (theorems, definitions, etc.)
# ---------------------------------------------------------------------------

class Concept(Base):
    __tablename__ = "concepts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    concept_type: Mapped[str] = mapped_column(
        Enum(
            "theorem", "definition", "lemma", "axiom",
            "conjecture", "corollary", "proposition",
            "equation", "remark", "example", "formula",
            name="concept_type_enum",
        ),
        nullable=False,
    )
    latex_statement: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    msc_codes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # Source paper — nullable because concepts can be user-created
    source_paper_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("papers.id", ondelete="SET NULL"), nullable=True
    )
    source_paper: Mapped[Optional[Paper]] = relationship("Paper", back_populates="concepts")

    # Lean 4 formal verification
    lean_verification_status: Mapped[str] = mapped_column(
        Enum("unverified", "pending", "verified", "failed", name="lean_status_enum"),
        nullable=False,
        default="unverified",
    )
    lean_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ChromaDB embedding reference
    chroma_embedding_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    # Graph relationships originating from this concept
    outgoing_relationships: Mapped[list["ConceptRelationship"]] = relationship(
        "ConceptRelationship",
        foreign_keys="ConceptRelationship.source_concept_id",
        back_populates="source_concept",
        cascade="all, delete-orphan",
    )
    incoming_relationships: Mapped[list["ConceptRelationship"]] = relationship(
        "ConceptRelationship",
        foreign_keys="ConceptRelationship.target_concept_id",
        back_populates="target_concept",
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# ConceptRelationship — persisted edges for the NetworkX knowledge graph
# ---------------------------------------------------------------------------

RELATIONSHIP_TYPES = (
    "proves",
    "depends_on",
    "generalizes",
    "is_special_case_of",
    "contradicts",
    "cited_by",
    "equivalent_to",
    "extends",
    "related_to",
)


class ConceptRelationship(Base):
    __tablename__ = "concept_relationships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_concept_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False
    )
    target_concept_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(
        Enum(*RELATIONSHIP_TYPES, name="relationship_type_enum"), nullable=False
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    source_paper_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("papers.id", ondelete="SET NULL"), nullable=True
    )

    source_concept: Mapped[Concept] = relationship(
        "Concept", foreign_keys=[source_concept_id], back_populates="outgoing_relationships"
    )
    target_concept: Mapped[Concept] = relationship(
        "Concept", foreign_keys=[target_concept_id], back_populates="incoming_relationships"
    )

    __table_args__ = (
        UniqueConstraint(
            "source_concept_id", "target_concept_id", "relationship_type",
            name="uq_concept_relationship",
        ),
    )


# ---------------------------------------------------------------------------
# Discoveries — user-created modifications to existing concepts
# ---------------------------------------------------------------------------

class Discovery(Base):
    __tablename__ = "discoveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)

    # The concept being modified — nullable if the discovery introduces a new concept
    base_concept_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("concepts.id", ondelete="SET NULL"), nullable=True
    )

    # The modified or new mathematical statement
    modified_latex_statement: Mapped[str] = mapped_column(Text, nullable=False)
    modification_description: Mapped[str] = mapped_column(Text, nullable=False)

    # SymPy pre-verification (fast, cheap)
    sympy_check_status: Mapped[str] = mapped_column(
        Enum("unchecked", "passed", "failed", name="sympy_status_enum"),
        nullable=False,
        default="unchecked",
    )
    sympy_check_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Lean 4 formal verification (authoritative)
    lean_verification_status: Mapped[str] = mapped_column(
        Enum("unverified", "pending", "verified", "failed", name="lean_discovery_status_enum"),
        nullable=False,
        default="unverified",
    )
    lean_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    base_concept: Mapped[Optional[Concept]] = relationship("Concept")
    impacts: Mapped[list["DiscoveryImpact"]] = relationship(
        "DiscoveryImpact", back_populates="discovery", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# DiscoveryImpact — propagation results: what a discovery affects
# ---------------------------------------------------------------------------

class DiscoveryImpact(Base):
    __tablename__ = "discovery_impacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    discovery_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("discoveries.id", ondelete="CASCADE"), nullable=False
    )
    affected_concept_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False
    )
    impact_type: Mapped[str] = mapped_column(
        Enum(
            "extends", "contradicts", "generalizes", "enables", "invalidates",
            name="impact_type_enum",
        ),
        nullable=False,
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    discovery: Mapped[Discovery] = relationship("Discovery", back_populates="impacts")
    affected_concept: Mapped[Concept] = relationship("Concept")
