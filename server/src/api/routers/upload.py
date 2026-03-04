"""Upload router — ingest a PDF directly via multipart/form-data.

POST /papers/upload   field: file (PDF)
→ Extracts text with PyMuPDF, persists Paper row, spawns ingestion pipeline.
→ Returns IngestJobResponse (identical shape to arXiv ingest).
"""

import asyncio
import logging
import uuid
from typing import Annotated

import fitz  # PyMuPDF
from fastapi import APIRouter, Depends, HTTPException, UploadFile

from src.api.dependencies import (
    get_ingestion_graph,
    get_running_threads,
    get_thread_metadata,
)
from src.api.schemas import IngestJobResponse, JobStatus
from src.db.chroma import collections
from src.db.sqlite.models import Paper
from src.db.sqlite.session import get_session
from src.model.graphs.ingestion_graph import IngestionState

router = APIRouter(prefix="/papers", tags=["papers"])
logger = logging.getLogger(__name__)


@router.post("/upload", response_model=IngestJobResponse, status_code=202)
async def upload_paper(
    file: UploadFile,
    ingestion_graph: Annotated[object, Depends(get_ingestion_graph)],
    running_threads: Annotated[set, Depends(get_running_threads)],
    thread_metadata: Annotated[dict, Depends(get_thread_metadata)],
) -> IngestJobResponse:
    """Upload a PDF and ingest it into the knowledge base.

    Extracts full text with PyMuPDF, persists a Paper row with source_type='upload',
    and spawns a background ingestion job. Returns immediately with job_id.
    """
    if file.content_type and not file.content_type.startswith("application/pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Extract text and metadata from PDF
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse PDF: {exc}")

    text = "\n\n".join(page.get_text() for page in doc)
    if not text.strip():
        raise HTTPException(status_code=422, detail="PDF contains no extractable text")

    pdf_metadata = doc.metadata or {}
    title = (
        pdf_metadata.get("title")
        or (file.filename.removesuffix(".pdf") if file.filename else None)
        or "Uploaded PDF"
    )
    doc.close()

    # Persist Paper row
    paper_id = str(uuid.uuid4())
    filename = file.filename or "upload.pdf"
    with get_session() as session:
        db_paper = Paper(
            id=paper_id,
            source_type="upload",
            title=title,
            authors=[],
            abstract=text[:500] if text else None,   # store first 500 chars as abstract
            url=f"upload://{filename}",
        )
        session.add(db_paper)

    # Upsert a brief abstract into ChromaDB for searchability
    abstract_snippet = text[:500]
    if abstract_snippet:
        try:
            collections.upsert_paper(
                paper_id=paper_id,
                abstract=abstract_snippet,
                metadata={"title": title, "arxiv_id": ""},
            )
        except Exception as exc:
            logger.warning("ChromaDB upsert failed for uploaded paper %s: %s", paper_id, exc)

    # Register thread and spawn background ingestion
    thread_id = str(uuid.uuid4())
    thread_metadata[thread_id] = {"paper_id": paper_id}

    initial_state: IngestionState = {
        "paper_id": paper_id,
        "arxiv_id": "",
        "content": text,          # pre-populated — fetch_content node will skip fetching
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
            logger.exception("Upload ingestion thread %s failed: %s", thread_id, exc)
            thread_metadata[thread_id]["error"] = str(exc)
        finally:
            running_threads.discard(thread_id)

    asyncio.create_task(_run())
    return IngestJobResponse(job_id=thread_id, paper_id=paper_id, status=JobStatus.PENDING)
