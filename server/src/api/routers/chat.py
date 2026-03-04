"""Chat router — fully autonomous conversational agent.

Flow per message:
  1. Restore or create session history.
  2. Call the primary LLM with the HEAVEN system prompt + conversation history.
  3. Parse the structured JSON response (reply + optional action).
  4. ALL actions execute immediately — no user confirmation required.
  5. If search_concepts returns empty, auto-chain: search arXiv → ingest top result.
"""

import asyncio
import json
import logging
import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from src.api.dependencies import (
    get_discovery_graph,
    get_ingestion_graph,
    get_research_graph,
    get_research_metadata,
    get_research_threads,
    get_running_threads,
    get_sessions,
    get_thread_metadata,
)
from src.api.schemas import CanvasItem, ChatRequest, ChatResponse, ChatStreamRequest
from src.db.chroma import collections
from src.db.sqlite.models import Concept, Paper
from src.db.sqlite.session import get_session
from src.graph import knowledge_graph
from src.ingestion import arxiv_client
from src.model.graphs.discovery_graph import DiscoveryState
from src.model.graphs.ingestion_graph import IngestionState
from src.model.providers.registry import primary

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)

# Rolling window applied to stored session history after each assistant turn.
_MAX_HISTORY_TURNS = 20

# Sentinel prefix used internally to signal an empty concept search result
# so the outer async handler can chain to paper search + ingest.
_EMPTY_SENTINEL = "__EMPTY_CONCEPTS__"

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_BASE = """\
You are HEAVEN, an AI research assistant for mathematicians. You help users explore
mathematical concepts, understand research, and analyze proposed modifications.

WORKFLOW:
1. When a user asks about a mathematical topic or concept:
   - ALWAYS call search_concepts first to check the knowledge base.
   - If the result is empty or sparse, call search_papers (source: "arxiv") then
     ingest_paper for the most relevant result — do this proactively without asking.
   - Answer using both your own mathematical knowledge and any retrieved concepts.
   - Provide background, proofs, significance, related work, and citations as appropriate.

2. When a user proposes a modification ("what if I added X", "suppose we require Y",
   "what changes if Z", "what happens if we drop condition W"):
   - Call search_concepts to find the base concept and note its ID.
   - Generate a precise modified LaTeX statement for the proposed change.
   - Call create_discovery with the concept_id, your generated LaTeX, and a clear
     description of the modification.
   - Explain what you expect will break, what new implications arise, and what other
     concepts might be affected.

ALL actions execute automatically — never ask the user to confirm anything.

Always respond with valid JSON only (no markdown fences, no extra text):
{"thinking": "...", "reply": "...", "sources": [], "action": null}
or
{"thinking": "...", "reply": "...", "sources": ["paper_id_1"], "action": {"type": "...", "payload": {...}}}

Fields:
- "thinking": your brief internal reasoning (1-3 sentences, not shown directly to the user)
- "reply": your response to the user
- "sources": list of paper IDs from the staged papers that you referenced in your answer
- "action": optional action to execute

Available actions:
- "search_concepts"   payload: {"query": "...", "n_results": 5}
- "show_concept"      payload: {"concept_id": "..."}
- "show_impact"       payload: {"concept_id": "..."}
- "search_papers"     payload: {"query": "...", "source": "arxiv", "limit": 5}
- "ingest_paper"      payload: {"arxiv_id": "..."}
- "create_discovery"  payload: {"name": "...", "base_concept_id": "...",
                                "modified_latex_statement": "...",
                                "modification_description": "..."}

Rules:
- Never fabricate concept IDs — only use IDs returned by search_concepts results.
- For create_discovery, always write syntactically correct LaTeX for modified_latex_statement.
- base_concept_id may be omitted from create_discovery if no matching concept exists yet.
- Respond with valid JSON only — no markdown, no text outside the JSON object.
"""


def _load_staged_papers(ids: list[str]) -> list[dict]:
    """Load Paper rows + top 8 concepts per paper from SQLite."""
    if not ids:
        return []
    result = []
    with get_session() as session:
        for paper_id in ids:
            paper = session.get(Paper, paper_id)
            if paper is None:
                continue
            concepts = (
                session.query(Concept)
                .filter(Concept.source_paper_id == paper_id)
                .limit(8)
                .all()
            )
            result.append({
                "id": paper.id,
                "title": paper.title,
                "authors": paper.authors,
                "abstract": (paper.abstract or "")[:600],
                "concepts": [
                    {
                        "name": c.name,
                        "type": c.concept_type,
                        "latex": c.latex_statement[:200],
                    }
                    for c in concepts
                ],
            })
    return result


