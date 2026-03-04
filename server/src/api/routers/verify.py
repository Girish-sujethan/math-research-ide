"""Verify router — proactive nudges and editor intelligence (parity, formalize, correlate, live-check)."""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import APIRouter

from src.api.schemas import (
    NudgeItem, NudgeRequest, NudgeResult,
    ParityRequest, ParityResult, ParityCheckItem,
    FormalizeRequest, FormalizeResult,
    CorrelateRequest, CorrelateResult, CorrelationItem,
    LiveCheckRequest, LiveCheckResult, LiveCheckItem,
)
from src.db.chroma import collections
from src.db.sqlite.models import Paper
from src.db.sqlite.session import get_session
from src.model.formalization.formalizer import formalize
from src.model.providers.registry import cheap, primary
from src.verification.sympy_check import (
    check_equality, check_latex_expression, _is_complex_expression,
)

router = APIRouter(prefix="/verify", tags=["verify"])
logger = logging.getLogger(__name__)

_NUDGE_PROMPT = """\
You are a mathematical research assistant. Given the following document blocks and staged paper excerpts,
generate 1-2 insightful synthesis nudges. Each nudge should either:
- Suggest an expansion ("expansion"): point to a relevant theorem or formula from the staged papers
  that could strengthen the current document
- Note a potential contradiction ("warning"): flag where document content may conflict with a staged paper

Respond with valid JSON only:
{"nudges": [{"type": "expansion"|"warning", "message": "...", "source_paper_id": "..."}]}

Keep messages concise (under 100 chars). Only return nudges if genuinely useful.
"""


