"""LangGraph checkpointer — SqliteSaver backed by heaven_checkpoints.db."""

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from src.config import settings

# Place the checkpoint DB next to heaven.db
_SERVER_DIR = Path(settings.sqlite_url.removeprefix("sqlite:///")).parent


def get_checkpointer() -> SqliteSaver:
    """Return a SqliteSaver connected to heaven_checkpoints.db.

    Uses ``check_same_thread=False`` so the same connection can be shared
    across the lifespan of the FastAPI app (single-process, I/O-bound).
    """
    db_path = _SERVER_DIR / "heaven_checkpoints.db"
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    return SqliteSaver(conn)