def _build_system(staged_papers: list[dict], canvas_summary: str) -> str:
    """Build contextual system prompt, grounded in staged papers when available."""
    if not staged_papers:
        suffix = (
            "\n\nNo papers are currently staged. "
            "Prompt the user to Stage a Source in the Knowledge Vault for grounded, "
            "specific theorem references."
        )
        return _SYSTEM_BASE + suffix

    lines = ["\n\n── STAGED PAPERS (ground your responses in these) ──"]
    for p in staged_papers:
        lines.append(f"\n[Paper ID: {p['id']}]")
        lines.append(f"Title: {p['title']}")
        if p["authors"]:
            lines.append(f"Authors: {', '.join(p['authors'][:3])}")
        if p["abstract"]:
            lines.append(f"Abstract (excerpt): {p['abstract']}")
        if p["concepts"]:
            lines.append("Key concepts extracted:")
            for c in p["concepts"]:
                lines.append(f"  - {c['name']} ({c['type']}): {c['latex']}")

    if canvas_summary:
        lines.append(f"\n── CURRENT DOCUMENT (user's work-in-progress) ──\n{canvas_summary}")

    lines.append(
        "\n\nIMPORTANT: Prefer referencing theorems and definitions from the staged papers above. "
        "When you reference a staged paper, include its ID in the 'sources' field of your JSON response."
    )
    return _SYSTEM_BASE + "\n".join(lines)

_READ_ACTIONS = {"search_concepts", "show_concept", "show_impact", "search_papers"}


async def _get_perplexity_context(message: str) -> str:
    """Fetch web-grounded context from Perplexity. Returns empty string if not configured."""
    from src.config import settings
    if not settings.perplexity_api_key:
        return ""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.perplexity.ai/chat/completions",
                headers={"Authorization": f"Bearer {settings.perplexity_api_key}"},
                json={
                    "model": settings.perplexity_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Briefly summarize relevant mathematical context for the query "
                                "in 2-4 sentences, with key references."
                            ),
                        },
                        {"role": "user", "content": message},
                    ],
                    "max_tokens": 300,
                },
            )
        return resp.json()["choices"][0]["message"]["content"]
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Read-action helpers (synchronous — run via asyncio.to_thread)
# ---------------------------------------------------------------------------

def _execute_read_action(action_type: str, payload: dict) -> tuple[str, list[CanvasItem]]:
    """Execute a read-only action. Returns (text_to_append, canvas_items)."""
    try:
        if action_type == "search_concepts":
            query = payload.get("query", "")
            n = min(int(payload.get("n_results", 5)), 20)
            res = collections.query_concepts(query, n_results=n)
            ids = res.get("ids", [[]])[0]
            metas = res.get("metadatas", [[]])[0]
            if not ids:
                # Return a sentinel so the async handler can auto-ingest
                return f"\n\n{_EMPTY_SENTINEL}{query}{_EMPTY_SENTINEL}", []
            lines = ["\n\n**Concepts in knowledge base:**"]
            canvas_items: list[CanvasItem] = []
            for cid, meta in zip(ids, metas):
                name = meta.get("name", cid)
                ctype = meta.get("concept_type", "")
                lines.append(f"- **{name}** ({ctype}) — `{cid}`")
                canvas_items.append(CanvasItem(type="concept", id=cid, name=name))
            return "\n".join(lines), canvas_items

        if action_type == "show_concept":
            concept_id = payload.get("concept_id", "")
            with get_session() as session:
                concept = session.get(Concept, concept_id)
            if concept is None:
                return f"\n\n*Concept `{concept_id}` not found.*", []
            desc = concept.description or ""
            text = (
                f"\n\n**{concept.name}** ({concept.concept_type})\n"
                f"```latex\n{concept.latex_statement}\n```"
                + (f"\n{desc}" if desc else "")
            )
            return text, [CanvasItem(type="concept", id=concept_id, name=concept.name)]

        if action_type == "show_impact":
            concept_id = payload.get("concept_id", "")
            g = knowledge_graph.build_graph()
            affected = knowledge_graph.get_impact_subgraph(g, concept_id)
            conflicts = knowledge_graph.find_potential_conflicts(g, concept_id)
            if not affected and not conflicts:
                return "\n\n*No impacts or conflicts found for this concept.*", []
            lines = ["\n\n**Impact analysis:**"]
            for rel_type, cids in affected.items():
                lines.append(f"- **{rel_type}**: {len(cids)} concept(s) affected")
            if conflicts:
                lines.append(f"- **contradicts**: {len(conflicts)} concept(s)")
            return "\n".join(lines), []

        if action_type == "search_papers":
            query = payload.get("query", "")
            limit = min(int(payload.get("limit", 5)), 20)
            papers = arxiv_client.search(query, max_results=limit)
            if not papers:
                return "\n\n*No papers found.*", []
            lines = ["\n\n**Papers found:**"]
            for p in papers:
                arxiv_id = getattr(p, "arxiv_id", None)
                suffix = f" — arXiv:`{arxiv_id}`" if arxiv_id else ""
                lines.append(f"- {p.title}{suffix}")
            return "\n".join(lines), []

    except Exception as exc:
        logger.warning("Read action %s failed: %s", action_type, exc)
        return f"\n\n*Could not complete {action_type}: {exc}*", []

    return "", []


