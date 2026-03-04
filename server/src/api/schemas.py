"""API-layer Pydantic schemas — request/response models for all HTTP routers."""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.schemas.models import PaperRead


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Papers
# ---------------------------------------------------------------------------

class PaperSearchRequest(BaseModel):
    query: str
    source: str = "arxiv"          # "arxiv" | "exa"
    limit: int = Field(10, ge=1, le=50)


class PaperSearchResult(BaseModel):
    arxiv_id: Optional[str] = None
    title: str
    authors: list[str]
    abstract: Optional[str] = None
    url: str
    source: str


class IngestRequest(BaseModel):
    arxiv_id: Optional[str] = None
    doi: Optional[str] = None


class IngestJobResponse(BaseModel):
    job_id: str
    paper_id: str
    status: JobStatus


class IngestJobResult(BaseModel):
    job_id: str
    paper_id: str
    status: JobStatus
    concepts_created: Optional[int] = None
    concept_ids: Optional[list[str]] = None
    relationships_created: Optional[int] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Discoveries
# ---------------------------------------------------------------------------

class DiscoveryJobResponse(BaseModel):
    job_id: str
    status: JobStatus


class DiscoveryJobResult(BaseModel):
    job_id: str
    status: JobStatus
    discovery_id: Optional[str] = None
    sympy_status: Optional[str] = None
    lean_status: Optional[str] = None
    impacts_count: Optional[int] = None
    conflict_count: Optional[int] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Concepts
# ---------------------------------------------------------------------------

class ConceptSearchRequest(BaseModel):
    query: str
    n_results: int = Field(10, ge=1, le=50)


class ConceptSearchResult(BaseModel):
    concept_id: str
    name: str
    concept_type: str
    distance: float


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class SearchResponse(BaseModel):
    concepts: list[ConceptSearchResult]
    papers: list[PaperRead]


# ---------------------------------------------------------------------------
# Research
# ---------------------------------------------------------------------------

class ResearchStartRequest(BaseModel):
    query: str


class ResearchJobResponse(BaseModel):
    job_id: str
    status: JobStatus


class ResearchJobResult(BaseModel):
    job_id: str
    status: JobStatus
    report: Optional[str] = None       # Content for document insertion
    heaven_note: Optional[str] = None # Short HEAVEN-relevant message for chat pane
    concept_ids: Optional[list[str]] = None
    concept_names: Optional[list[str]] = None
    paper_ids: Optional[list[str]] = None
    paper_names: Optional[list[str]] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class CanvasItem(BaseModel):
    type: str   # "concept" | "paper"
    id: str
    name: str


class SuggestedAction(BaseModel):
    type: str
    payload: dict[str, Any]


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    context: Optional[dict[str, Any]] = None    # e.g. {"current_concept_id": "..."}


class ChatMessage(BaseModel):
    role: str   # "user" | "assistant" | "system"
    content: str


class ChatStreamRequest(BaseModel):
    """Accepted by POST /chat/stream. Either messages (useChat) or message (legacy)."""
    messages: Optional[list[ChatMessage]] = None  # full history; last must be user
    message: Optional[str] = None
    session_id: Optional[str] = None
    context: Optional[dict[str, Any]] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    canvas_items: list[CanvasItem] = []
    thinking: Optional[str] = None
    sources: list[str] = []


# ---------------------------------------------------------------------------
# Concept graph
# ---------------------------------------------------------------------------

class ConceptNode(BaseModel):
    id: str
    name: str
    concept_type: str
    paper_id: Optional[str] = None


class ConceptEdge(BaseModel):
    source: str
    target: str
    relationship_type: str


class ConceptGraphResponse(BaseModel):
    nodes: list[ConceptNode]
    edges: list[ConceptEdge]


# ---------------------------------------------------------------------------
# Paper Discovery
# ---------------------------------------------------------------------------

class DiscoveredPaper(BaseModel):
    arxiv_id: Optional[str] = None
    title: str
    authors: list[str]
    abstract: Optional[str] = None
    url: str
    source: str
    relevance_score: float
    relevance_explanation: str


class PaperDiscoveryRequest(BaseModel):
    query: str


class PaperDiscoveryJobResponse(BaseModel):
    job_id: str
    status: JobStatus


class PaperDiscoveryJobResult(BaseModel):
    job_id: str
    status: JobStatus
    stage: Optional[str] = None   # mirrors PaperDiscoveryState.status mid-run
    papers: list[DiscoveredPaper] = []
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Nudges (verify/nudge endpoint)
# ---------------------------------------------------------------------------

class NudgeItem(BaseModel):
    type: str          # "connection" | "warning" | "expansion"
    message: str
    source_paper_id: Optional[str] = None
    source_paper_title: Optional[str] = None
    block_index: Optional[int] = None
    distance: Optional[float] = None


class NudgeRequest(BaseModel):
    blocks: list[dict]            # [{type, content}]
    staged_paper_ids: list[str]


class NudgeResult(BaseModel):
    nudges: list[NudgeItem]


# ---------------------------------------------------------------------------
# Editor intelligence
# ---------------------------------------------------------------------------

# Parity check
class ParityRequest(BaseModel):
    source: str


class ParityCheckItem(BaseModel):
    start_char: int
    end_char: int
    expression: str
    lhs: Optional[str] = None
    rhs: Optional[str] = None
    status: str          # "verified" | "failed" | "invalid" | "skip"
    output: str
    simplified_form: Optional[str] = None


class ParityResult(BaseModel):
    results: list[ParityCheckItem]


# Formalization
class FormalizeRequest(BaseModel):
    statement: str
    concept_name: str


class FormalizeResult(BaseModel):
    success: bool
    lean_source: Optional[str] = None
    attempts: int
    error: Optional[str] = None


# Correlation alerts
class ParagraphInput(BaseModel):
    text: str
    start_char: int
    end_char: int


class CorrelateRequest(BaseModel):
    paragraphs: list[ParagraphInput]
    staged_paper_ids: list[str]


class CorrelationItem(BaseModel):
    para_index: int
    start_char: int
    end_char: int
    concept_id: str
    concept_name: str
    concept_type: str
    distance: float
    paper_id: str = ""
    paper_title: str = ""


class CorrelateResult(BaseModel):
    correlations: list[CorrelationItem]


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

class PythonVisualRequest(BaseModel):
    code: str
    title: Optional[str] = None


class PythonVisualResponse(BaseModel):
    output: str = ""
    image_base64: Optional[str] = None
    error: Optional[str] = None


class FactCheckRequest(BaseModel):
    statement: str
    staged_paper_ids: list[str] = []


class FactCheckResponse(BaseModel):
    verdict: str                  # "supported" | "contradicted" | "uncertain"
    confidence: float             # 0.0 – 1.0
    explanation: str
    supporting_evidence: list[str] = []
    issues: list[str] = []
    suggestion: Optional[str] = None


# ---------------------------------------------------------------------------
# Live verification (multi-tier: SymPy -> Wolfram -> LLM -> CrossRef)
# ---------------------------------------------------------------------------

class LiveCheckRequest(BaseModel):
    source: str
    staged_paper_ids: list[str] = []


class LiveCheckItem(BaseModel):
    start_char: int
    end_char: int
    expression: str
    status: str                    # "verified" | "failed" | "skipped" | "error"
    tier: str                      # "sympy" | "wolfram" | "llm" | "crossref"
    output: str
    simplified_form: Optional[str] = None
    paper_title: Optional[str] = None


class LiveCheckResult(BaseModel):
    results: list[LiveCheckItem]
    check_id: Optional[str] = None
