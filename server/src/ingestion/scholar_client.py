"""Semantic Scholar on-demand client.

Uses the Semantic Scholar Academic Graph API (free, no auth required,
higher rate limits with an API key). Preferred over Google Scholar
scraping which is brittle and violates ToS.

Docs: https://api.semanticscholar.org/graph/v1
"""

import httpx
from dataclasses import dataclass
from datetime import datetime

from src.config import settings

_BASE_URL = "https://api.semanticscholar.org/graph/v1"
_FIELDS = "paperId,externalIds,title,abstract,authors,year,publicationDate,fieldsOfStudy,url,openAccessPdf"


@dataclass
class ScholarPaperMeta:
    semantic_scholar_id: str
    arxiv_id: str | None
    doi: str | None
    title: str
    authors: list[str]
    abstract: str | None
    url: str
    pdf_url: str | None
    published_at: datetime | None
    fields_of_study: list[str]


def _headers() -> dict:
    headers = {"Accept": "application/json"}
    if settings.semantic_scholar_api_key:
        headers["x-api-key"] = settings.semantic_scholar_api_key
    return headers


def _parse_paper(data: dict) -> ScholarPaperMeta:
    external_ids = data.get("externalIds") or {}
    pub_date = data.get("publicationDate")
    published_at = datetime.fromisoformat(pub_date) if pub_date else None

    pdf_info = data.get("openAccessPdf")
    pdf_url = pdf_info.get("url") if pdf_info else None

    return ScholarPaperMeta(
        semantic_scholar_id=data["paperId"],
        arxiv_id=external_ids.get("ArXiv"),
        doi=external_ids.get("DOI"),
        title=data.get("title", ""),
        authors=[a["name"] for a in (data.get("authors") or [])],
        abstract=data.get("abstract"),
        url=data.get("url") or f"https://www.semanticscholar.org/paper/{data['paperId']}",
        pdf_url=pdf_url,
        published_at=published_at,
        fields_of_study=data.get("fieldsOfStudy") or [],
    )


def search(query: str, limit: int = 10) -> list[ScholarPaperMeta]:
    """Search Semantic Scholar for papers matching a query."""
    with httpx.Client(headers=_headers(), timeout=30) as client:
        response = client.get(
            f"{_BASE_URL}/paper/search",
            params={"query": query, "limit": limit, "fields": _FIELDS},
        )
        response.raise_for_status()
        data = response.json()

    return [_parse_paper(p) for p in (data.get("data") or [])]


def fetch_by_id(paper_id: str) -> ScholarPaperMeta | None:
    """Fetch a single paper by Semantic Scholar ID or DOI."""
    with httpx.Client(headers=_headers(), timeout=30) as client:
        response = client.get(
            f"{_BASE_URL}/paper/{paper_id}",
            params={"fields": _FIELDS},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
    return _parse_paper(data)
