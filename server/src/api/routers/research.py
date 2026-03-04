"""Research router — structured multi-step query resolution pipeline.

Endpoints:
  POST /research/start           — kick off a background research job
  GET  /research/jobs/{id}       — poll for job status and results
  GET  /research/jobs/{id}/stream— stream synthesized report (Vercel AI UI protocol)
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from src.api.dependencies import (
    get_research_graph,
    get_research_metadata,
    get_research_threads,
)
from src.api.schemas import JobStatus, ResearchJobResponse, ResearchJobResult, ResearchStartRequest
from src.model.graphs.research_graph import ResearchState

router = APIRouter(prefix="/research", tags=["research"])
logger = logging.getLogger(__name__)


def _sse_line(data: str) -> bytes:
  """Format a single Server-Sent Event line."""
  return f"data: {data}\n\n".encode("utf-8")


@router.post("/start", response_model=ResearchJobResponse, status_code=202)
async def start_research_job(
    req: ResearchStartRequest,
    research_graph: Annotated[object, Depends(get_research_graph)],
    research_threads: Annotated[set, Depends(get_research_threads)],
    research_metadata: Annotated[dict, Depends(get_research_metadata)],
) -> ResearchJobResponse:
    """Start a background research job. Returns immediately with a job_id.
    Poll GET /research/jobs/{job_id} for status and the synthesized report.
    """
    job_id = str(uuid.uuid4())
    research_metadata[job_id] = {}

    initial_state: ResearchState = {
        "query": req.query,
        "job_id": job_id,
        "sub_queries": [],
        "existing_concept_ids": [],
        "existing_concept_names": [],
        "candidate_papers": [],
        "new_paper_ids": [],
        "new_paper_names": [],
        "report": "",
        "heaven_note": "",
        "canvas_concept_ids": [],
        "canvas_concept_names": [],
        "status": "running",
        "error": None,
    }
    config = {"configurable": {"thread_id": job_id}}

    async def _run() -> None:
        research_threads.add(job_id)
        try:
            await asyncio.to_thread(research_graph.invoke, initial_state, config)
        except Exception as exc:
            logger.exception("Research job %s failed: %s", job_id, exc)
            research_metadata[job_id]["error"] = str(exc)
        finally:
            research_threads.discard(job_id)

    asyncio.create_task(_run())
    return ResearchJobResponse(job_id=job_id, status=JobStatus.PENDING)


@router.get("/jobs/{job_id}", response_model=ResearchJobResult)
def get_research_job(
    job_id: str,
    research_graph: Annotated[object, Depends(get_research_graph)],
    research_threads: Annotated[set, Depends(get_research_threads)],
    research_metadata: Annotated[dict, Depends(get_research_metadata)],
) -> ResearchJobResult:
    """Poll the status of a research job."""
    meta = research_metadata.get(job_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Research job {job_id!r} not found.")

    if job_id in research_threads:
        return ResearchJobResult(job_id=job_id, status=JobStatus.RUNNING)

    config = {"configurable": {"thread_id": job_id}}
    try:
        snapshot = research_graph.get_state(config)
    except Exception as exc:
        logger.warning("Could not retrieve snapshot for research job %s: %s", job_id, exc)
        snapshot = None

    if snapshot is None or not snapshot.values:
        return ResearchJobResult(job_id=job_id, status=JobStatus.PENDING)

    values = snapshot.values
    if values.get("status") == "done":
        return ResearchJobResult(
            job_id=job_id,
            status=JobStatus.DONE,
            report=values.get("report"),
            heaven_note=values.get("heaven_note"),
            concept_ids=values.get("canvas_concept_ids") or [],
            concept_names=values.get("canvas_concept_names") or [],
            paper_ids=values.get("new_paper_ids") or [],
            paper_names=values.get("new_paper_names") or [],
        )

    error = meta.get("error")
    return ResearchJobResult(
        job_id=job_id,
        status=JobStatus.FAILED,
        error=error,
    )


@router.get("/jobs/{job_id}/stream")
async def stream_research_job(
    job_id: str,
    research_graph: Annotated[object, Depends(get_research_graph)],
    research_threads: Annotated[set, Depends(get_research_threads)],
    research_metadata: Annotated[dict, Depends(get_research_metadata)],
) -> StreamingResponse:
    """Stream the synthesized research report as a Vercel AI UI message stream (SSE)."""
    meta = research_metadata.get(job_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Research job {job_id!r} not found.")

    config = {"configurable": {"thread_id": job_id}}
    start_time = time.monotonic()
    max_wait_s = 300.0  # hard cap: 5 minutes server-side

    async def event_stream():
        nonlocal meta

        # Wait for job to finish (running → done / failed)
        while True:
            if time.monotonic() - start_time > max_wait_s:
                yield _sse_line(json.dumps({"type": "error", "errorText": "Research stream timed out"}))
                yield _sse_line("[DONE]")
                return

            if job_id in research_threads:
                await asyncio.sleep(0.7)
                continue

            try:
                snapshot = research_graph.get_state(config)
            except Exception as exc:
                logger.warning("Could not retrieve snapshot for research job %s: %s", job_id, exc)
                snapshot = None

            if snapshot is None or not snapshot.values:
                await asyncio.sleep(0.7)
                continue

            values = snapshot.values
            status = values.get("status")
            if status != "done":
                # Treat any non-done terminal state as failure.
                error_text = (meta or {}).get("error") or "Research job failed"
                yield _sse_line(json.dumps({"type": "error", "errorText": error_text}))
                yield _sse_line("[DONE]")
                return

            # Job completed successfully — stream the report
            report: str = values.get("report") or ""
            heaven_note: str = values.get("heaven_note") or ""
            concept_names = values.get("canvas_concept_names") or []

            message_id = f"research_{job_id}"
            text_id = f"text_{job_id}"

            # Message start
            yield _sse_line(json.dumps({"type": "start", "messageId": message_id}))

            # Text stream
            yield _sse_line(json.dumps({"type": "text-start", "id": text_id}))
            chunk_size = 128
            for i in range(0, len(report), chunk_size):
                chunk = report[i : i + chunk_size]
                yield _sse_line(json.dumps({"type": "text-delta", "id": text_id, "delta": chunk}))
            yield _sse_line(json.dumps({"type": "text-end", "id": text_id}))

            # HEAVEN metadata for Agent pane
            yield _sse_line(
                json.dumps(
                    {
                        "type": "data-heaven-research",
                        "data": {
                            "job_id": job_id,
                            "heaven_note": heaven_note,
                            "concept_names": concept_names,
                        },
                    }
                )
            )

            # Finish
            yield _sse_line(json.dumps({"type": "finish"}))
            yield _sse_line("[DONE]")
            return

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "x-vercel-ai-ui-message-stream": "v1",
        },
    )
