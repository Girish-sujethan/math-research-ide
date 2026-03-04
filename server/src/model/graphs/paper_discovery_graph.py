"""LangGraph paper discovery pipeline — AI-driven paper search and ranking.

Nodes (linear):
  1. plan_queries    — LLM generates 2-3 targeted sub-queries; sets status="searching_sources"
  2. search_sources  — ThreadPoolExecutor fans out to arXiv + Exa per sub-query;
                       deduplicates by arxiv_id; caps at 20 raw results; status="ranking_papers"
  3. rank_papers     — LLM scores each paper 0-10 + one-sentence explanation;
                       sorts descending, keeps top 10; status="done"

Design notes:
- Runs inside asyncio.to_thread; all node functions are synchronous.
- Exa search is skipped (returns []) when EXA_API_KEY is not set.
- Ranking failure falls back to raw papers with score=0.0.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph

from src.ingestion import arxiv_client, exa_client
from src.model.providers.registry import primary as _primary_default

logger = logging.getLogger(__name__)

_RESULTS_PER_QUERY_PER_SOURCE = 5
_MAX_RAW_RESULTS = 20
_TOP_K = 10


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class PaperDiscoveryState(TypedDict):
    query: str
    job_id: str
    sub_queries: list[str]
    raw_results: list[dict]     # {arxiv_id?, title, authors, abstract, url, source}
    ranked_papers: list[dict]   # same + relevance_score (float), relevance_explanation (str)
    status: str                 # "running"|"searching_sources"|"ranking_papers"|"done"
    error: Optional[str]


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_paper_discovery_graph(checkpointer):
    """Compile and return the paper discovery StateGraph.

    No closure dependencies on app.state — safe to build once at startup.
    """

    # ------------------------------------------------------------------
    # Node 1: plan_queries
    # ------------------------------------------------------------------

    def plan_queries(state: PaperDiscoveryState) -> dict:
        """Use the primary LLM to generate 2-3 targeted sub-queries."""
        query = state["query"]
        prompt = (
            f"Generate 2-3 focused search strings for finding academic papers about: {query}\n"
            "Return ONLY a JSON array of strings — no explanation, no markdown."
        )
        try:
            resp = _primary_default.complete(
                system="You generate targeted academic search queries. Return only valid JSON arrays of strings.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=256,
                temperature=0.2,
            )
            raw = resp.content.strip()
            if raw.startswith("```"):
                raw = "\n".join(raw.splitlines()[1:])
                raw = raw.rsplit("```", 1)[0].strip()
            sub_queries = json.loads(raw)
            if not isinstance(sub_queries, list):
                raise ValueError("Expected a JSON array")
            sub_queries = [str(q) for q in sub_queries[:3] if q]
        except Exception as exc:
            logger.warning(
                "Paper discovery %s: query planning failed (%s) — using original query",
                state["job_id"], exc,
            )
            sub_queries = [query]

        logger.info("Paper discovery %s: planned %d sub-queries", state["job_id"], len(sub_queries))
        return {"sub_queries": sub_queries, "status": "searching_sources"}

    # ------------------------------------------------------------------
    # Node 2: search_sources
    # ------------------------------------------------------------------

    def search_sources(state: PaperDiscoveryState) -> dict:
        """Fan out to arXiv and Exa for each sub-query. Deduplicate results."""
        sub_queries = state["sub_queries"]
        job_id = state["job_id"]
        n = _RESULTS_PER_QUERY_PER_SOURCE

        futures_map: dict = {}
        with ThreadPoolExecutor(max_workers=6) as executor:
            for sq in sub_queries:
                futures_map[executor.submit(arxiv_client.search, sq, n)] = ("arxiv", sq)
                futures_map[executor.submit(exa_client.search, sq, n)] = ("exa", sq)

            raw_results: list[dict] = []
            seen: dict[str, int] = {}   # dedup_key -> index in raw_results

            for future in as_completed(futures_map):
                source, sq = futures_map[future]
                try:
                    papers = future.result()
                except Exception as exc:
                    logger.warning(
                        "Paper discovery %s: %s search failed for %r: %s",
                        job_id, source, sq, exc,
                    )
                    continue

                for p in papers:
                    arxiv_id = getattr(p, "arxiv_id", None) or None
                    title = getattr(p, "title", "") or ""
                    authors = list(getattr(p, "authors", []) or [])
                    abstract = getattr(p, "abstract", "") or ""
                    url = getattr(p, "url", "") or ""

                    dedup_key = arxiv_id if arxiv_id else f"{source}::{title}"
                    entry = {
                        "arxiv_id": arxiv_id,
                        "title": title,
                        "authors": authors,
                        "abstract": abstract,
                        "url": url,
                        "source": source,
                    }

                    if dedup_key in seen:
                        # Prefer arXiv entry when the same paper appears from multiple sources
                        existing = raw_results[seen[dedup_key]]
                        if source == "arxiv" and existing["source"] != "arxiv":
                            raw_results[seen[dedup_key]] = entry
                    else:
                        seen[dedup_key] = len(raw_results)
                        raw_results.append(entry)

        raw_results = raw_results[:_MAX_RAW_RESULTS]
        logger.info("Paper discovery %s: collected %d raw results", job_id, len(raw_results))
        return {"raw_results": raw_results, "status": "ranking_papers"}

    # ------------------------------------------------------------------
    # Node 3: rank_papers
    # ------------------------------------------------------------------

    def rank_papers(state: PaperDiscoveryState) -> dict:
        """Score each paper 0-10 for relevance; sort descending; keep top 10."""
        query = state["query"]
        job_id = state["job_id"]
        papers = state["raw_results"]

        if not papers:
            return {"ranked_papers": [], "status": "done"}

        lines = []
        for i, p in enumerate(papers):
            snippet = (p.get("abstract") or "")[:250]
            lines.append(f'[{i}] "{p["title"]}" ({p["source"]}): {snippet}')
        paper_list = "\n".join(lines)

        prompt = (
            f"Rate each paper's relevance to the query '{query}' on a scale 0-10 "
            "and give a one-sentence explanation.\n\n"
            f"{paper_list}\n\n"
            'Return JSON: [{"index":0,"score":8.5,"explanation":"..."}]'
        )
        try:
            resp = _primary_default.complete(
                system="You rate academic papers for relevance. Return only valid JSON arrays.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                temperature=0.1,
            )
            raw = resp.content.strip()
            if raw.startswith("```"):
                raw = "\n".join(raw.splitlines()[1:])
                raw = raw.rsplit("```", 1)[0].strip()
            scores = json.loads(raw)
            if not isinstance(scores, list):
                raise ValueError("Expected a JSON array")

            score_map = {int(s["index"]): s for s in scores if "index" in s}
            ranked = []
            for i, p in enumerate(papers):
                s = score_map.get(i, {})
                ranked.append({
                    **p,
                    "relevance_score": float(s.get("score", 0.0)),
                    "relevance_explanation": str(s.get("explanation", "Unranked")),
                })
            ranked.sort(key=lambda x: x["relevance_score"], reverse=True)
            ranked = ranked[:_TOP_K]

        except Exception as exc:
            logger.warning(
                "Paper discovery %s: ranking failed (%s) — returning raw papers unranked",
                job_id, exc,
            )
            ranked = [
                {**p, "relevance_score": 0.0, "relevance_explanation": "Unranked"}
                for p in papers[:_TOP_K]
            ]

        logger.info("Paper discovery %s: ranked %d papers", job_id, len(ranked))
        return {"ranked_papers": ranked, "status": "done"}

    # ------------------------------------------------------------------
    # Assemble the graph
    # ------------------------------------------------------------------

    workflow = StateGraph(PaperDiscoveryState)

    workflow.add_node("plan_queries", plan_queries)
    workflow.add_node("search_sources", search_sources)
    workflow.add_node("rank_papers", rank_papers)

    workflow.set_entry_point("plan_queries")
    workflow.add_edge("plan_queries", "search_sources")
    workflow.add_edge("search_sources", "rank_papers")
    workflow.add_edge("rank_papers", END)

    return workflow.compile(checkpointer=checkpointer)