@router.post("/nudge", response_model=NudgeResult)
def get_nudges(req: NudgeRequest) -> NudgeResult:
    """Scan document blocks against staged papers and return proactive nudges."""
    nudges: list[NudgeItem] = []

    if not req.staged_paper_ids:
        return NudgeResult(nudges=[])

    # Load paper titles for display
    paper_titles: dict[str, str] = {}
    with get_session() as session:
        for pid in req.staged_paper_ids:
            paper = session.get(Paper, pid)
            if paper:
                paper_titles[pid] = paper.title

    # Semantic similarity nudges per block
    for block_idx, block in enumerate(req.blocks):
        content: str = block.get("content", "")
        if len(content) < 20:
            continue

        try:
            res = collections.query_concepts(content, n_results=3)
        except Exception as exc:
            logger.warning("Nudge query failed for block %d: %s", block_idx, exc)
            continue

        ids = res.get("ids", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        distances = res.get("distances", [[]])[0]

        for cid, meta, dist in zip(ids, metas, distances):
            source_paper_id = meta.get("source_paper_id") or meta.get("paper_id")
            if source_paper_id not in req.staged_paper_ids:
                continue

            concept_name = meta.get("name", "a concept")
            source_title = paper_titles.get(source_paper_id, "staged paper")

            if dist < 0.15:
                # Very close match — check for LaTeX differences (potential warning)
                block_has_latex = "$" in content
                concept_latex = meta.get("latex_statement", "")
                if block_has_latex and concept_latex and concept_latex not in content:
                    nudges.append(NudgeItem(
                        type="warning",
                        message=f"LaTeX may differ from '{concept_name}' in {source_title[:40]}",
                        source_paper_id=source_paper_id,
                        source_paper_title=source_title,
                        block_index=block_idx,
                        distance=round(dist, 3),
                    ))
            elif dist < 0.2:
                # Close match — connection nudge
                nudges.append(NudgeItem(
                    type="connection",
                    message=f"Related to '{concept_name}' in {source_title[:40]}",
                    source_paper_id=source_paper_id,
                    source_paper_title=source_title,
                    block_index=block_idx,
                    distance=round(dist, 3),
                ))

    # Deduplicate (keep first of same message prefix)
    seen: set[str] = set()
    deduped: list[NudgeItem] = []
    for n in nudges:
        key = n.message[:40]
        if key not in seen:
            seen.add(key)
            deduped.append(n)

    # LLM-generated expansion nudges (up to 2, only if we have staged papers)
    if req.staged_paper_ids and req.blocks:
        try:
            doc_summary = "\n".join(
                f"[{b.get('type','text')}] {b.get('content','')[:200]}"
                for b in req.blocks
                if len(b.get("content", "")) >= 20
            )[:1000]

            paper_excerpts: list[str] = []
            with get_session() as session:
                for pid in req.staged_paper_ids[:3]:
                    paper = session.get(Paper, pid)
                    if paper and paper.abstract:
                        paper_excerpts.append(
                            f"[{pid}] {paper.title}: {paper.abstract[:300]}"
                        )

            if doc_summary and paper_excerpts:
                prompt = (
                    f"Document blocks:\n{doc_summary}\n\n"
                    f"Staged papers:\n" + "\n".join(paper_excerpts)
                )
                llm_resp = cheap.complete(
                    system=_NUDGE_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=256,
                    temperature=0.3,
                )
                parsed = json.loads(llm_resp.content.strip())
                for n in parsed.get("nudges", []):
                    nudge_type = n.get("type", "expansion")
                    message = n.get("message", "")
                    spid = n.get("source_paper_id")
                    if message:
                        deduped.append(NudgeItem(
                            type=nudge_type,
                            message=message,
                            source_paper_id=spid,
                            source_paper_title=paper_titles.get(spid, "") if spid else None,
                        ))
        except Exception as exc:
            logger.warning("LLM nudge generation failed: %s", exc)

    return NudgeResult(nudges=deduped[:5])


@router.post("/parity", response_model=ParityResult)
def check_parity(req: ParityRequest) -> ParityResult:
    """Scan LaTeX source for equations and verify them symbolically via SymPy."""
    results: list[ParityCheckItem] = []
    source = req.source

    def _process_expr(expr: str, start_char: int, end_char: int) -> None:
        # Skip expressions containing constructs SymPy can't quickly evaluate
        # (integrals, infinite sums, limits, etc.) — avoids server hangs.
        if _is_complex_expression(expr):
            results.append(ParityCheckItem(
                start_char=start_char, end_char=end_char,
                expression=expr, status="skip",
                output="Skipped — expression too complex for fast symbolic check.",
            ))
            return

        if "=" in expr:
            parts = expr.split("=", 1)
            lhs, rhs = parts[0].strip(), parts[1].strip()
            try:
                r = check_equality(lhs, rhs)
                status = "verified" if r.passed else "failed"
                results.append(ParityCheckItem(
                    start_char=start_char, end_char=end_char,
                    expression=expr, lhs=lhs, rhs=rhs,
                    status=status, output=r.output,
                    simplified_form=r.simplified_form,
                ))
            except Exception as exc:
                results.append(ParityCheckItem(
                    start_char=start_char, end_char=end_char,
                    expression=expr, lhs=lhs, rhs=rhs,
                    status="invalid", output=str(exc),
                ))
        else:
            try:
                r = check_latex_expression(expr)
            except Exception:
                r = None  # type: ignore[assignment]
            results.append(ParityCheckItem(
                start_char=start_char, end_char=end_char,
                expression=expr, status="skip",
                output=r.output if r else "parse error",
                simplified_form=r.simplified_form if r else None,
            ))

    for m in re.finditer(r'\$\$([\s\S]*?)\$\$', source):
        _process_expr(m.group(1).strip(), m.start(), m.end())

    for m in re.finditer(r'\\begin\{equation\*?\}([\s\S]*?)\\end\{equation\*?\}', source):
        _process_expr(m.group(1).strip(), m.start(), m.end())

    # Sort by start_char so the client's RangeSetBuilder receives them in ascending order
    results.sort(key=lambda r: r.start_char)
    return ParityResult(results=results)


@router.post("/formalize", response_model=FormalizeResult)
def formalize_statement(req: FormalizeRequest) -> FormalizeResult:
    """Formalize a LaTeX theorem/lemma/definition statement into Lean 4."""
    try:
        result = formalize(req.statement, req.concept_name, primary)
        success = (
            result.lean_source is not None
            and not result.lean_source.startswith("-- Error")
            and result.success
        )
        return FormalizeResult(
            success=success,
            lean_source=result.lean_source,
            attempts=result.attempts,
        )
    except Exception as exc:
        return FormalizeResult(success=False, attempts=0, error=str(exc))


@router.post("/correlate", response_model=CorrelateResult)
def get_correlations(req: CorrelateRequest) -> CorrelateResult:
    """Find concept correlations for document paragraphs against staged papers."""
    correlations: list[CorrelationItem] = []

    for para_idx, para in enumerate(req.paragraphs):
        if len(para.text.strip()) < 30:
            continue
        try:
            res = collections.query_concepts(para.text, n_results=12)
        except Exception as exc:
            logger.warning("Correlation query failed for para %d: %s", para_idx, exc)
            continue

        ids = res.get("ids", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        distances = res.get("distances", [[]])[0]

        for cid, meta, dist in zip(ids, metas, distances):
            source_paper_id = meta.get("source_paper_id") or meta.get("paper_id") or ""
            if source_paper_id not in req.staged_paper_ids:
                continue
            if dist >= 0.5:
                continue
            correlations.append(CorrelationItem(
                para_index=para_idx,
                start_char=para.start_char,
                end_char=para.end_char,
                concept_id=cid,
                concept_name=meta.get("name", "unknown"),
                concept_type=meta.get("concept_type", "unknown"),
                distance=round(dist, 4),
                paper_id=source_paper_id,
                paper_title=meta.get("paper_title") or meta.get("title") or "",
            ))

    return CorrelateResult(correlations=correlations)


# ---------------------------------------------------------------------------
# Live verification — multi-tier pipeline (all synchronous, no Lean)
#   Tier 1: SymPy (fast, local, deterministic) — equations
#   Tier 2: Wolfram Alpha (remote, deterministic) — fallback for complex eqs
#   Tier 3: LLM (fast, non-deterministic) — theorems & statements SymPy can't handle
#   Tier 4: CrossRef (staged paper semantic match)
# ---------------------------------------------------------------------------

_VERIFY_PROMPT = """\
You are a rigorous mathematical fact-checker. Assess whether the given mathematical \
content (theorem, definition, remark, or prose with math) is correct and consistent \
with established mathematics.

Rules:
- Respond with ONLY valid JSON: {"verdict": "correct"|"incorrect"|"uncertain", "reason": "..."}
- "correct" = the content is a standard, correct mathematical fact or definition
- "incorrect" = the content contains a clear mathematical error or false claim
- "uncertain" = you cannot determine correctness with high confidence
- Keep "reason" under 120 characters
- Be conservative: if unsure, say "uncertain"
- Do NOT attempt to prove; only assess truthfulness against established mathematics.
"""


def _wolfram_verify_expression(expr: str) -> LiveCheckItem | None:
    """Try to verify an equation via Wolfram Alpha. Returns None if unavailable."""
    try:
        from src.ingestion.wolfram_client import query as wolfram_query
        from src.config import settings
        if not settings.wolfram_app_id:
            return None

        wolfram_input = expr
        if "=" in expr:
            wolfram_input = f"simplify {expr}"

        result = wolfram_query(wolfram_input)
        if result is None:
            return None

        text = result.plaintext.lower()
        if "true" in text or "yes" in text or "0" in text:
            return LiveCheckItem(
                start_char=0, end_char=0, expression=expr,
                status="verified", tier="wolfram",
                output=result.plaintext[:200],
            )
        elif "false" in text or "no" in text:
            return LiveCheckItem(
                start_char=0, end_char=0, expression=expr,
                status="failed", tier="wolfram",
                output=result.plaintext[:200],
            )
        return LiveCheckItem(
            start_char=0, end_char=0, expression=expr,
            status="verified", tier="wolfram",
            output=result.plaintext[:200],
        )
    except Exception as e:
        logger.debug("Wolfram verification failed for %s: %s", expr[:40], e)
        return None


def _check_equation(expr: str, start: int, end: int) -> LiveCheckItem:
    """Check a single equation expression via SymPy, falling back to Wolfram, then LLM."""
    if _is_complex_expression(expr):
        wolfram_result = _wolfram_verify_expression(expr)
        if wolfram_result:
            wolfram_result.start_char = start
            wolfram_result.end_char = end
            return wolfram_result
        return _llm_verify_statement(expr, start, end)

    if "=" in expr:
        parts = expr.split("=", 1)
        lhs, rhs = parts[0].strip(), parts[1].strip()
        try:
            r = check_equality(lhs, rhs)
            if r.passed:
                return LiveCheckItem(
                    start_char=start, end_char=end,
                    expression=expr, status="verified", tier="sympy",
                    output=r.output, simplified_form=r.simplified_form,
                )
            wolfram_result = _wolfram_verify_expression(expr)
            if wolfram_result and wolfram_result.status == "verified":
                wolfram_result.start_char = start
                wolfram_result.end_char = end
                return wolfram_result
            return LiveCheckItem(
                start_char=start, end_char=end,
                expression=expr, status="failed", tier="sympy",
                output=r.output, simplified_form=r.simplified_form,
            )
        except Exception:
            return _llm_verify_statement(expr, start, end)

    try:
        r = check_latex_expression(expr)
        return LiveCheckItem(
            start_char=start, end_char=end,
            expression=expr, status="verified" if r.passed else "failed",
            tier="sympy", output=r.output,
            simplified_form=r.simplified_form,
        )
    except Exception:
        return _llm_verify_statement(expr, start, end)


def _llm_verify_statement(statement: str, start: int, end: int) -> LiveCheckItem:
    """Use the LLM to assess mathematical correctness when symbolic tools can't."""
    try:
        resp = cheap.complete(
            system=_VERIFY_PROMPT,
            messages=[{"role": "user", "content": f"Verify this mathematical statement:\n\n{statement[:500]}"}],
            max_tokens=200,
            temperature=0.0,
        )
        parsed = json.loads(resp.content.strip())
        verdict = parsed.get("verdict", "uncertain")
        reason = parsed.get("reason", "")

        status_map = {"correct": "verified", "incorrect": "failed", "uncertain": "skipped"}
        return LiveCheckItem(
            start_char=start, end_char=end,
            expression=statement[:100],
            status=status_map.get(verdict, "skipped"),
            tier="llm",
            output=reason[:200] if reason else f"LLM verdict: {verdict}",
        )
    except Exception as exc:
        logger.debug("LLM verification failed: %s", exc)
        return LiveCheckItem(
            start_char=start, end_char=end,
            expression=statement[:100], status="skipped", tier="llm",
            output="LLM verification unavailable.",
        )


def _check_theorem(statement: str, start: int, end: int) -> LiveCheckItem:
    """Verify a theorem/lemma/proposition via SymPy (extract equations) then LLM fallback."""
    # Try to extract equations from the theorem body for symbolic checking
    equations = re.findall(r'\$([^$]+)\$', statement)
    equations += re.findall(r'\\\((.+?)\\\)', statement)

    sympy_results: list[bool] = []
    for eq in equations:
        eq = eq.strip()
        if "=" in eq and not _is_complex_expression(eq):
            parts = eq.split("=", 1)
            try:
                r = check_equality(parts[0].strip(), parts[1].strip())
                sympy_results.append(r.passed)
            except Exception:
                pass

    if sympy_results:
        all_pass = all(sympy_results)
        if all_pass:
            return LiveCheckItem(
                start_char=start, end_char=end,
                expression=statement[:100], status="verified", tier="sympy",
                output=f"All {len(sympy_results)} embedded equation(s) verified symbolically.",
            )
        else:
            failed = sum(1 for x in sympy_results if not x)
            return LiveCheckItem(
                start_char=start, end_char=end,
                expression=statement[:100], status="failed", tier="sympy",
                output=f"{failed}/{len(sympy_results)} embedded equation(s) failed symbolic check.",
            )

    # No extractable equations — use LLM verification
    return _llm_verify_statement(statement, start, end)


def _crossref_paragraphs(
    source: str,
    staged_paper_ids: list[str],
    checked_ranges: set[tuple[int, int]],
) -> list[LiveCheckItem]:
    """Cross-reference prose paragraphs against staged papers via ChromaDB."""
    results: list[LiveCheckItem] = []
    if not staged_paper_ids:
        return results

    paper_titles: dict[str, str] = {}
    with get_session() as session:
        for pid in staged_paper_ids:
            paper = session.get(Paper, pid)
            if paper:
                paper_titles[pid] = paper.title

    pos = 0
    for chunk in source.split("\n\n"):
        stripped = chunk.strip()
        chunk_start = source.find(chunk, pos)
        if chunk_start < 0:
            chunk_start = pos
        chunk_end = chunk_start + len(chunk)
        pos = chunk_end + 2

        if len(stripped) < 40:
            continue
        if (chunk_start, chunk_end) in checked_ranges:
            continue
        if stripped.startswith("\\documentclass") or stripped.startswith("\\usepackage"):
            continue
        text_portion = re.sub(r'\\[a-zA-Z]+(?:\{[^}]*\})?', ' ', stripped).strip()
        if len(text_portion) < 30:
            continue

        try:
            res = collections.query_concepts(text_portion, n_results=3)
        except Exception:
            continue

        ids = res.get("ids", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        distances = res.get("distances", [[]])[0]

        for cid, meta, dist in zip(ids, metas, distances):
            source_paper_id = meta.get("source_paper_id") or meta.get("paper_id") or ""
            if source_paper_id not in staged_paper_ids:
                continue
            if dist >= 0.25:
                continue
            ptitle = paper_titles.get(source_paper_id, "")
            if not ptitle:
                ptitle = meta.get("paper_title") or meta.get("title") or ""
            concept_name = meta.get("name", "")
            results.append(LiveCheckItem(
                start_char=chunk_start, end_char=chunk_end,
                expression=concept_name[:80],
                status="verified", tier="crossref",
                output=f"Supported by concept '{concept_name}' in staged paper",
                paper_title=ptitle,
            ))
            break

    return results


@router.post("/live-check", response_model=LiveCheckResult)
def live_check(req: LiveCheckRequest) -> LiveCheckResult:
    """Verify mathematical content in LaTeX source — fully synchronous.

    Tiers (in order of preference):
      1. SymPy — algebraic equations with = signs
      2. Wolfram Alpha — complex expressions SymPy can't handle
      3. LLM — theorems, prose claims, anything symbolic tools skip
      4. CrossRef — semantic match against staged papers
    """
    results: list[LiveCheckItem] = []
    source = req.source
    checked_ranges: set[tuple[int, int]] = set()

    # ── Collect all equations to check ──────────────────────────────────────
    equation_patterns = [
        r'\$\$([\s\S]*?)\$\$',
        r'\\\[([\s\S]*?)\\\]',
        r'\\begin\{equation\*?\}([\s\S]*?)\\end\{equation\*?\}',
        r'\\begin\{align\*?\}([\s\S]*?)\\end\{align\*?\}',
    ]

    eq_tasks: list[tuple[str, int, int]] = []

    for pattern in equation_patterns:
        for m in re.finditer(pattern, source):
            range_key = (m.start(), m.end())
            if range_key in checked_ranges:
                continue
            checked_ranges.add(range_key)

            expr = m.group(1).strip()
            if not expr or len(expr) < 3:
                continue

            if "\\\\" in expr:
                lines = [l.strip().rstrip("\\\\").strip() for l in expr.split("\\\\")]
                lines = [l for l in lines if l and "=" in l]
                if not lines:
                    lines = [expr]
            else:
                lines = [expr]

            for line in lines:
                line = line.replace("&", "").strip()
                if not line:
                    continue
                eq_tasks.append((line, m.start(), m.end()))

    for m in re.finditer(r'(?<!\$)\$(?!\$)((?:[^$\\]|\\.)+)\$(?!\$)', source):
        expr = m.group(1).strip()
        if "=" not in expr or len(expr) < 3:
            continue
        range_key = (m.start(), m.end())
        if range_key in checked_ranges:
            continue
        checked_ranges.add(range_key)
        eq_tasks.append((expr, m.start(), m.end()))

    # ── Theorem / lemma / proposition / corollary / definition / remark ───────
    statement_env_patterns = [
        (r'\\begin\{theorem\}([\s\S]*?)\\end\{theorem\}', "theorem"),
        (r'\\begin\{lemma\}([\s\S]*?)\\end\{lemma\}', "lemma"),
        (r'\\begin\{proposition\}([\s\S]*?)\\end\{proposition\}', "proposition"),
        (r'\\begin\{corollary\}([\s\S]*?)\\end\{corollary\}', "corollary"),
        (r'\\begin\{definition\}([\s\S]*?)\\end\{definition\}', "definition"),
        (r'\\begin\{remark\}([\s\S]*?)\\end\{remark\}', "remark"),
    ]

    stmt_tasks: list[tuple[str, int, int]] = []

    for pattern, _env_type in statement_env_patterns:
        for m in re.finditer(pattern, source):
            statement = m.group(1).strip()
            if not statement or len(statement) < 10:
                continue
            checked_ranges.add((m.start(), m.end()))
            stmt_tasks.append((statement, m.start(), m.end()))

    # ── Prose paragraphs that contain math (verify everything) ───────────────
    # Any substantial paragraph with $...$ or \frac, \sum, \int, etc. gets LLM check
    _MATH_IN_PROSE = re.compile(r'\$[^$]+\$|\\frac\{|\\sum|\\int|\\lim|\\mathbb\{|\\mathcal\{')
    prose_tasks: list[tuple[str, int, int]] = []
    pos = 0
    for chunk in source.split("\n\n"):
        stripped = chunk.strip()
        chunk_start = source.find(chunk, pos)
        if chunk_start < 0:
            chunk_start = pos
        chunk_end = chunk_start + len(chunk)
        pos = chunk_end + 2

        if len(stripped) < 50:
            continue
        if (chunk_start, chunk_end) in checked_ranges:
            continue
        if stripped.startswith("\\documentclass") or stripped.startswith("\\usepackage"):
            continue
        if not _MATH_IN_PROSE.search(stripped):
            continue
        # Skip if it's mostly LaTeX commands (e.g. a figure block)
        text_portion = re.sub(r'\\[a-zA-Z]+(?:\{[^}]*\})?', ' ', stripped).strip()
        if len(text_portion) < 30:
            continue
        checked_ranges.add((chunk_start, chunk_end))
        prose_tasks.append((stripped[:600], chunk_start, chunk_end))

    # Cap prose checks to avoid excessive LLM calls
    prose_tasks = prose_tasks[:15]

    # Run all checks in parallel
    all_tasks: list[tuple[str, str, int, int]] = []
    for expr, start, end in eq_tasks:
        all_tasks.append(("eq", expr, start, end))
    for stmt, start, end in stmt_tasks:
        all_tasks.append(("thm", stmt, start, end))
    for prose, start, end in prose_tasks:
        all_tasks.append(("thm", prose, start, end))

    if all_tasks:
        with ThreadPoolExecutor(max_workers=min(len(all_tasks), 8)) as pool:
            def _dispatch(task: tuple[str, str, int, int]) -> LiveCheckItem:
                kind, text, s, e = task
                if kind == "eq":
                    return _check_equation(text, s, e)
                return _check_theorem(text, s, e)

            futures = {pool.submit(_dispatch, t): t for t in all_tasks}
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:
                    logger.warning("Verification task raised: %s", exc)

    # ── Cross-reference prose with staged papers ────────────────────────────
    if req.staged_paper_ids:
        crossref_results = _crossref_paragraphs(source, req.staged_paper_ids, checked_ranges)
        results.extend(crossref_results)

    results.sort(key=lambda r: r.start_char)
    return LiveCheckResult(results=results, check_id=None)