# ---------------------------------------------------------------------------
# Write-action helpers (async — spawn background tasks)
# ---------------------------------------------------------------------------

async def _execute_ingest(
    arxiv_id: str,
    ingestion_graph,
    running_threads: set,
    thread_metadata: dict,
) -> tuple[str, list[CanvasItem]]:
    """Persist paper metadata and start a background ingestion job.
    Returns (text_to_append, canvas_items) — canvas_items contains a loading placeholder."""
    with get_session() as session:
        existing = session.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
        if existing is not None:
            canvas_item = CanvasItem(type="paper", id=existing.id, name=existing.title)
            return f"\n\n*Paper `{arxiv_id}` is already in the knowledge base.*", [canvas_item]

    meta = await asyncio.to_thread(arxiv_client.fetch_by_id, arxiv_id)
    if meta is None:
        return f"\n\n*Could not find arXiv paper `{arxiv_id}`.*", []

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

    if meta.abstract:
        try:
            collections.upsert_paper(
                paper_id=paper_id,
                abstract=meta.abstract,
                metadata={"title": meta.title, "arxiv_id": meta.arxiv_id or ""},
            )
        except Exception as exc:
            logger.warning("ChromaDB upsert failed for paper %s: %s", paper_id, exc)

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
            logger.exception("Chat-triggered ingestion %s failed: %s", thread_id, exc)
            thread_metadata[thread_id]["error"] = str(exc)
        finally:
            running_threads.discard(thread_id)

    asyncio.create_task(_run())
    canvas_item = CanvasItem(type="paper", id=paper_id, name=meta.title)
    return (
        f"\n\n*Ingesting **{meta.title}** into the knowledge base. "
        f"Concept extraction takes a few minutes — ask me about this topic again shortly.*",
        [canvas_item],
    )


