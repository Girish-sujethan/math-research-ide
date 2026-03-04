"""Lightweight Agent synthesis — no external search, grounded on staged papers + model knowledge.

Used by the Agent tab: stream REASONING + DOCUMENT_CONTENT (LaTeX) + HEAVEN_NOTE using primary LLM only.
"""

import logging
import re
from typing import Iterator

from src.model.providers.registry import primary as _primary

logger = logging.getLogger(__name__)


def build_agent_prompt(
    query: str,
    staged_papers: list[dict],
    canvas_summary: str,
) -> tuple[str, str]:
    """Build system and user prompts for Agent synthesis (staged papers + canvas only)."""
    system = (
        "You are a mathematical research assistant writing for an academic LaTeX document. "
        "You produce THREE sections in a single response, each starting with its header on its own line.\n\n"
        "REASONING:\n"
        "Think step-by-step about the user's query. Explain:\n"
        "  - What mathematical concepts and theorems are relevant\n"
        "  - Which staged papers (if any) inform the response and how\n"
        "  - How you will structure the content: which \\section{}/\\subsection{} to use, and which key results to present as \\begin{theorem}, \\begin{definition}, \\begin{lemma}, or \\begin{proof}\n"
        "  - Whether a Python visualization or TikZ diagram would help illustrate the concepts "
        "(e.g. plotting a function, phase portrait, convergence behavior, geometric construction). "
        "If yes, describe what you will generate.\n"
        "Keep reasoning concise (3-8 sentences). This is shown to the user live.\n\n"
        "DOCUMENT_CONTENT:\n"
        "Write publication-quality LaTeX that will be inserted directly into a .tex document and must compile. "
        "Output ONLY valid LaTeX — no markdown. Produce substantial, detailed content — do not be terse.\n\n"
        "Structure and length (important):\n"
        "  - Use \\section{} and \\subsection{} to organize. For mathematical topics, use formal environments: \\begin{theorem}...\\end{theorem}, \\begin{definition}...\\end{definition}, \\begin{lemma}...\\end{lemma}, \\begin{proposition}...\\end{proposition}, \\begin{proof}...\\end{proof}, \\begin{remark}...\\end{remark}, \\begin{example}...\\end{example}. Give theorems and definitions clear statements; include proof sketches or full proofs where appropriate.\n"
        "  - Produce substantial content: at least 2-3 sections or subsections, multiple paragraphs of exposition, and at least one or two formal theorem/definition/lemma blocks when the topic involves key results or concepts. Aim for roughly 8-15 paragraphs (or equivalent in structured blocks). Expand on ideas; do not summarize in a few lines.\n\n"
        "LaTeX formatting (strict):\n"
        "  - Headings: \\section{Title} and \\subsection{Title} only. Never use # or ##.\n"
        "  - Inline math: \\( ... \\) or $ ... $. Display math: \\[ ... \\] or $$ ... $$.\n"
        "  - Emphasis: \\textbf{bold}, \\textit{italic}, \\emph{emphasis}. Never use ** or *.\n"
        "  - Lists: \\begin{itemize} \\item ... \\end{itemize} or \\begin{enumerate} \\item ... \\end{enumerate}. Never use - or * for list items.\n"
        "  - Citations: \\cite{key} or plain text like [Paper: Title]. No markdown links.\n"
        "  - Newlines: use blank lines between paragraphs; use \\par or two newlines. No single \\n in the middle of a sentence.\n"
        "  - Special characters: escape # $ % & _ { } with backslash in prose (e.g. \\%); in math mode they are fine.\n"
        "  - Do NOT mention the assistant, HEAVEN, or the AI.\n\n"
        "Mathematics (critical — formulas must typeset correctly):\n"
        "  - Put EVERY equation and formula in math mode. Never write things like ax^2+bx+c=0 or x = 1/(2a) as plain text; they will render as literal characters. Use \\( ax^2+bx+c=0 \\) and \\( x=\\frac{-b\\pm\\sqrt{b^2-4ac}}{2a} \\).\n"
        "  - Fractions: always use \\frac{numerator}{denominator} inside math mode. Wrong: x = {2a} or 1/2. Right: \\( x=\\frac{1}{2a} \\) or \\( \\frac{-b}{2a} \\).\n"
        "  - Roots: square root \\( \\sqrt{x} \\), nth root \\( \\sqrt[n]{x} \\). Wrong: [3]{-q/2}. Right: \\( \\sqrt[3]{-q/2} \\) or \\( \\sqrt[3]{-\\frac{q}{2}} \\).\n"
        "  - Polynomials, variables, and any expression with ^ or _ must be inside \\( ... \\) or \\[ ... \\]. Example: \"the equation \\( x^5 + ax^4 + bx^3 + cx^2 + dx + e = 0 \\)\" not \"the equation x^5+ax^4+...\".\n"
        "  - Example quadratic formula in LaTeX: \\( x = \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a} \\). Example cube root: \\( y = \\sqrt[3]{-\\frac{q}{2}+\\sqrt{\\left(\\frac{q}{2}\\right)^2+\\left(\\frac{p}{3}\\right)^3}} + \\sqrt[3]{-\\frac{q}{2}-\\sqrt{\\left(\\frac{q}{2}\\right)^2+\\left(\\frac{p}{3}\\right)^3}} \\). Use this level of completeness for any formula you write.\n\n"
        "  - For Python visualizations (plots, figures): do NOT use \\begin{verbatim}. "
        "Use the executable block so the system can run the code and embed the plot as an image:\n"
        "    \\begin{heaven_python}\n"
        "    <python code using numpy/matplotlib only>\n"
        "    \\end{heaven_python}\n"
        "    The code will be executed server-side and the generated figure will be inserted in place.\n"
        "  - For TikZ diagrams use:\n"
        "    \\begin{figure}[h]\n"
        "    \\centering\n"
        "    \\begin{tikzpicture}\n"
        "    <tikz code>\n"
        "    \\end{tikzpicture}\n"
        "    \\caption{...}\n"
        "    \\end{figure}\n\n"
        "  - CRITICAL — graph/figure/plot requests: if the user explicitly asks to add, insert, draw, "
        "plot, or visualize a graph, figure, chart, diagram, or any visual, you MUST include a concrete "
        "executable block in your DOCUMENT_CONTENT. Use \\begin{heaven_python}...\\end{heaven_python} "
        "for any plot or data visualization (preferred), or \\begin{figure}[h]...\\begin{tikzpicture}..."
        "\\end{tikzpicture}...\\end{figure} for a geometric or structural diagram. "
        "A prose description of what the figure would look like is NOT acceptable — produce the actual code. "
        "If you are unsure of the exact data or parameters, use representative placeholder values.\n\n"
        "Formatting examples — wrong vs right:\n"
        "  Wrong: # Introduction  |  Right: \\section{Introduction}\n"
        "  Wrong: **important**    |  Right: \\textbf{important}\n"
        "  Wrong: x^2 (outside math) |  Right: \\( x^2 \\) or $x^2$\n"
        "  Wrong: roots x = 1/(2a)  |  Right: roots \\( x = \\frac{1}{2a} \\)\n"
        "  Wrong: y = [3]{-q/2}      |  Right: \\( y = \\sqrt[3]{-\\frac{q}{2}} \\)\n"
        "  Wrong: - item one      |  Right: \\begin{itemize} \\item item one \\end{itemize}\n\n"
        "HEAVEN_NOTE:\n"
        "A short message (1-2 sentences) for the user about what sources were used and what was generated. "
        "Mention if a visualization was included. Reference staged papers by title when relevant.\n\n"
        "IMPORTANT: Always start with REASONING: then DOCUMENT_CONTENT: then HEAVEN_NOTE:. "
        "All three sections are required."
    )

    if not staged_papers:
        context_block = "No papers are currently staged. Use your mathematical knowledge only."
    else:
        lines = ["── STAGED PAPERS (ground your response in these) ──"]
        for p in staged_papers:
            lines.append(f"\n[Paper: {p.get('title', '')}]")
            if p.get("abstract"):
                lines.append(f"Abstract: {p['abstract'][:500]}")
            if p.get("concepts"):
                lines.append("Concepts: " + ", ".join(c.get("name", "") for c in p["concepts"][:8]))
        context_block = "\n".join(lines)

    doc_section = f"\n── CURRENT DOCUMENT ──\n{canvas_summary}" if canvas_summary else ""

    user = (
        f"Research query: {query}\n\n"
        f"{context_block}{doc_section}\n\n"
        "Write your response now. Start with REASONING: on its own line.\n\n"
        "REASONING:\n"
    )
    return system, user


