"""Exa.ai search client for research pipeline.

Uses Exa's HTTP API to search for relevant web content based on a query.
Returns lightweight metadata suitable for synthesis (title, abstract/summary, authors-ish, url).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import httpx

from src.config import settings


EXA_API_URL = "https://api.exa.ai/search"


@dataclass
class ExaResult:
    id: str
    title: str
    url: str
    snippet: str
    author: str | None = None


def is_configured() -> bool:
    return bool(settings.exa_api_key)


def search(query: str, max_results: int = 5) -> List[ExaResult]:
    """Search Exa for relevant pages.

    This uses a compact payload: we ask Exa for text snippets that can stand in for an abstract.
    """
    if not settings.exa_api_key:
        return []

    headers = {
        "Content-Type": "application/json",
        "x-api-key": settings.exa_api_key,
    }
    body = {
        "query": query,
        "num_results": max_results,
        # Prefer semantic search with concise text snippets.
        "type": "neural",
        "use_autoprompt": True,
        "text": True,
    }

    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(EXA_API_URL, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return []

    results: List[ExaResult] = []
    for item in data.get("results", [])[:max_results]:
        results.append(
            ExaResult(
                id=str(item.get("id") or item.get("url") or ""),
                title=item.get("title") or "",
                url=item.get("url") or "",
                snippet=item.get("text") or item.get("snippet") or "",
                author=item.get("author") or None,
            )
        )
    return results
