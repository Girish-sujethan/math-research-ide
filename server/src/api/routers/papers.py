"""Papers router — search, ingest (background), list, retrieve, resume."""

import asyncio
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import (
    get_ingestion_graph,
    get_running_threads,
    get_sessions,
    get_thread_metadata,
)
from src.api.schemas import (
    IngestJobResponse,
    IngestJobResult,
    IngestRequest,
    JobStatus,
    PaperSearchRequest,
    PaperSearchResult,
)
from src.db.chroma import collections
from src.db.sqlite.models import Paper
from src.db.sqlite.session import get_session
from src.ingestion import arxiv_client
from src.model.graphs.ingestion_graph import IngestionState
from src.schemas.models import PaperRead

router = APIRouter(prefix="/papers", tags=["papers"])
logger = logging.getLogger(__name__)


@router.post("/search", response_model=list[PaperSearchResult])
async def search_papers(req: PaperSearchRequest) -> list[PaperSearchResult]:
    """Search arXiv or Exa. Results are not persisted."""
    if req.source == "arxiv":
        results = await asyncio.to_thread(arxiv_client.search, req.query, req.limit)
        return [
            PaperSearchResult(
                arxiv_id=r.arxiv_id,
                title=r.title,
                authors=r.authors,
                abstract=r.abstract,
                url=r.url,
                source="arxiv",
            )
            for r in results
        ]
    if req.source == "exa":
        from src.ingestion import exa_client
        results = await asyncio.to_thread(exa_client.search, req.query, req.limit)
        return results
    raise HTTPException(
        status_code=400,
        detail=f"Unknown source {req.source!r}. Use 'arxiv' or 'exa'.",
    )


@router.post("/ingest", response_model=IngestJobResponse, status_code=202)
async def ingest_paper_endpoint(
    req: IngestRequest,
    ingestion_graph: Annotated[object, Depends(get_ingestion_graph)],
    running_threads: Annotated[set, Depends(get_running_threads)],
    thread_metadata: Annotated[dict, Depends(get_thread_metadata)],
) -> IngestJobResponse:
    """Persist paper metadata, then extract concepts in a background job.

    Accepts either arxiv_id or doi. Returns immediately with a job_id.
    Poll GET /papers/ingest/{job_id} for status.
    """
    if not req.arxiv_id and not req.doi:
        raise HTTPException(status_code=400, detail="Provide arxiv_id or doi")

    # --- DOI path: resolve via CrossRef (no API key required) ------------------
    if req.doi and not req.arxiv_id:
        import httpx
        doi_encoded = req.doi.strip()
        crossref_url = f"https://api.crossref.org/works/{doi_encoded}"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    crossref_url,
                    headers={"Accept": "application/json", "User-Agent": "HEAVEN/1.0 (mailto:dev@example.org)"},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"Could not resolve DOI {req.doi!r}: {exc}")

        message = data.get("message") or {}
        title = (message.get("title") or [req.doi])[0]
        authors_raw = message.get("author") or []
        authors = []
        for a in authors_raw:
            given = a.get("given", "")
            family = a.get("family", "")
            authors.append(f"{given} {family}".strip() or "Unknown")
        abstract = None
        if message.get("abstract"):
            raw = message["abstract"]
            if isinstance(raw, str):
                abstract = raw.replace("<jats:p>", "").replace("</jats:p>", "").strip()
            else:
                abstract = str(raw)

        with get_session() as session:
            existing = session.query(Paper).filter(Paper.doi == req.doi).first()
            if existing is not None:
                return IngestJobResponse(
                    job_id=existing.id,
                    paper_id=existing.id,
                    status=JobStatus.DONE,
                )

        paper_id = str(uuid.uuid4())
        with get_session() as session:
            db_paper = Paper(
                id=paper_id,
                source_type="other",
                doi=req.doi,
                title=title,
                authors=authors,
                abstract=abstract,
                url=f"https://doi.org/{req.doi}",
            )
            session.add(db_paper)

        if abstract:
            try:
                collections.upsert_paper(
                    paper_id=paper_id,
                    abstract=abstract,
                    metadata={"title": title, "arxiv_id": ""},
                )
            except Exception as exc:
                logger.warning("ChromaDB upsert failed for DOI paper %s: %s", paper_id, exc)

        thread_id = str(uuid.uuid4())
        thread_metadata[thread_id] = {"paper_id": paper_id}
        initial_state: IngestionState = {
            "paper_id": paper_id,
            "arxiv_id": "",
            "content": abstract or title,
            "extracted_concepts": [],
            "name_to_id": {},
            "new_concept_ids": [],
            "concepts_created": 0,
            "concepts_deduplicated": 0,
            "relationships_created": 0,
            "status": "running",
        }
        config = {"configurable": {"thread_id": thread_id}}

        async def _run_doi() -> None:
            running_threads.add(thread_id)
            try:
                await asyncio.to_thread(ingestion_graph.invoke, initial_state, config)
            except Exception as exc:
                logger.exception("DOI ingestion thread %s failed: %s", thread_id, exc)
                thread_metadata[thread_id]["error"] = str(exc)
            finally:
                running_threads.discard(thread_id)

        asyncio.create_task(_run_doi())
        return IngestJobResponse(job_id=thread_id, paper_id=paper_id, status=JobStatus.PENDING)

    # --- arXiv path ------------------------------------------------------------
    arxiv_id = req.arxiv_id

    # Duplicate guard — return existing paper instead of 409
    with get_session() as session:
        existing = session.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
        if existing is not None:
            # Paper already ingested — return it directly so the caller can stage it
            return IngestJobResponse(
                job_id=existing.id,
                paper_id=existing.id,
                status=JobStatus.DONE,
            )

    # Fetch metadata synchronously — fast, just an API call
    meta = await asyncio.to_thread(arxiv_client.fetch_by_id, arxiv_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"arXiv paper {arxiv_id!r} not found")

    # Persist Paper ORM row
    paper_id = str(uuid.uuid4())
    with get_session() as session:
        db_paper = Paper(
            id=paper_id,
            source_type="arxiv",
            arxiv_id=meta.arxiv_id,
            title=meta.title,
            authors=meta.authors,
            abstract=meta.abstract,
            url=meta.url,
            published_at=meta.published_at,
            msc_codes=meta.msc_codes,
        )
        session.add(db_paper)

    # Upsert abstract into ChromaDB papers collection
    if meta.abstract:
        try:
            collections.upsert_paper(
                paper_id=paper_id,
                abstract=meta.abstract,
                metadata={"title": meta.title, "arxiv_id": meta.arxiv_id or ""},
            )
        except Exception as exc:
            logger.warning("ChromaDB upsert failed for paper %s: %s", paper_id, exc)

    # Register thread and spawn background task
    thread_id = str(uuid.uuid4())
    thread_metadata[thread_id] = {"paper_id": paper_id}

    initial_state: IngestionState = {
        "paper_id": paper_id,
        "arxiv_id": arxiv_id,
        "content": None,
        "extracted_concepts": [],
        "name_to_id": {},
        "new_concept_ids": [],
        "concepts_created": 0,
        "concepts_deduplicated": 0,
        "relationships_created": 0,
        "status": "running",
    }
    config = {"configurable": {"thread_id": thread_id}}

    async def _run() -> None:
        running_threads.add(thread_id)
        try:
            await asyncio.to_thread(ingestion_graph.invoke, initial_state, config)
        except Exception as exc:
            logger.exception("Ingestion thread %s failed: %s", thread_id, exc)
            thread_metadata[thread_id]["error"] = str(exc)
        finally:
            running_threads.discard(thread_id)

    asyncio.create_task(_run())
    return IngestJobResponse(job_id=thread_id, paper_id=paper_id, status=JobStatus.PENDING)


