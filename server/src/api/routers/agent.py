"""Agent tab streaming — lightweight synthesis grounded on staged papers only (no Exa/arXiv).

Streams three phases to the client:
  1. reasoning   – live thinking/decision-making (shown in chat pane)
  2. text-delta  – LaTeX document content (streamed into editor)
  3. metadata    – heaven_note, verification, correlations
"""

import asyncio
import json
import logging
import re
import threading
import time
import uuid
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.api.routers.chat import _load_staged_papers
from src.api.routers.verify import get_correlations, get_nudges
from src.api.schemas import CorrelateRequest, NudgeRequest, ParagraphInput
from src.model.graphs.agent_synthesis import parse_report_and_note, stream_agent_synthesis

router = APIRouter(prefix="/agent", tags=["agent"])
logger = logging.getLogger(__name__)

_DOC_HEADER_RE = re.compile(
    r"(?:#+ *)?(?:\*\*)?DOCUMENT[_ ]?CONTENT(?:\*\*)?:?",
    re.IGNORECASE,
)
_NOTE_HEADER_RE = re.compile(
    r"(?:#+ *)?(?:\*\*)?HEAVEN[_ ]?NOTE(?:\*\*)?:?",
    re.IGNORECASE,
)


class AgentStreamRequest(BaseModel):
    query: str
    staged_paper_ids: list[str] = []
    canvas_summary: str = ""


def _sse_line(data: str) -> bytes:
    return f"data: {data}\n\n".encode("utf-8")


def _report_to_blocks(report: str) -> list[dict]:
    """Split report into blocks for nudge API: [{ type, content }, ...]."""
    blocks: list[dict] = []
    for part in report.split("\n\n"):
        part = part.strip()
        if len(part) < 20:
            continue
        blocks.append({"type": "paragraph", "content": part})
    return blocks[:20]


def _report_to_paragraphs(report: str) -> list[dict]:
    """Split report into paragraphs with start_char/end_char for correlate API."""
    paragraphs: list[dict] = []
    start = 0
    for part in report.split("\n\n"):
        part = part.strip()
        if len(part) < 30:
            start += len(part) + 2
            continue
        idx = report.find(part, start)
        if idx == -1:
            idx = start
        end = idx + len(part)
        paragraphs.append({"text": part, "start_char": idx, "end_char": end})
        start = end + 2
        if len(paragraphs) >= 15:
            break
    return paragraphs


