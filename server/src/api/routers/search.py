"""Cross-entity search router — semantic search over concepts and papers."""

from fastapi import APIRouter

from src.api.schemas import ConceptSearchResult, SearchResponse
from src.db.chroma import collections
from src.db.sqlite.models import Paper
from src.db.sqlite.session import get_session
from src.schemas.models import PaperRead, SemanticSearchQuery

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
def search(req: SemanticSearchQuery) -> SearchResponse:
    """Semantic search across concept embeddings and paper abstracts in ChromaDB."""
    concepts: list[ConceptSearchResult] = []
    papers: list[PaperRead] = []

    if req.search_concepts:
        chroma = collections.query_concepts(req.query, n_results=req.n_results)
        ids = chroma.get("ids", [[]])[0]
        distances = chroma.get("distances", [[]])[0]
        metadatas = chroma.get("metadatas", [[]])[0]
        concepts = [
            ConceptSearchResult(
                concept_id=cid,
                name=meta.get("name", ""),
                concept_type=meta.get("concept_type", ""),
                distance=dist,
            )
            for cid, dist, meta in zip(ids, distances, metadatas)
        ]

    if req.search_papers:
        chroma = collections.query_papers(req.query, n_results=req.n_results)
        ids = chroma.get("ids", [[]])[0]
        with get_session() as session:
            for pid in ids:
                paper = session.get(Paper, pid)
                if paper is not None:
                    papers.append(PaperRead.model_validate(paper))

    return SearchResponse(concepts=concepts, papers=papers)
