"""FastAPI dependency providers — injected via Depends() into route handlers."""

from fastapi import Request


def get_ingestion_graph(request: Request):
    """Return the compiled ingestion LangGraph from app state."""
    return request.app.state.ingestion_graph


def get_discovery_graph(request: Request):
    """Return the compiled discovery LangGraph from app state."""
    return request.app.state.discovery_graph


def get_running_threads(request: Request) -> set:
    """Return the in-progress thread ID set from app state."""
    return request.app.state.running_threads


def get_thread_metadata(request: Request) -> dict:
    """Return the thread metadata dict from app state."""
    return request.app.state.thread_metadata


def get_sessions(request: Request) -> dict:
    """Return the chat session store from app state."""
    return request.app.state.sessions


def get_research_graph(request: Request):
    """Return the compiled research LangGraph from app state."""
    return request.app.state.research_graph


def get_research_threads(request: Request) -> set:
    """Return the in-progress research thread ID set from app state."""
    return request.app.state.research_threads


def get_research_metadata(request: Request) -> dict:
    """Return the research thread metadata dict from app state."""
    return request.app.state.research_metadata


def get_paper_discovery_graph(request: Request):
    """Return the compiled paper discovery LangGraph from app state."""
    return request.app.state.paper_discovery_graph


def get_paper_discovery_threads(request: Request) -> set:
    """Return the in-progress paper discovery thread ID set from app state."""
    return request.app.state.paper_discovery_threads


def get_paper_discovery_metadata(request: Request) -> dict:
    """Return the paper discovery thread metadata dict from app state."""
    return request.app.state.paper_discovery_metadata
