"""LangGraph research pipeline — structured multi-step query resolution.

Nodes (linear):
  1. decompose_query         — LLM decomposes query into 3-5 targeted sub-queries
  2. parallel_search         — ChromaDB concept search + arXiv paper search per sub-query
  3. spawn_background_ingest — fire-and-forget threading.Thread ingestion for top 3 new papers
  4. synthesize_research     — LLM composes structured report from concepts + abstracts; status="done"

Design notes:
- Runs inside asyncio.to_thread, so node functions are synchronous.
- spawn_background_ingest uses threading.Thread directly (no event loop access from sync context).
- ingestion_graph, running_threads, thread_metadata are captured via closure in build_research_graph.
"""

import json
import logging
import threading
import uuid
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph

from src.db.chroma import collections
from src.db.sqlite.models import Concept, Paper
from src.db.sqlite.session import get_session
from src.ingestion import arxiv_client
from src.ingestion import exa_client
from src.model.graphs.ingestion_graph import IngestionState
from src.model.providers.registry import primary as _primary_default

logger = logging.getLogger(__name__)

_MAX_CANDIDATE_PAPERS = 5   # arXiv results per sub-query
_MAX_INGEST_NEW = 3         # max new papers to background-ingest
_MAX_CONCEPTS_PER_QUERY = 5 # ChromaDB results per sub-query


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class ResearchState(TypedDict):
    # Inputs
    query: str
    job_id: str
    # Set by decompose_query
    sub_queries: list[str]
    # Set by parallel_search
    existing_concept_ids: list[str]
    existing_concept_names: list[str]
    candidate_papers: list[dict]          # [{arxiv_id, title, abstract, authors}]
    # Set by spawn_background_ingest
    new_paper_ids: list[str]
    new_paper_names: list[str]
    # Set by synthesize_research
    report: str                    # Content for document insertion (no HEAVEN/AI mentions)
    heaven_note: str               # Short message for chat pane (HEAVEN-relevant only)
    canvas_concept_ids: list[str]
    canvas_concept_names: list[str]
    # Terminal
    status: str                           # "running" | "done"
    error: Optional[str]


# ---------------------------------------------------------------------------
# Graph builder (closures capture app-level resources)
# ---------------------------------------------------------------------------

