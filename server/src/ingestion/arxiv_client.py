"""arXiv on-demand client.

Fetches paper metadata and content transiently — nothing is stored except
what the caller explicitly persists (metadata + extracted concepts).
"""

import arxiv
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator


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
    """Fetch the ar5iv HTML (structured HTML version of arXiv papers) for a paper.

    Returns raw text content for transient use — caller must not persist full content.
    Uses ar5iv.org which provides structured, LaTeX-parsed HTML.
    """
    import httpx

    url = f"https://ar5iv.org/abs/{arxiv_id}"
    try:
        response = httpx.get(url, timeout=30, follow_redirects=True)
        response.raise_for_status()
        return response.text  # caller extracts concepts, then discards this
    except httpx.HTTPError:
        return None
