"""Wolfram Alpha on-demand client.

Used for:
- Querying mathematical definitions and properties
- Computational verification of expressions
- Fetching structured results for a math concept or query
"""

import wolframalpha
from dataclasses import dataclass

from src.config import settings


@dataclass
class WolframResult:
    query: str
    plaintext: str          # human-readable result
    pods: list[dict]        # raw structured pods from Wolfram


def query(query_text: str) -> WolframResult | None:
    """Send a query to Wolfram Alpha and return structured results.

    Results are transient — caller decides what to extract and persist.
    """
    if not settings.wolfram_app_id:
        raise RuntimeError("WOLFRAM_APP_ID is not set in .env")

    client = wolframalpha.Client(settings.wolfram_app_id)
    try:
        res = client.query(query_text)
    except Exception:
        return None

    pods = []
    plaintext_parts = []

    for pod in res.pods:
        pod_data = {"title": pod.title, "subpods": []}
        for subpod in pod.subpods:
            text = getattr(subpod, "plaintext", "") or ""
            if text:
                plaintext_parts.append(text)
            pod_data["subpods"].append({"plaintext": text})
        pods.append(pod_data)

    return WolframResult(
        query=query_text,
        plaintext="\n".join(filter(None, plaintext_parts)),
        pods=pods,
    )