_REASONING_HEADER_RE = re.compile(
    r"^(?:#+ *)?(?:\*\*)?REASONING(?:\*\*)?:?",
    re.IGNORECASE | re.MULTILINE,
)
_DOC_HEADER_RE = re.compile(
    r"^(?:#+ *)?(?:\*\*)?DOCUMENT[_ ]?CONTENT(?:\*\*)?:?",
    re.IGNORECASE | re.MULTILINE,
)
_NOTE_HEADER_RE = re.compile(
    r"^(?:#+ *)?(?:\*\*)?HEAVEN[_ ]?NOTE(?:\*\*)?:?",
    re.IGNORECASE | re.MULTILINE,
)
_DEFAULT_NOTE = "Content generated from staged papers and model knowledge."


def parse_report_and_note(raw: str) -> tuple[str, str, str]:
    """Parse REASONING, DOCUMENT_CONTENT, and HEAVEN_NOTE from model output.

    Returns (reasoning, report, heaven_note).
    """
    reasoning = ""
    report = ""
    heaven_note = _DEFAULT_NOTE

    reasoning_match = _REASONING_HEADER_RE.search(raw)
    doc_match = _DOC_HEADER_RE.search(raw)
    note_match = _NOTE_HEADER_RE.search(raw)

    if reasoning_match and doc_match and reasoning_match.end() < doc_match.start():
        reasoning = raw[reasoning_match.end():doc_match.start()].strip()

    if doc_match and note_match and doc_match.end() < note_match.start():
        report = raw[doc_match.end():note_match.start()].strip()
        heaven_note = raw[note_match.end():].strip() or heaven_note
    elif doc_match:
        after_doc = raw[doc_match.end():]
        note_in_tail = _NOTE_HEADER_RE.search(after_doc)
        if note_in_tail:
            report = after_doc[:note_in_tail.start()].strip()
            heaven_note = after_doc[note_in_tail.end():].strip() or heaven_note
        else:
            report = after_doc.strip()
    elif note_match:
        report = raw[:note_match.start()].strip()
        if reasoning_match:
            report = raw[reasoning_match.end():note_match.start()].strip()
        heaven_note = raw[note_match.end():].strip() or heaven_note

    # Strip any reasoning prefix from report if it leaked through
    if report and reasoning and report.startswith(reasoning[:50]):
        report = report[len(reasoning):].strip()

    # Final fallback: use the whole raw output as document content
    if not report and len(raw.strip()) > 50:
        logger.warning("parse_report_and_note: using full raw output as report (%d chars)", len(raw))
        cleaned = _DOC_HEADER_RE.sub("", raw, count=1).strip()
        cleaned = _REASONING_HEADER_RE.sub("", cleaned, count=1).strip()
        cleaned = _NOTE_HEADER_RE.sub("", cleaned, count=1).strip()
        report = cleaned or raw.strip()

    return reasoning, report, heaven_note


def stream_agent_synthesis(
    query: str,
    staged_papers: list[dict],
    canvas_summary: str,
    max_tokens: int = 8192,
    temperature: float = 0.4,
) -> Iterator[str]:
    """Stream Agent synthesis chunks (no external search). Yields text deltas from the primary LLM."""
    system, user = build_agent_prompt(query, staged_papers, canvas_summary)
    for chunk in _primary.stream_complete(
        system=system,
        messages=[{"role": "user", "content": user}],
        max_tokens=max_tokens,
        temperature=temperature,
    ):
        yield chunk