async def _agent_stream_generator(
    query: str,
    staged_paper_ids: list[str],
    canvas_summary: str,
):
    """Yield SSE lines for Agent synthesis with live reasoning.

    The model output has three sections: REASONING, DOCUMENT_CONTENT, HEAVEN_NOTE.
    We detect section boundaries in the stream and emit:
      - {"type": "reasoning-delta", "delta": "..."} during REASONING
      - {"type": "text-delta", "delta": "..."}      during DOCUMENT_CONTENT
    """
    staged_papers = await asyncio.to_thread(_load_staged_papers, staged_paper_ids)

    message_id = f"agent_{uuid.uuid4().hex}"
    text_id = f"text_{uuid.uuid4().hex}"

    yield _sse_line(json.dumps({"type": "start", "messageId": message_id}))

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    full_chunks: list[str] = []
    exc_holder: list[BaseException] = []
    t0 = time.perf_counter()

    def run_sync_stream():
        try:
            for chunk in stream_agent_synthesis(query, staged_papers, canvas_summary):
                full_chunks.append(chunk)
                loop.call_soon_threadsafe(queue.put_nowait, ("chunk", chunk))
            loop.call_soon_threadsafe(queue.put_nowait, ("done", None))
        except BaseException as e:
            exc_holder.append(e)
            loop.call_soon_threadsafe(queue.put_nowait, ("done", None))

    thread = threading.Thread(target=run_sync_stream, daemon=True)
    thread.start()

    # Track which section we're in based on accumulated text
    accumulated = ""
    # "reasoning" | "document" | "note"
    current_section = "reasoning"
    sent_text_start = False

    while True:
        try:
            msg = await asyncio.wait_for(queue.get(), timeout=300.0)
        except asyncio.TimeoutError:
            logger.warning("Agent stream timed out")
            yield _sse_line(json.dumps({"type": "error", "errorText": "Agent synthesis timed out"}))
            break
        if msg[0] == "done":
            break
        if msg[0] == "chunk" and msg[1]:
            chunk_text = msg[1]
            accumulated += chunk_text

            # Check for section transitions in accumulated text
            if current_section == "reasoning":
                doc_match = _DOC_HEADER_RE.search(accumulated)
                if doc_match:
                    # Everything before DOCUMENT_CONTENT is reasoning
                    # Emit any remaining reasoning text before the header
                    before = accumulated[:doc_match.start()]
                    # We may have already sent some reasoning; only send the new part
                    # But since we track by accumulated, just send this chunk as reasoning
                    # up to the header, then switch
                    current_section = "document"
                    # Trim accumulated to just what's after the header
                    accumulated = accumulated[doc_match.end():]
                    if not sent_text_start:
                        yield _sse_line(json.dumps({"type": "text-start", "id": text_id}))
                        sent_text_start = True
                    # Send any content after the header as document
                    if accumulated.lstrip().startswith("\n"):
                        accumulated = accumulated.lstrip("\n")
                    if accumulated:
                        yield _sse_line(json.dumps({"type": "text-delta", "id": text_id, "delta": accumulated}))
                        accumulated = ""
                    continue
                # Still in reasoning section — emit as reasoning-delta
                yield _sse_line(json.dumps({"type": "reasoning-delta", "delta": chunk_text}))
                continue

            if current_section == "document":
                note_match = _NOTE_HEADER_RE.search(accumulated)
                if note_match:
                    # Send content before HEAVEN_NOTE as document content
                    before_note = accumulated[:note_match.start()]
                    if before_note.strip():
                        yield _sse_line(json.dumps({"type": "text-delta", "id": text_id, "delta": before_note}))
                    current_section = "note"
                    accumulated = accumulated[note_match.end():]
                    continue
                # Still in document section — emit as text-delta
                yield _sse_line(json.dumps({"type": "text-delta", "id": text_id, "delta": chunk_text}))
                accumulated = chunk_text  # reset to just current chunk for next header check
                continue

            # In note section — don't stream (will be sent as metadata)

    if exc_holder:
        yield _sse_line(json.dumps({"type": "error", "errorText": str(exc_holder[0])}))
        yield _sse_line("[DONE]")
        return

    if sent_text_start:
        yield _sse_line(json.dumps({"type": "text-end", "id": text_id}))

    raw = "".join(full_chunks)
    logger.info("Agent synthesis completed in %.2fs (%d chars)", time.perf_counter() - t0, len(raw))
    reasoning, report, heaven_note = parse_report_and_note(raw)

    if not report and raw.strip():
        logger.warning(
            "Agent report is EMPTY but raw output has %d chars. Snippet:\n%.600s",
            len(raw), raw,
        )

    concept_names = []
    for p in staged_papers:
        for c in p.get("concepts", [])[:5]:
            concept_names.append(c.get("name", ""))

    yield _sse_line(
        json.dumps(
            {
                "type": "data-heaven-research",
                "data": {
                    "heaven_note": heaven_note,
                    "concept_names": concept_names,
                    "report": report,
                    "reasoning": reasoning,
                },
            }
        )
    )

    # Verification and correlation
    if report and staged_paper_ids:
        t_verify = time.perf_counter()
        try:
            blocks = _report_to_blocks(report)
            if blocks:
                nudge_result = await asyncio.to_thread(
                    get_nudges,
                    NudgeRequest(blocks=blocks, staged_paper_ids=staged_paper_ids),
                )
                nudge_list = [n.model_dump() for n in nudge_result.nudges]
                yield _sse_line(
                    json.dumps(
                        {
                            "type": "data-heaven-nudges",
                            "data": {"nudges": nudge_list},
                        }
                    )
                )
            para_dicts = _report_to_paragraphs(report)
            if para_dicts and staged_paper_ids:
                paragraphs = [
                    ParagraphInput(text=p["text"], start_char=p["start_char"], end_char=p["end_char"])
                    for p in para_dicts
                ]
                corr_result = await asyncio.to_thread(
                    get_correlations,
                    CorrelateRequest(paragraphs=paragraphs, staged_paper_ids=staged_paper_ids),
                )
                yield _sse_line(
                    json.dumps(
                        {
                            "type": "data-heaven-correlation",
                            "data": {
                                "correlations": [c.model_dump() for c in corr_result.correlations],
                            },
                        }
                    )
                )
            logger.info("Agent verify/correlate completed in %.2fs", time.perf_counter() - t_verify)
        except Exception as e:
            logger.warning("Agent verify/correlate failed after %.2fs: %s", time.perf_counter() - t_verify, e)
            yield _sse_line(
                json.dumps(
                    {
                        "type": "data-heaven-verification",
                        "data": {
                            "nudges": [],
                            "error": str(e),
                        },
                    }
                )
            )

    yield _sse_line(json.dumps({"type": "finish"}))
    yield _sse_line("[DONE]")


@router.post("/stream")
async def agent_stream(request: AgentStreamRequest) -> StreamingResponse:
    """Stream Agent synthesis (staged papers + model only, no external search)."""
    return StreamingResponse(
        _agent_stream_generator(
            query=request.query,
            staged_paper_ids=request.staged_paper_ids or [],
            canvas_summary=request.canvas_summary or "",
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "x-vercel-ai-ui-message-stream": "v1",
        },
    )
