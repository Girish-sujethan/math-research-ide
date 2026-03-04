"""Tests for /discoveries routes."""

import uuid
from unittest.mock import MagicMock, patch

from src.api.schemas import JobStatus
from src.db.sqlite.models import Discovery
from src.db.sqlite.session import get_session


def _insert_discovery(name: str = "My Discovery") -> str:
    did = str(uuid.uuid4())
    with get_session() as session:
        session.add(Discovery(
            id=did,
            name=name,
            modified_latex_statement=r"x^2 + 1 = 0",
            modification_description="Testing.",
            sympy_check_status="unchecked",
            lean_verification_status="unverified",
        ))
    return did


_DISCOVERY_PAYLOAD = {
    "name": "Generalised RH",
    "base_concept_id": None,
    "modified_latex_statement": r"\forall \chi,\, L(s,\chi)\neq 0",
    "modification_description": "Extend RH to Dirichlet L-functions.",
}


# ---------------------------------------------------------------------------
# Create (async pipeline)
# ---------------------------------------------------------------------------

def test_create_discovery_returns_202(client):
    with patch("src.api.routers.discoveries.asyncio.create_task", side_effect=lambda c: c.close()):
        resp = client.post("/discoveries", json=_DISCOVERY_PAYLOAD)
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "pending"
    assert "job_id" in data


# ---------------------------------------------------------------------------
# Job polling
# ---------------------------------------------------------------------------

def test_discovery_job_not_found(client):
    resp = client.get("/discoveries/jobs/no-such-job")
    assert resp.status_code == 404


def test_discovery_job_pending(client, test_thread_metadata, mock_discovery_graph):
    test_thread_metadata["dj1"] = {}
    mock_discovery_graph.get_state.return_value = None
    resp = client.get("/discoveries/jobs/dj1")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


def test_discovery_job_running(client, test_thread_metadata, test_running_threads):
    test_thread_metadata["dj1"] = {}
    test_running_threads.add("dj1")
    resp = client.get("/discoveries/jobs/dj1")
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


def test_discovery_job_done(client, test_thread_metadata, mock_discovery_graph):
    test_thread_metadata["dj2"] = {}
    snapshot = MagicMock()
    snapshot.values = {
        "discovery_id": "disc-1",
        "sympy_status": "passed",
        "lean_status": "failed",
        "impacts": [{}, {}, {}],
        "conflict_ids": ["c1"],
        "status": "done",
    }
    mock_discovery_graph.get_state.return_value = snapshot
    resp = client.get("/discoveries/jobs/dj2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"
    assert data["discovery_id"] == "disc-1"
    assert data["sympy_status"] == "passed"
    assert data["lean_status"] == "failed"
    assert data["impacts_count"] == 3
    assert data["conflict_count"] == 1


def test_discovery_job_failed(client, test_thread_metadata, mock_discovery_graph):
    test_thread_metadata["dj3"] = {"error": "Lean timeout"}
    snapshot = MagicMock()
    snapshot.values = {"status": "running"}
    mock_discovery_graph.get_state.return_value = snapshot
    resp = client.get("/discoveries/jobs/dj3")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert data["error"] == "Lean timeout"


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------

def test_resume_discovery_job_not_found(client):
    resp = client.post("/discoveries/jobs/no-such-job/resume")
    assert resp.status_code == 404


def test_resume_discovery_job_returns_202(client, test_thread_metadata):
    test_thread_metadata["dj4"] = {}
    with patch(
        "src.api.routers.discoveries.asyncio.create_task", side_effect=lambda c: c.close()
    ):
        resp = client.post("/discoveries/jobs/dj4/resume")
    assert resp.status_code == 202
    assert resp.json()["status"] == "running"


# ---------------------------------------------------------------------------
# List / get
# ---------------------------------------------------------------------------

def test_list_discoveries_filter_by_sympy_status(client):
    _insert_discovery("Passed")
    _insert_discovery("Unchecked")
    resp = client.get("/discoveries?sympy_status=unchecked")
    assert resp.status_code == 200
    assert all(d["sympy_check_status"] == "unchecked" for d in resp.json())


def test_list_discoveries_empty(client):
    resp = client.get("/discoveries")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_discoveries_returns_inserted(client):
    _insert_discovery()
    resp = client.get("/discoveries")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_list_discoveries_filter_by_lean_status(client):
    _insert_discovery("Verified")
    _insert_discovery("Unverified")
    resp = client.get("/discoveries?lean_status=unverified")
    assert resp.status_code == 200
    assert all(d["lean_verification_status"] == "unverified" for d in resp.json())


def test_get_discovery_not_found(client):
    resp = client.get("/discoveries/no-such-id")
    assert resp.status_code == 404


def test_get_discovery_found(client):
    did = _insert_discovery("My Theorem Mod")
    resp = client.get(f"/discoveries/{did}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "My Theorem Mod"


def test_get_discovery_impacts_not_found(client):
    resp = client.get("/discoveries/no-id/impacts")
    assert resp.status_code == 404


def test_get_discovery_impacts_empty(client):
    did = _insert_discovery()
    resp = client.get(f"/discoveries/{did}/impacts")
    assert resp.status_code == 200
    assert resp.json() == []
