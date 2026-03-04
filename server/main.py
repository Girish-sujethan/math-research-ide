"""HEAVEN server entry point.

Run with:
    uv run uvicorn main:app --reload              # development
    uv run uvicorn main:app --workers 1           # production

IMPORTANT — single-worker only:
    The knowledge graph (NetworkX), job registry, and chat sessions all live in
    app.state (in-memory, per-process). Running with multiple workers creates
    independent, diverging copies of this state. Until HEAVEN is migrated to
    LangGraph + persistent state, always use --workers 1.
"""

import uvicorn

from src.api.app import app  # noqa: F401  — imported so uvicorn can find "main:app"

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        workers=1,      # Must stay 1 — see module docstring above
        log_level="info",
    )