@router.get("/ingest/{job_id}", response_model=IngestJobResult)
def get_ingest_status(
    job_id: str,
    ingestion_graph: Annotated[object, Depends(get_ingestion_graph)],
    running_threads: Annotated[set, Depends(get_running_threads)],
    thread_metadata: Annotated[dict, Depends(get_thread_metadata)],
) -> IngestJobResult:
    """Poll the status of a paper ingestion background job."""
    meta = thread_metadata.get(job_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")

    paper_id = meta.get("paper_id", "")

    if job_id in running_threads:
        return IngestJobResult(job_id=job_id, paper_id=paper_id, status=JobStatus.RUNNING)

    config = {"configurable": {"thread_id": job_id}}
    snapshot = ingestion_graph.get_state(config)

    if snapshot is None or not snapshot.values:
        # Task registered but not yet started → pending
        return IngestJobResult(job_id=job_id, paper_id=paper_id, status=JobStatus.PENDING)

    if snapshot.values.get("status") == "done":
        v = snapshot.values
        return IngestJobResult(
            job_id=job_id,
            paper_id=v.get("paper_id", paper_id),
            status=JobStatus.DONE,
            concepts_created=v.get("concepts_created"),
            concept_ids=v.get("new_concept_ids"),
            relationships_created=v.get("relationships_created"),
        )

    return IngestJobResult(
        job_id=job_id,
        paper_id=paper_id,
        status=JobStatus.FAILED,
        error=meta.get("error"),
    )


@router.post("/ingest/{job_id}/resume", response_model=IngestJobResponse, status_code=202)
async def resume_ingest_job(
    job_id: str,
    ingestion_graph: Annotated[object, Depends(get_ingestion_graph)],
    running_threads: Annotated[set, Depends(get_running_threads)],
    thread_metadata: Annotated[dict, Depends(get_thread_metadata)],
) -> IngestJobResponse:
    """Resume an interrupted ingestion job from its last checkpoint."""
    meta = thread_metadata.get(job_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")

    paper_id = meta.get("paper_id", "")
    config = {"configurable": {"thread_id": job_id}}

    # Clear any previous error so polling reflects the new attempt
    meta.pop("error", None)

    async def _run() -> None:
        running_threads.add(job_id)
        try:
            await asyncio.to_thread(ingestion_graph.invoke, None, config)
        except Exception as exc:
            logger.exception("Resume of ingestion thread %s failed: %s", job_id, exc)
            thread_metadata[job_id]["error"] = str(exc)
        finally:
            running_threads.discard(job_id)

    asyncio.create_task(_run())
    return IngestJobResponse(job_id=job_id, paper_id=paper_id, status=JobStatus.RUNNING)


@router.get("", response_model=list[PaperRead])
def list_papers(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> list[PaperRead]:
    """List all persisted papers (paginated)."""
    with get_session() as session:
        papers = session.query(Paper).offset(offset).limit(limit).all()
        return [PaperRead.model_validate(p) for p in papers]


@router.get("/{paper_id}", response_model=PaperRead)
def get_paper(paper_id: str) -> PaperRead:
    """Get a single paper by ID."""
    with get_session() as session:
        paper = session.get(Paper, paper_id)
        if paper is None:
            raise HTTPException(status_code=404, detail=f"Paper {paper_id!r} not found")
        return PaperRead.model_validate(paper)
