"""Shared fixtures for API integration tests.

Each test gets:
- An isolated SQLite database in tmp_path (schema pre-created)
- Dependency overrides for ingestion_graph, discovery_graph, running_threads,
  thread_metadata, sessions (in-memory, empty)
- A FastAPI TestClient wired to the real app
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.db.sqlite.session as session_mod
from src.api.app import app
from src.api.dependencies import (
    get_discovery_graph,
    get_ingestion_graph,
    get_running_threads,
    get_sessions,
    get_thread_metadata,
)
from src.db.sqlite.models import Base


@pytest.fixture()
def mock_ingestion_graph():
    graph = MagicMock()
    # Default: get_state returns None → status pending
    graph.get_state.return_value = None
    return graph


@pytest.fixture()
def mock_discovery_graph():
    graph = MagicMock()
    graph.get_state.return_value = None
    return graph


@pytest.fixture()
def test_running_threads():
    return set()


@pytest.fixture()
def test_thread_metadata():
    return {}


@pytest.fixture()
def test_sessions():
    return {}


@pytest.fixture()
def client(
    tmp_path,
    monkeypatch,
    mock_ingestion_graph,
    mock_discovery_graph,
    test_running_threads,
    test_thread_metadata,
    test_sessions,
):
    """TestClient with an isolated SQLite DB and mocked app state."""
    # Redirect SQLite to a temp file so tests never touch heaven.db
    engine = create_engine(
        f"sqlite:///{tmp_path}/test.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(session_mod, "engine", engine)
    monkeypatch.setattr(session_mod, "SessionLocal", TestSession)

    # Override FastAPI Depends() providers
    app.dependency_overrides[get_ingestion_graph] = lambda: mock_ingestion_graph
    app.dependency_overrides[get_discovery_graph] = lambda: mock_discovery_graph
    app.dependency_overrides[get_running_threads] = lambda: test_running_threads
    app.dependency_overrides[get_thread_metadata] = lambda: test_thread_metadata
    app.dependency_overrides[get_sessions] = lambda: test_sessions

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    app.dependency_overrides.clear()
