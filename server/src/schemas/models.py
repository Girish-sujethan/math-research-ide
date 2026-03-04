"""Pydantic schemas — used for API boundaries and inter-module data transfer."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

ConceptType = Literal[
    "theorem", "definition", "lemma", "axiom", "conjecture", "corollary", "proposition",
    "equation", "remark", "example", "formula",
]
SourceType = Literal["arxiv", "scholar", "wolfram", "mathworld", "dlmf", "other", "upload"]
LeanStatus = Literal["unverified", "pending", "verified", "failed"]
SympyStatus = Literal["unchecked", "passed", "failed"]
RelationshipType = Literal[
    "proves", "depends_on", "generalizes", "is_special_case_of",
    "contradicts", "cited_by", "equivalent_to", "extends"
]
ImpactType = Literal["extends", "contradicts", "generalizes", "enables", "invalidates"]


# ---------------------------------------------------------------------------
# Paper schemas
# ---------------------------------------------------------------------------

class PaperBase(BaseModel):
    source_type: SourceType
    title: str
    authors: list[str]
    abstract: Optional[str] = None
    url: str
    arxiv_id: Optional[str] = None
    doi: Optional[str] = None
    published_at: Optional[datetime] = None
    msc_codes: list[str] = Field(default_factory=list)


class PaperRead(PaperBase):
    id: str
    fetched_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Concept schemas
# ---------------------------------------------------------------------------

class ConceptCreate(BaseModel):
    name: str
    concept_type: ConceptType
    latex_statement: str
    description: Optional[str] = None
    msc_codes: list[str] = Field(default_factory=list)
    source_paper_id: Optional[str] = None


class ConceptRead(ConceptCreate):
    id: str
    lean_verification_status: LeanStatus
    lean_output: Optional[str] = None
    chroma_embedding_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Relationship schemas
# ---------------------------------------------------------------------------

class RelationshipCreate(BaseModel):
    source_concept_id: str
    target_concept_id: str
    relationship_type: RelationshipType
    description: Optional[str] = None
    weight: float = 1.0
    source_paper_id: Optional[str] = None


class RelationshipRead(RelationshipCreate):
    id: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Discovery schemas
# ---------------------------------------------------------------------------

class DiscoveryCreate(BaseModel):
    name: str
    base_concept_id: Optional[str] = None
    modified_latex_statement: str
    modification_description: str


class DiscoveryRead(DiscoveryCreate):
    id: str
    sympy_check_status: SympyStatus
    sympy_check_output: Optional[str] = None
    lean_verification_status: LeanStatus
    lean_output: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Impact schemas
# ---------------------------------------------------------------------------

class ImpactRead(BaseModel):
    id: str
    discovery_id: str
    affected_concept_id: str
    impact_type: ImpactType
    description: Optional[str] = None
    confidence_score: float

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Query / search schemas
# ---------------------------------------------------------------------------

class SemanticSearchQuery(BaseModel):
    query: str
    n_results: int = 10
    search_concepts: bool = True
    search_papers: bool = True


class ImpactAnalysisResult(BaseModel):
    concept_id: str
    affected_by_relationship: dict[str, list[str]]   # relationship_type → affected concept IDs
    potential_conflicts: list[str]
    dependencies: list[str]
