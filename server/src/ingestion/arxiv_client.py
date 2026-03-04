"""arXiv on-demand client.

Fetches paper metadata and content transiently — nothing is stored except
what the caller explicitly persists (metadata + extracted concepts).
"""

from dataclasses import dataclass
from datetime import datetime

import arxiv


@dataclass
class ArxivPaperMeta:
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    url: str
    pdf_url: str
    published_at: datetime
    msc_codes: list[str]  # populated from categories where possible
    categories: list[str]


def search(
    query: str,
    max_results: int = 10,
    sort_by: arxiv.SortCriterion = arxiv.SortCriterion.Relevance,
) -> list[ArxivPaperMeta]:
    """Search arXiv and return paper metadata. No content stored."""
    client = arxiv.Client()
    search_obj = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=sort_by,
    )
    results = []
    for paper in client.results(search_obj):
        results.append(
            ArxivPaperMeta(
                arxiv_id=paper.get_short_id(),
                title=paper.title,
                authors=[str(a) for a in paper.authors],
                abstract=paper.summary,
                url=paper.entry_id,
                pdf_url=paper.pdf_url,
                published_at=paper.published,
                msc_codes=[],  # arXiv doesn't expose MSC codes directly
                categories=paper.categories,
            )
        )
    return results


def fetch_by_id(arxiv_id: str) -> ArxivPaperMeta | None:
    """Fetch a single paper by arXiv ID."""
    client = arxiv.Client()
    search_obj = arxiv.Search(id_list=[arxiv_id])
    for paper in client.results(search_obj):
        return ArxivPaperMeta(
            arxiv_id=paper.get_short_id(),
            title=paper.title,
            authors=[str(a) for a in paper.authors],
            abstract=paper.summary,
            url=paper.entry_id,
            pdf_url=paper.pdf_url,
            published_at=paper.published,
            msc_codes=[],
            categories=paper.categories,
        )
    return None


def fetch_content_transiently(arxiv_id: str) -> str | None:
    """Fetch the ar5iv HTML for a paper and convert it to LaTeX-friendly plain text.

    ar5iv.org renders arXiv LaTeX papers as HTML.  Math is stored in
    ``<math alttext="...">`` elements.  We extract those alttext values
    (which ARE raw LaTeX) and reconstruct theorem/definition blocks from
    the ar5iv CSS classes so the downstream chunker can find
    ``\\begin{theorem}…\\end{theorem}`` patterns.

    Returns plain text with inline LaTeX ($...$) for transient use.
    """
    import re

    import httpx

    # ar5iv requires the bare ID without a version suffix
    clean_id = re.sub(r"v\d+$", "", arxiv_id)
    url = f"https://ar5iv.org/abs/{clean_id}"
    try:
        response = httpx.get(url, timeout=30, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError:
        return None

    html = response.text

    # 1. Replace <math alttext="LATEX">…</math> with inline $LATEX$
    html = re.sub(
        r"<math\b[^>]*\balttext=\"([^\"]*)\"[^>]*>.*?</math>",
        lambda m: f" ${m.group(1)}$ ",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Self-closing variant
    html = re.sub(
        r"<math\b[^>]*\balttext=\"([^\"]*)\"[^>]*/\s*>",
        lambda m: f" ${m.group(1)}$ ",
        html,
        flags=re.IGNORECASE,
    )

    # 2. Reconstruct LaTeX theorem/definition/… environments from ar5iv CSS classes
    #    ar5iv marks these with class="ltx_theorem ltx_theorem_<envname>"
    def _wrap_env(m: re.Match) -> str:
        env = m.group(1).lower()
        inner = m.group(2)
        return f"\n\n\\begin{{{env}}}\n{inner}\n\\end{{{env}}}\n\n"

    html = re.sub(
        r'class="[^"]*ltx_theorem[^"]*ltx_theorem_(\w+)"[^>]*>(.*?)</(?:div|section|figure)>',
        _wrap_env,
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # 3. Strip all remaining HTML tags
    text = re.sub(r"<[^>]+>", " ", html)

    # 4. Decode common HTML entities
    for entity, char in [
        ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
        ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " "),
    ]:
        text = text.replace(entity, char)

    # 5. Normalise whitespace
    text = re.sub(r"[ \t]{3,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip() or None