async def _start_research_job(
    query: str,
    research_graph,
    research_threads: set,
    research_metadata: dict,
) -> tuple[str, list[CanvasItem]]:
    """Kick off a background research job. Returns (reply_text, [research-job canvas item])."""
    job_id = str(uuid.uuid4())
    research_metadata[job_id] = {}
    from src.model.graphs.research_graph import ResearchState

    initial_state: ResearchState = {
        "query": query,
        "job_id": job_id,
        "sub_queries": [],
        "existing_concept_ids": [],
        "existing_concept_names": [],
        "candidate_papers": [],
        "new_paper_ids": [],
        "new_paper_names": [],
        "report": "",
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
    canvas_item = CanvasItem(type="research-job", id=job_id, name=query)
    reply_text = (
        f"\n\n*Starting deep research on **'{query}'**…*\n"
        f"I'm decomposing your query, searching the knowledge base, finding relevant papers, "
        f"and preparing a synthesis. This takes 30–60 seconds — results will appear automatically."
    )
    return reply_text, [canvas_item]


async def _execute_discovery(
    payload: dict,
    discovery_graph,
    running_threads: set,
    thread_metadata: dict,
) -> str:
    """Start a discovery analysis pipeline in the background."""
    name = payload.get("name", "")
    base_concept_id = payload.get("base_concept_id") or None
    modified_latex = payload.get("modified_latex_statement", "")
    mod_description = payload.get("modification_description", "")

    if not name or not modified_latex or not mod_description:
        return (
            "\n\n*Could not start discovery analysis — "
            "name, modified_latex_statement, and modification_description are all required.*"
        )

    thread_id = str(uuid.uuid4())
    thread_metadata[thread_id] = {}
    initial_state: DiscoveryState = {
        "name": name,
        "base_concept_id": base_concept_id,
        "modified_latex_statement": modified_latex,
        "modification_description": mod_description,
        "discovery_id": "",
        "concept_type": "",
        "base_concept": None,
        "sympy_passed": None,
        "sympy_output": None,
        "sympy_status": "pending",
        "lean_success": False,
        "lean_output": None,
        "lean_status": "pending",
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
            logger.exception("Chat-triggered discovery %s failed: %s", thread_id, exc)
            thread_metadata[thread_id]["error"] = str(exc)
        finally:
            running_threads.discard(thread_id)

    asyncio.create_task(_run())
    return (
        f"\n\n*Started analysis of **{name}**. "
        f"Running symbolic verification → Lean 4 formalization → "
        f"graph impact analysis → conflict detection. "
        f"Check the Discoveries tab for live results.*"
    )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post("", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    sessions: Annotated[dict, Depends(get_sessions)],
    ingestion_graph: Annotated[object, Depends(get_ingestion_graph)],
    discovery_graph: Annotated[object, Depends(get_discovery_graph)],
    running_threads: Annotated[set, Depends(get_running_threads)],
    thread_metadata: Annotated[dict, Depends(get_thread_metadata)],
    research_graph: Annotated[object, Depends(get_research_graph)],
    research_threads: Annotated[set, Depends(get_research_threads)],
    research_metadata: Annotated[dict, Depends(get_research_metadata)],
) -> ChatResponse:
    """Interpret a natural-language message and execute any required actions autonomously."""
    session_id = req.session_id or str(uuid.uuid4())
    history: list[dict] = sessions.setdefault(session_id, [])

    # Extract staged paper IDs and canvas summary from context
    ctx = req.context or {}
    staged_paper_ids: list[str] = ctx.get("staged_paper_ids", [])
    canvas_summary: str = ctx.get("canvas_summary", "")

    user_content = req.message
    if ctx:
        # Only append non-internal context keys to the user message
        display_ctx = {k: v for k, v in ctx.items() if k not in ("staged_paper_ids", "canvas_summary")}
        if display_ctx:
            user_content += f"\n\n[Context: {json.dumps(display_ctx)}]"
    history.append({"role": "user", "content": user_content})

    # Load staged papers and build system prompt (fail-safe: fall back to no grounding)
    try:
        staged_papers = await asyncio.to_thread(_load_staged_papers, staged_paper_ids)
    except Exception as exc:
        logger.warning("Failed to load staged papers, proceeding without grounding: %s", exc)
        staged_papers = []
    system_prompt = _build_system(staged_papers, canvas_summary)

    # Perplexity web-grounded fallback when no papers are staged
    if not staged_papers:
        perplexity_context = await _get_perplexity_context(req.message)
        if perplexity_context:
            system_prompt += (
                f"\n\n── WEB CONTEXT (from Perplexity, treat as background) ──\n{perplexity_context}"
            )

    # Call the LLM
    try:
        llm_resp = await asyncio.to_thread(
            primary.complete,
            system=system_prompt,
            messages=list(history),
            max_tokens=1024,
            temperature=0.3,
        )
        raw = llm_resp.content.strip()
    except Exception as exc:
        logger.error("Chat LLM call failed: %s", exc)
        raise HTTPException(status_code=503, detail="LLM unavailable — try again shortly.")

    # Parse structured JSON
    try:
        parsed = json.loads(raw)
        reply: str = parsed.get("reply", raw)
        action = parsed.get("action")
        thinking: str | None = parsed.get("thinking") or None
        sources: list[str] = parsed.get("sources", [])
    except json.JSONDecodeError:
        reply = raw
        action = None
        thinking = None
        sources = []

    # Execute action
    canvas_items: list[CanvasItem] = []

    if isinstance(action, dict):
        action_type: str = action.get("type", "")
        payload: dict = action.get("payload", {})

        if action_type in _READ_ACTIONS:
            extra, items = await asyncio.to_thread(_execute_read_action, action_type, payload)
            canvas_items.extend(items)

            # Research trigger: empty concept search → start structured research job
            if action_type == "search_concepts" and _EMPTY_SENTINEL in extra:
                sentinel_match = re.search(
                    rf"{re.escape(_EMPTY_SENTINEL)}(.+?){re.escape(_EMPTY_SENTINEL)}", extra
                )
                query = sentinel_match.group(1) if sentinel_match else payload.get("query", "")
                research_extra, research_items = await _start_research_job(
                    query, research_graph, research_threads, research_metadata
                )
                extra = research_extra
                canvas_items.extend(research_items)

            reply = reply + extra

        elif action_type == "ingest_paper":
            extra, items = await _execute_ingest(
                payload.get("arxiv_id", ""), ingestion_graph, running_threads, thread_metadata
            )
            canvas_items.extend(items)
            reply = reply + extra

        elif action_type == "create_discovery":
            extra = await _execute_discovery(
                payload, discovery_graph, running_threads, thread_metadata
            )
            reply = reply + extra

    # Store assistant turn and trim rolling window
    history.append({"role": "assistant", "content": reply})
    if len(history) > _MAX_HISTORY_TURNS:
        del history[:-_MAX_HISTORY_TURNS]

    return ChatResponse(
        reply=reply,
        session_id=session_id,
        canvas_items=canvas_items,
        thinking=thinking,
        sources=sources,
    )


# ---------------------------------------------------------------------------
# Streaming (Vercel AI SDK data stream protocol)
# ---------------------------------------------------------------------------

# Chunk size for streaming reply text (simulated token stream)
_STREAM_CHUNK_SIZE = 24


def _sse_line(data: str) -> bytes:
    """One SSE line: data: <payload>."""
    return f"data: {data}\n\n".encode("utf-8")


async def _chat_stream_generator(
    session_id: str,
    reply: str,
    thinking: str | None,
    sources: list[str],
    canvas_items: list[CanvasItem],
    message_id: str,
    reasoning_id: str,
    text_id: str,
):
    """Yield SSE lines for the Vercel AI SDK data stream protocol."""
    yield _sse_line(json.dumps({"type": "start", "messageId": message_id}))

    if thinking:
        yield _sse_line(json.dumps({"type": "reasoning-start", "id": reasoning_id}))
        # Stream thinking in chunks
        for i in range(0, len(thinking), _STREAM_CHUNK_SIZE):
            chunk = thinking[i : i + _STREAM_CHUNK_SIZE]
            yield _sse_line(
                json.dumps({"type": "reasoning-delta", "id": reasoning_id, "delta": chunk})
            )
        yield _sse_line(json.dumps({"type": "reasoning-end", "id": reasoning_id}))

    yield _sse_line(json.dumps({"type": "text-start", "id": text_id}))
    for i in range(0, len(reply), _STREAM_CHUNK_SIZE):
        chunk = reply[i : i + _STREAM_CHUNK_SIZE]
        yield _sse_line(
            json.dumps({"type": "text-delta", "id": text_id, "delta": chunk})
        )
    yield _sse_line(json.dumps({"type": "text-end", "id": text_id}))

    # HEAVEN metadata (session_id, sources, canvas_items) for the client
    yield _sse_line(
        json.dumps(
            {
                "type": "data-heaven",
                "data": {
                    "session_id": session_id,
                    "sources": sources,
                    "canvas_items": [c.model_dump() for c in canvas_items],
                },
            }
        )
    )
    yield _sse_line(json.dumps({"type": "finish"}))
    yield _sse_line("[DONE]")


@router.post("/stream")
async def chat_stream(
    req: ChatStreamRequest,
    sessions: Annotated[dict, Depends(get_sessions)],
    ingestion_graph: Annotated[object, Depends(get_ingestion_graph)],
    discovery_graph: Annotated[object, Depends(get_discovery_graph)],
    running_threads: Annotated[set, Depends(get_running_threads)],
    thread_metadata: Annotated[dict, Depends(get_thread_metadata)],
    research_graph: Annotated[object, Depends(get_research_graph)],
    research_threads: Annotated[set, Depends(get_research_threads)],
    research_metadata: Annotated[dict, Depends(get_research_metadata)],
):
    """Stream chat response using Vercel AI SDK data stream protocol (SSE)."""
    ctx = req.context or {}
    staged_paper_ids: list[str] = ctx.get("staged_paper_ids", [])
    canvas_summary: str = ctx.get("canvas_summary", "")

    if req.messages:
        # useChat sends full messages array; use as history, last message is the new user input
        history = [{"role": m.role, "content": m.content} for m in req.messages]
        if not history or history[-1]["role"] != "user":
            raise HTTPException(status_code=400, detail="messages must end with a user message")
        user_content = history[-1]["content"]
        session_id = req.session_id or str(uuid.uuid4())
        # Append context to the user message for this turn only (already in content from client)
    else:
        if not req.message:
            raise HTTPException(status_code=400, detail="message or messages required")
        session_id = req.session_id or str(uuid.uuid4())
        history = sessions.setdefault(session_id, [])
        user_content = req.message
        if ctx:
            display_ctx = {k: v for k, v in ctx.items() if k not in ("staged_paper_ids", "canvas_summary")}
            if display_ctx:
                user_content += f"\n\n[Context: {json.dumps(display_ctx)}]"
        history.append({"role": "user", "content": user_content})

    try:
        staged_papers = await asyncio.to_thread(_load_staged_papers, staged_paper_ids)
    except Exception as exc:
        logger.warning("Failed to load staged papers, proceeding without grounding: %s", exc)
        staged_papers = []
    system_prompt = _build_system(staged_papers, canvas_summary)

    if not staged_papers:
        perplexity_context = await _get_perplexity_context(req.message)
        if perplexity_context:
            system_prompt += (
                f"\n\n── WEB CONTEXT (from Perplexity, treat as background) ──\n{perplexity_context}"
            )

    try:
        llm_resp = await asyncio.to_thread(
            primary.complete,
            system=system_prompt,
            messages=list(history),
            max_tokens=1024,
            temperature=0.3,
        )
        raw = llm_resp.content.strip()
    except Exception as exc:
        logger.error("Chat stream LLM call failed: %s", exc)
        raise HTTPException(status_code=503, detail="LLM unavailable — try again shortly.")

    try:
        parsed = json.loads(raw)
        reply: str = parsed.get("reply", raw)
        action = parsed.get("action")
        thinking = parsed.get("thinking") or None
        sources: list[str] = parsed.get("sources", [])
    except json.JSONDecodeError:
        reply = raw
        action = None
        thinking = None
        sources = []

    canvas_items: list[CanvasItem] = []
    if isinstance(action, dict):
        action_type = action.get("type", "")
        payload = action.get("payload", {})

        if action_type in _READ_ACTIONS:
            extra, items = await asyncio.to_thread(_execute_read_action, action_type, payload)
            canvas_items.extend(items)
            if action_type == "search_concepts" and _EMPTY_SENTINEL in extra:
                sentinel_match = re.search(
                    rf"{re.escape(_EMPTY_SENTINEL)}(.+?){re.escape(_EMPTY_SENTINEL)}", extra
                )
                query = sentinel_match.group(1) if sentinel_match else payload.get("query", "")
                research_extra, research_items = await _start_research_job(
                    query, research_graph, research_threads, research_metadata
                )
                extra = research_extra
                canvas_items.extend(research_items)
            reply = reply + extra
        elif action_type == "ingest_paper":
            extra, items = await _execute_ingest(
                payload.get("arxiv_id", ""), ingestion_graph, running_threads, thread_metadata
            )
            canvas_items.extend(items)
            reply = reply + extra
        elif action_type == "create_discovery":
            extra = await _execute_discovery(
                payload, discovery_graph, running_threads, thread_metadata
            )
            reply = reply + extra

    history.append({"role": "assistant", "content": reply})
    if len(history) > _MAX_HISTORY_TURNS:
        del history[:-_MAX_HISTORY_TURNS]
    sessions[session_id] = history

    message_id = f"msg_{uuid.uuid4().hex}"
    reasoning_id = f"reasoning_{uuid.uuid4().hex}"
    text_id = f"text_{uuid.uuid4().hex}"

    return StreamingResponse(
        _chat_stream_generator(
            session_id, reply, thinking, sources, canvas_items,
            message_id, reasoning_id, text_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "x-vercel-ai-ui-message-stream": "v1",
        },
    )
