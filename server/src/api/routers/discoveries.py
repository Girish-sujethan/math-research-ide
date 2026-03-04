"""Discoveries router — create (background pipeline), list, retrieve, impacts, resume."""

import asyncio
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import (
    get_discovery_graph,
    get_running_threads,
    get_thread_metadata,
)
from src.api.schemas import DiscoveryJobResponse, DiscoveryJobResult, JobStatus
from src.db.sqlite.models import Discovery, DiscoveryImpact
from src.db.sqlite.session import get_session
from src.model.graphs.discovery_graph import DiscoveryState
from src.schemas.models import DiscoveryCreate, DiscoveryRead, ImpactRead

router = APIRouter(prefix="/discoveries", tags=["discoveries"])
logger = logging.getLogger(__name__)


@router.post("", response_model=DiscoveryJobResponse, status_code=202)
async def create_discovery(
    discovery_create: DiscoveryCreate,
    discovery_graph: Annotated[object, Depends(get_discovery_graph)],
    running_threads: Annotated[set, Depends(get_running_threads)],
    thread_metadata: Annotated[dict, Depends(get_thread_metadata)],
) -> DiscoveryJobResponse:
    """Run the full discovery pipeline (SymPy → Lean 4 → impact analysis) in the background.

    Returns a job_id immediately. Poll GET /discoveries/jobs/{job_id} for the result,
    which includes the discovery_id once complete.
    """
    import uuid
    thread_id = str(uuid.uuid4())
    thread_metadata[thread_id] = {}

    initial_state: DiscoveryState = {
        "name": discovery_create.name,
        "base_concept_id": discovery_create.base_concept_id,
        "modified_latex_statement": discovery_create.modified_latex_statement,
        "modification_description": discovery_create.modification_description,
        "discovery_id": "",
        "concept_type": "theorem",
        "base_concept": None,
        "sympy_passed": None,
        "sympy_output": None,
        "sympy_status": "unchecked",
        "lean_success": False,
        "lean_output": None,
        "lean_status": "unverified",
        "affected": {},
        "conflict_ids": [],
        "impacts": [],
        "conflict_explanations": [],
        "status": "running",
    }
    config = {"configurable": {"thread_id": thread_id}}

    async def _run() -> None:
        running_threads.add(thread_id)
        try:
            await asyncio.to_thread(discovery_graph.invoke, initial_state, config)
        except Exception as exc:
            logger.exception("Discovery thread %s failed: %s", thread_id, exc)
            thread_metadata[thread_id]["error"] = str(exc)
        finally:
            running_threads.discard(thread_id)

    asyncio.create_task(_run())
    return DiscoveryJobResponse(job_id=thread_id, status=JobStatus.PENDING)


@router.get("/jobs/{job_id}", response_model=DiscoveryJobResult)
def get_discovery_job_status(
    job_id: str,
    discovery_graph: Annotated[object, Depends(get_discovery_graph)],
    running_threads: Annotated[set, Depends(get_running_threads)],
    thread_metadata: Annotated[dict, Depends(get_thread_metadata)],
) -> DiscoveryJobResult:
    """Poll the status of a discovery pipeline job."""
    meta = thread_metadata.get(job_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")

    if job_id in running_threads:
        return DiscoveryJobResult(job_id=job_id, status=JobStatus.RUNNING)

    config = {"configurable": {"thread_id": job_id}}
    snapshot = discovery_graph.get_state(config)

    if snapshot is None or not snapshot.values:
        return DiscoveryJobResult(job_id=job_id, status=JobStatus.PENDING)

    if snapshot.values.get("status") == "done":
        v = snapshot.values
        return DiscoveryJobResult(
            job_id=job_id,
            status=JobStatus.DONE,
            discovery_id=v.get("discovery_id"),
            sympy_status=v.get("sympy_status"),
            lean_status=v.get("lean_status"),
            impacts_count=len(v.get("impacts", [])),
            conflict_count=len(v.get("conflict_ids", [])),
        )

    return DiscoveryJobResult(
        job_id=job_id,
        status=JobStatus.FAILED,
        error=meta.get("error"),
    )


@router.post("/jobs/{job_id}/resume", response_model=DiscoveryJobResponse, status_code=202)
async def resume_discovery_job(
    job_id: str,
    discovery_graph: Annotated[object, Depends(get_discovery_graph)],
    running_threads: Annotated[set, Depends(get_running_threads)],
    thread_metadata: Annotated[dict, Depends(get_thread_metadata)],
) -> DiscoveryJobResponse:
    """Resume an interrupted discovery job from its last checkpoint."""
    meta = thread_metadata.get(job_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")

    config = {"configurable": {"thread_id": job_id}}
    meta.pop("error", None)

    async def _run() -> None:
        running_threads.add(job_id)
        try:
            await asyncio.to_thread(discovery_graph.invoke, None, config)
        except Exception as exc:
            logger.exception("Resume of discovery thread %s failed: %s", job_id, exc)
            thread_metadata[job_id]["error"] = str(exc)
        finally:
            running_threads.discard(job_id)

    asyncio.create_task(_run())
    return DiscoveryJobResponse(job_id=job_id, status=JobStatus.RUNNING)


@router.get("", response_model=list[DiscoveryRead])
def list_discoveries(
    lean_status: Optional[str] = Query(None),
    sympy_status: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> list[DiscoveryRead]:
    """List all discoveries with optional status filters."""
    with get_session() as session:
        q = session.query(Discovery)
        if lean_status:
            q = q.filter(Discovery.lean_verification_status == lean_status)
        if sympy_status:
            q = q.filter(Discovery.sympy_check_status == sympy_status)
        return [DiscoveryRead.model_validate(d) for d in q.offset(offset).limit(limit).all()]


@router.get("/{discovery_id}", response_model=DiscoveryRead)
def get_discovery(discovery_id: str) -> DiscoveryRead:
    """Get a single discovery by ID."""
    with get_session() as session:
        discovery = session.get(Discovery, discovery_id)
        if discovery is None:
            raise HTTPException(
                status_code=404, detail=f"Discovery {discovery_id!r} not found"
            )
        return DiscoveryRead.model_validate(discovery)


@router.get("/{discovery_id}/impacts", response_model=list[ImpactRead])
def get_discovery_impacts(discovery_id: str) -> list[ImpactRead]:
    """Get all impact rows for a discovery."""
    with get_session() as session:
        if session.get(Discovery, discovery_id) is None:
            raise HTTPException(
                status_code=404, detail=f"Discovery {discovery_id!r} not found"
            )
        impacts = (
            session.query(DiscoveryImpact)
            .filter(DiscoveryImpact.discovery_id == discovery_id)
            .all()
        )
        return [ImpactRead.model_validate(i) for i in impacts]
