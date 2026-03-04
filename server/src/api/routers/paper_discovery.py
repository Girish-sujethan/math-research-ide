"""Paper Discovery router — AI-driven paper search via LangGraph pipeline.

Endpoints:
  POST /papers/discover           — kick off a background discovery job
  GET  /papers/discover/{job_id}  — poll for job status and ranked results
"""

import asyncio
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.api.dependencies import (
    get_paper_discovery_graph,
    get_paper_discovery_metadata,
    get_paper_discovery_threads,
)
from src.api.schemas import (
    DiscoveredPaper,
    JobStatus,
    PaperDiscoveryJobResponse,
    PaperDiscoveryJobResult,
    PaperDiscoveryRequest,
)
from src.model.graphs.paper_discovery_graph import PaperDiscoveryState

router = APIRouter(prefix="/papers/discover", tags=["paper-discovery"])
logger = logging.getLogger(__name__)


@router.post("", response_model=PaperDiscoveryJobResponse, status_code=202)
async def start_paper_discovery(
    req: PaperDiscoveryRequest,
    paper_discovery_graph: Annotated[object, Depends(get_paper_discovery_graph)],
    paper_discovery_threads: Annotated[set, Depends(get_paper_discovery_threads)],
    paper_discovery_metadata: Annotated[dict, Depends(get_paper_discovery_metadata)],
) -> PaperDiscoveryJobResponse:
    """Start a background paper discovery job. Returns immediately with a job_id.
    Poll GET /papers/discover/{job_id} for status and results.
    """
    job_id = str(uuid.uuid4())
    paper_discovery_metadata[job_id] = {}

    initial_state: PaperDiscoveryState = {
        "query": req.query,
        "job_id": job_id,
        "sub_queries": [],
        "raw_results": [],
        "ranked_papers": [],
        "status": "running",
        "error": None,
    }
    config = {"configurable": {"thread_id": job_id}}

    async def _run() -> None:
        paper_discovery_threads.add(job_id)
        try:
            await asyncio.to_thread(paper_discovery_graph.invoke, initial_state, config)
        except Exception as exc:
            logger.exception("Paper discovery %s failed: %s", job_id, exc)
            paper_discovery_metadata[job_id]["error"] = str(exc)
        finally:
            paper_discovery_threads.discard(job_id)

    asyncio.create_task(_run())
    return PaperDiscoveryJobResponse(job_id=job_id, status=JobStatus.PENDING)


@router.get("/{job_id}", response_model=PaperDiscoveryJobResult)
def get_paper_discovery_status(
    job_id: str,
    paper_discovery_graph: Annotated[object, Depends(get_paper_discovery_graph)],
    paper_discovery_threads: Annotated[set, Depends(get_paper_discovery_threads)],
    paper_discovery_metadata: Annotated[dict, Depends(get_paper_discovery_metadata)],
) -> PaperDiscoveryJobResult:
    """Poll the status of a paper discovery job."""
    meta = paper_discovery_metadata.get(job_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Paper discovery job {job_id!r} not found.")

    if job_id in paper_discovery_threads:
        return PaperDiscoveryJobResult(job_id=job_id, status=JobStatus.RUNNING)

    config = {"configurable": {"thread_id": job_id}}
    try:
        snapshot = paper_discovery_graph.get_state(config)
    except Exception as exc:
        logger.warning("Could not retrieve snapshot for paper discovery job %s: %s", job_id, exc)
        snapshot = None

    if snapshot is None or not snapshot.values:
        return PaperDiscoveryJobResult(job_id=job_id, status=JobStatus.PENDING)

    values = snapshot.values
    if values.get("status") == "done":
        raw_papers = values.get("ranked_papers") or []
        papers = [
            DiscoveredPaper(
                arxiv_id=p.get("arxiv_id"),
                title=p.get("title", ""),
                authors=p.get("authors") or [],
                abstract=p.get("abstract"),
                url=p.get("url", ""),
                source=p.get("source", ""),
                relevance_score=float(p.get("relevance_score", 0.0)),
                relevance_explanation=str(p.get("relevance_explanation", "Unranked")),
            )
            for p in raw_papers
        ]
        return PaperDiscoveryJobResult(
            job_id=job_id,
            status=JobStatus.DONE,
            stage="done",
            papers=papers,
        )

    # Still running — return intermediate stage for progress indicator
    stage = values.get("status")
    return PaperDiscoveryJobResult(
        job_id=job_id,
        status=JobStatus.RUNNING,
        stage=stage,
        error=meta.get("error"),
    )