def build_research_graph(checkpointer, ingestion_graph, running_threads: set, thread_metadata: dict):
    """Compile and return the research StateGraph.

    ingestion_graph, running_threads, and thread_metadata are app.state objects shared with
    the papers router — background ingest threads update the same caches.
    """

    # ------------------------------------------------------------------
    # Node 1: decompose_query
    # ------------------------------------------------------------------

    def decompose_query(state: ResearchState) -> dict:
        """Use the primary LLM to break the query into targeted sub-queries."""
        query = state["query"]

        prompt = (
            "You are a mathematical research assistant. "
            "Decompose the following research query into 3 to 5 specific, targeted sub-queries. "
            "Each sub-query should target a distinct aspect of the topic and be phrased to "
            "retrieve relevant mathematical concepts or papers. "
            "Return ONLY a JSON array of strings — no explanation, no markdown.\n\n"
            f"Query: {query}"
        )
        try:
            resp = _primary_default.complete(
                system="You decompose mathematical research queries. Return only valid JSON.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=512,
                temperature=0.2,
            )
            raw = resp.content.strip()
            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = "\n".join(raw.splitlines()[1:])
                raw = raw.rsplit("```", 1)[0].strip()
            sub_queries = json.loads(raw)
            if not isinstance(sub_queries, list):
                raise ValueError("Expected a JSON array")
            sub_queries = [str(q) for q in sub_queries[:5] if q]
        except Exception as exc:
            logger.warning("Query decomposition failed (%s) — using original query", exc)
            sub_queries = [query]

        logger.info("Research %s: decomposed into %d sub-queries", state["job_id"], len(sub_queries))
        return {"sub_queries": sub_queries}

    # ------------------------------------------------------------------
    # Node 2: parallel_search
    # ------------------------------------------------------------------

    def parallel_search(state: ResearchState) -> dict:
        """Search ChromaDB and arXiv for each sub-query. Deduplicate results."""
        sub_queries = state["sub_queries"]
        job_id = state["job_id"]

        seen_concept_ids: set[str] = set()
        concept_ids: list[str] = []
        concept_names: list[str] = []

        candidate_papers: list[dict] = []

        for sq in sub_queries:
            # --- ChromaDB concept search ---
            try:
                res = collections.query_concepts(sq, n_results=_MAX_CONCEPTS_PER_QUERY)
                ids = res.get("ids", [[]])[0]
                metas = res.get("metadatas", [[]])[0]
                for cid, meta in zip(ids, metas):
                    if cid not in seen_concept_ids:
                        seen_concept_ids.add(cid)
                        concept_ids.append(cid)
                        concept_names.append(meta.get("name", cid))
            except Exception as exc:
                logger.warning("Research %s: concept search failed for %r: %s", job_id, sq, exc)

            # --- External paper search (Exa preferred, fallback to arXiv) ---
            used_exa = False
            if exa_client.is_configured():
                try:
                    exa_results = exa_client.search(sq, max_results=_MAX_CANDIDATE_PAPERS)
                    for r in exa_results:
                        if not r.url:
                            continue
                        candidate_papers.append(
                            {
                                "source": "exa",
                                "id": r.id,
                                "title": r.title,
                                "abstract": r.snippet,
                                "authors": [r.author] if r.author else [],
                                "url": r.url,
                            }
                        )
                    used_exa = True
                except Exception as exc:
                    logger.warning("Research %s: Exa search failed for %r: %s", job_id, sq, exc)

            if not used_exa:
                try:
                    papers = arxiv_client.search(sq, max_results=_MAX_CANDIDATE_PAPERS)
                    seen_arxiv_ids: set[str] = set()
                    for p in papers:
                        aid = getattr(p, "arxiv_id", None)
                        if not aid or aid in seen_arxiv_ids:
                            continue
                        seen_arxiv_ids.add(aid)
                        candidate_papers.append(
                            {
                                "source": "arxiv",
                                "arxiv_id": aid,
                                "title": p.title,
                                "abstract": getattr(p, "abstract", "") or "",
                                "authors": list(getattr(p, "authors", []) or []),
                                "url": p.url,
                            }
                        )
                except Exception as exc:
                    logger.warning("Research %s: arXiv search failed for %r: %s", job_id, sq, exc)

        logger.info(
            "Research %s: found %d concepts, %d candidate papers",
            job_id, len(concept_ids), len(candidate_papers),
        )
        return {
            "existing_concept_ids": concept_ids,
            "existing_concept_names": concept_names,
            "candidate_papers": candidate_papers,
        }

    # ------------------------------------------------------------------
    # Node 3: spawn_background_ingest
    # ------------------------------------------------------------------

    def spawn_background_ingest(state: ResearchState) -> dict:
        """Persist and background-ingest the top N new candidate papers.

        Uses threading.Thread directly — this node runs inside asyncio.to_thread so
        asyncio.create_task is not available from this synchronous context.
        """
        job_id = state["job_id"]
        candidates = state["candidate_papers"]
        new_paper_ids: list[str] = []
        new_paper_names: list[str] = []
        ingested = 0

        for paper_data in candidates:
            if ingested >= _MAX_INGEST_NEW:
                break
            arxiv_id = paper_data.get("arxiv_id")
            if not arxiv_id:
                continue

            # Skip already-ingested papers
            with get_session() as session:
                existing = session.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
                if existing is not None:
                    logger.debug("Research %s: paper %s already in DB", job_id, arxiv_id)
                    continue

            # Fetch metadata from arXiv
            try:
                meta = arxiv_client.fetch_by_id(arxiv_id)
            except Exception as exc:
                logger.warning("Research %s: fetch_by_id %s failed: %s", job_id, arxiv_id, exc)
                continue
            if meta is None:
                continue

            paper_id = str(uuid.uuid4())
            try:
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
            except Exception as exc:
                logger.warning("Research %s: could not persist paper %s: %s", job_id, arxiv_id, exc)
                continue

            # Upsert abstract into ChromaDB
            if meta.abstract:
                try:
                    from src.db.chroma import collections as chroma_cols
                    chroma_cols.upsert_paper(
                        paper_id=paper_id,
                        abstract=meta.abstract,
                        metadata={"title": meta.title, "arxiv_id": meta.arxiv_id or ""},
                    )
                except Exception as exc:
                    logger.warning("Research %s: ChromaDB upsert failed for %s: %s", job_id, arxiv_id, exc)

            # Spawn ingestion thread
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

            def _run_ingest(
                _ig=ingestion_graph,
                _state=initial_state,
                _cfg=config,
                _tid=thread_id,
            ):
                running_threads.add(_tid)
                try:
                    _ig.invoke(_state, _cfg)
                except Exception as exc:
                    logger.exception("Research-triggered ingest %s failed: %s", _tid, exc)
                    thread_metadata[_tid]["error"] = str(exc)
                finally:
                    running_threads.discard(_tid)

            t = threading.Thread(target=_run_ingest, daemon=True)
            t.start()

            new_paper_ids.append(paper_id)
            new_paper_names.append(meta.title)
            ingested += 1
            logger.info("Research %s: spawned ingestion for %r (%s)", job_id, meta.title, arxiv_id)

        return {"new_paper_ids": new_paper_ids, "new_paper_names": new_paper_names}

    # ------------------------------------------------------------------
    # Node 4: synthesize_research
    # ------------------------------------------------------------------

    def synthesize_research(state: ResearchState) -> dict:
        """Synthesize a structured research report from existing concepts + paper abstracts."""
        query = state["query"]
        job_id = state["job_id"]
        concept_ids = state["existing_concept_ids"]
        candidate_papers = state["candidate_papers"]

        # Load concept details from SQLite
        concepts_text_parts: list[str] = []
        canvas_concept_ids: list[str] = []
        canvas_concept_names: list[str] = []

        for cid in concept_ids[:10]:
            try:
                with get_session() as session:
                    c = session.get(Concept, cid)
                    if c:
                        canvas_concept_ids.append(cid)
                        canvas_concept_names.append(c.name)
                        concepts_text_parts.append(
                            f"**{c.name}** ({c.concept_type})\n"
                            f"LaTeX: {c.latex_statement}\n"
                            + (f"Description: {c.description}" if c.description else "")
                        )
            except Exception as exc:
                logger.warning("Research %s: could not load concept %s: %s", job_id, cid, exc)

        # Collect paper abstracts (supports Exa and arXiv-backed entries)
        papers_text_parts: list[str] = []
        for p in candidate_papers[:8]:
            abstract = p.get("abstract", "") or ""
            if not abstract:
                continue
            authors_list = p.get("authors") or []
            authors = ", ".join(authors_list[:3])
            papers_text_parts.append(
                f"**{p.get('title', '')}** ({authors})\n{abstract[:600]}\n{p.get('url','')}"
            )

        # Build synthesis prompt: two outputs — document content (for the paper) and HEAVEN note (for chat)
        concepts_block = "\n\n".join(concepts_text_parts) if concepts_text_parts else "None found yet."
        papers_block = "\n\n".join(papers_text_parts) if papers_text_parts else "None found."
        concept_names_list = ", ".join(canvas_concept_names[:10]) if canvas_concept_names else "none"

        system = (
            "You are a mathematical research assistant. You produce two outputs in a single response, "
            "using exactly the section headers below.\n\n"
            "1) DOCUMENT_CONTENT: Content to insert into the user's mathematical document. Write as if for the "
            "paper itself: definitions, proofs, exposition, references to the literature. Do NOT mention the assistant, "
            "HEAVEN, the AI, or the knowledge base. Use LaTeX and markdown as needed.\n\n"
            "2) HEAVEN_NOTE: A short message (1–2 sentences) for the user about what sources were used. Examples: "
            "'Staged papers do not include concepts relevant to this request; used 3 concepts from search.' "
            "'Used concepts X, Y from the knowledge base.' 'No relevant concepts in the knowledge base; response based on paper abstracts.' "
            "Do not repeat the document content; only describe what was used or missing."
        )
        user = (
            f"Research query: {query}\n\n"
            f"## Concepts in knowledge base\n{concepts_block}\n\n"
            f"## Candidate papers found\n{papers_block}\n\n"
            "Reply with exactly these two sections:\n\n"
            "DOCUMENT_CONTENT:\n"
            "<content to insert into the document — mathematics/exposition only, no mention of AI or knowledge base>\n\n"
            "HEAVEN_NOTE:\n"
            "<short message about what HEAVEN used or lacked>"
        )

        try:
            resp = _primary_default.complete(
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=2048,
                temperature=0.4,
            )
            raw = resp.content.strip()
        except Exception as exc:
            logger.error("Research %s: synthesis LLM call failed: %s", job_id, exc)
            raw = (
                f"DOCUMENT_CONTENT:\n(Synthesis failed: {exc})\n\n"
                f"HEAVEN_NOTE:\nKnowledge base had {len(canvas_concept_ids)} concepts; synthesis failed."
            )

        # Parse DOCUMENT_CONTENT and HEAVEN_NOTE
        report = ""
        heaven_note = f"Used concepts: {concept_names_list}." if concept_names_list != "none" else "No relevant concepts in the knowledge base."
        if "DOCUMENT_CONTENT:" in raw and "HEAVEN_NOTE:" in raw:
            try:
                _, rest = raw.split("DOCUMENT_CONTENT:", 1)
                doc_part, note_part = rest.split("HEAVEN_NOTE:", 1)
                report = doc_part.strip()
                heaven_note = note_part.strip() or heaven_note
            except Exception as parse_exc:
                logger.warning("Research %s: failed to parse DOCUMENT_CONTENT/HEAVEN_NOTE: %s", job_id, parse_exc)
                report = raw
        else:
            report = raw

        logger.info("Research %s: synthesis complete (report=%d chars, note=%d chars)", job_id, len(report), len(heaven_note))
        return {
            "report": report,
            "heaven_note": heaven_note,
            "canvas_concept_ids": canvas_concept_ids,
            "canvas_concept_names": canvas_concept_names,
            "status": "done",
        }

    # ------------------------------------------------------------------
    # Assemble the graph
    # ------------------------------------------------------------------

    workflow = StateGraph(ResearchState)

    workflow.add_node("decompose_query", decompose_query)
    workflow.add_node("parallel_search", parallel_search)
    workflow.add_node("spawn_background_ingest", spawn_background_ingest)
    workflow.add_node("synthesize_research", synthesize_research)

    workflow.set_entry_point("decompose_query")
    workflow.add_edge("decompose_query", "parallel_search")
    workflow.add_edge("parallel_search", "spawn_background_ingest")
    workflow.add_edge("spawn_background_ingest", "synthesize_research")
    workflow.add_edge("synthesize_research", END)

    return workflow.compile(checkpointer=checkpointer)
