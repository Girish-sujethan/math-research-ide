"""Fact-Checker agent.

POST /agents/fact-check

Evaluates a mathematical statement against:
  1. The ChromaDB knowledge base (semantic similarity search).
  2. Any staged research papers (title, abstract, extracted concepts).

Returns a structured verdict: supported | contradicted | uncertain,
a confidence score (0–1), a plain-English explanation, and an optional
suggested correction.
"""

import asyncio
import json
import logging

from fastapi import APIRouter

from src.api.schemas import FactCheckRequest, FactCheckResponse
from src.db.chroma import collections
from src.db.sqlite.models import Concept, Paper
from src.db.sqlite.session import get_session
from src.model.providers.registry import primary

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agents/fact-check", tags=["agents"])

_SYSTEM = """\
You are a rigorous mathematical fact-checker embedded in a research assistant.
Your task is to evaluate the accuracy of a mathematical statement given context
from a knowledge base.

Rules:
- Be strict about mathematical correctness.
- Distinguish clearly between correct statements, incorrect statements, and
  statements that are ambiguous or context-dependent.
- If the knowledge base context is insufficient to make a definitive call,
  return verdict "uncertain" with a lower confidence.

Respond ONLY with valid JSON — no markdown fences, no prose outside the object:
{
  "verdict": "supported" | "contradicted" | "uncertain",
  "confidence": <float 0.0-1.0>,
  "explanation": "<2-4 sentence explanation of the verdict>",
  "supporting_evidence": ["<short evidence point>", ...],
  "issues": ["<specific issue with the statement>", ...],
  "suggestion": "<corrected or improved version of the statement, or null>"
}

Confidence guidelines:
  0.85-1.0  — clearly correct, directly supported by the knowledge base
  0.65-0.85 — likely correct with minor caveats or notation differences
  0.40-0.65 — uncertain; partially supported but significant gaps remain
  0.20-0.40 — likely incorrect; contradicts known results
  0.00-0.20 — clearly wrong or internally contradictory
"""


@router.post("", response_model=FactCheckResponse)
async def fact_check(req: FactCheckRequest) -> FactCheckResponse:
    """Validate a mathematical statement against the knowledge base and staged papers."""
    statement = req.statement.strip()
    if not statement:
        return FactCheckResponse(
            verdict="uncertain",
            confidence=0.0,
            explanation="No statement provided.",
            suggestion=None,
        )

    # ── 1. Semantic search for related concepts ───────────────────────────────
    try:
        concept_ctx = await asyncio.to_thread(
            collections.query_concepts, statement, n_results=6
        )
        related = _format_concepts(concept_ctx)
    except Exception as exc:
        logger.warning("ChromaDB query failed in fact-check: %s", exc)
        related = ""

    # ── 2. Load staged papers ─────────────────────────────────────────────────
    papers_ctx = await asyncio.to_thread(_load_papers, req.staged_paper_ids)

    # ── 3. Build prompt ───────────────────────────────────────────────────────
    parts = [f'Statement to verify:\n"{statement}"']
    if related:
        parts.append(f"\nRelated concepts from the knowledge base:\n{related}")
    if papers_ctx:
        parts.append(f"\nStaged research papers:\n{papers_ctx}")
    if not related and not papers_ctx:
        parts.append(
            "\n(No knowledge base context is available. "
            "Evaluate based on general mathematical correctness only.)"
        )
    prompt = "\n".join(parts)

    # ── 4. LLM call ───────────────────────────────────────────────────────────
    try:
        resp = await asyncio.to_thread(
            primary.complete,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=700,
            temperature=0.1,
        )
        raw = resp.content.strip()
        # Strip markdown fences if the model wraps in ```json ... ```
        if raw.startswith("```"):
            parts2 = raw.split("```")
            raw = parts2[1].lstrip("json").strip() if len(parts2) > 1 else raw
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Fact-check LLM returned non-JSON: %.200s", raw)
        return FactCheckResponse(
            verdict="uncertain",
            confidence=0.5,
            explanation="The fact-check model returned an unexpected response format.",
            suggestion=None,
        )
    except Exception as exc:
        logger.error("Fact-check LLM call failed: %s", exc)
        return FactCheckResponse(
            verdict="uncertain",
            confidence=0.0,
            explanation="Fact-check failed due to an internal error.",
            issues=[str(exc)],
            suggestion=None,
        )

    return FactCheckResponse(
        verdict=parsed.get("verdict", "uncertain"),
        confidence=float(parsed.get("confidence", 0.5)),
        explanation=parsed.get("explanation", ""),
        supporting_evidence=parsed.get("supporting_evidence", []),
        issues=parsed.get("issues", []),
        suggestion=parsed.get("suggestion"),
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _format_concepts(results: dict) -> str:
    ids = results.get("ids", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]
    if not ids:
        return ""
    lines = []
    for cid, meta, dist in zip(ids, metas, dists):
        name = meta.get("name", cid)
        ctype = meta.get("concept_type", "")
        latex = (meta.get("latex_statement") or "")[:200]
        sim = round(1.0 - float(dist), 3)
        lines.append(f"[{ctype}] {name}  (similarity {sim})\n  {latex}")
    return "\n".join(lines)


def _load_papers(paper_ids: list[str]) -> str:
    if not paper_ids:
        return ""
    lines: list[str] = []
    with get_session() as session:
        for pid in paper_ids:
            paper = session.get(Paper, pid)
            if paper is None:
                continue
            lines.append(f"Paper: {paper.title}")
            if paper.abstract:
                lines.append(f"Abstract: {paper.abstract[:500]}")
            concepts = (
                session.query(Concept)
                .filter(Concept.source_paper_id == pid)
                .limit(6)
                .all()
            )
            for c in concepts:
                lines.append(
                    f"  [{c.concept_type}] {c.name}: {(c.latex_statement or '')[:180]}"
                )
    return "\n".join(lines)
