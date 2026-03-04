"""Tests for /papers routes."""

from datetime import datetime
from unittest.mock import MagicMock, patch

from src.api.schemas import JobStatus
from src.ingestion.arxiv_client import ArxivPaperMeta


def _meta(arxiv_id: str = "2301.00001") -> ArxivPaperMeta:
    return ArxivPaperMeta(
        arxiv_id=arxiv_id,
        title="Test Paper",
        authors=["Alice", "Bob"],
        abstract="Abstract text.",
        url=f"https://arxiv.org/abs/{arxiv_id}",
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
        published_at=datetime(2023, 1, 1),
        msc_codes=[],
        categories=["math.AG"],
    )


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def test_search_arxiv_returns_results(client):
    with patch("src.api.routers.papers.arxiv_client.search", return_value=[_meta()]):
        resp = client.post("/papers/search", json={"query": "Riemann", "source": "arxiv"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Test Paper"
    assert data[0]["arxiv_id"] == "2301.00001"


def test_search_unknown_source_returns_400(client):
    resp = client.post("/papers/search", json={"query": "q", "source": "unknown"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def test_ingest_creates_paper_and_returns_202(client):
    with (
        patch("src.api.routers.papers.arxiv_client.fetch_by_id", return_value=_meta()),
        patch("src.api.routers.papers.collections.upsert_paper"),
        patch("src.api.routers.papers.asyncio.create_task", side_effect=lambda c: c.close()),
    ):
        resp = client.post("/papers/ingest", json={"arxiv_id": "2301.00001"})

    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "pending"
    assert "job_id" in data
    assert "paper_id" in data


def test_ingest_duplicate_returns_existing_paper(client):
    """Re-ingesting the same arXiv ID is idempotent: returns 202 with the existing paper_id."""
    with (
        patch("src.api.routers.papers.arxiv_client.fetch_by_id", return_value=_meta()),
        patch("src.api.routers.papers.collections.upsert_paper"),
        patch("src.api.routers.papers.asyncio.create_task", side_effect=lambda c: c.close()),
    ):
        first = client.post("/papers/ingest", json={"arxiv_id": "2301.00001"})
        resp = client.post("/papers/ingest", json={"arxiv_id": "2301.00001"})

    assert resp.status_code == 202
    assert resp.json()["paper_id"] == first.json()["paper_id"]


def test_ingest_arxiv_not_found_returns_404(client):
    with patch("src.api.routers.papers.arxiv_client.fetch_by_id", return_value=None):
        resp = client.post("/papers/ingest", json={"arxiv_id": "9999.99999"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Job polling
# ---------------------------------------------------------------------------

def test_get_ingest_job_not_found(client):
    resp = client.get("/papers/ingest/no-such-job")
    assert resp.status_code == 404


def test_get_ingest_job_pending(client, test_thread_metadata, mock_ingestion_graph):
    test_thread_metadata["j1"] = {"paper_id": "p1"}
    mock_ingestion_graph.get_state.return_value = None
    resp = client.get("/papers/ingest/j1")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


def test_get_ingest_job_running(client, test_thread_metadata, test_running_threads):
    test_thread_metadata["j1"] = {"paper_id": "p1"}
    test_running_threads.add("j1")
    resp = client.get("/papers/ingest/j1")
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


def test_get_ingest_job_done(client, test_thread_metadata, mock_ingestion_graph):
    test_thread_metadata["j2"] = {"paper_id": "p1"}
    snapshot = MagicMock()
    snapshot.values = {
        "paper_id": "p1",
        "concepts_created": 3,
        "new_concept_ids": ["a", "b", "c"],
        "relationships_created": 2,
        "status": "done",
    }
    mock_ingestion_graph.get_state.return_value = snapshot
    resp = client.get("/papers/ingest/j2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"
    assert data["concepts_created"] == 3
    assert data["concept_ids"] == ["a", "b", "c"]


def test_get_ingest_job_failed(client, test_thread_metadata, mock_ingestion_graph):
    test_thread_metadata["j3"] = {"paper_id": "p1", "error": "Network error"}
    snapshot = MagicMock()
    snapshot.values = {"status": "running"}
    mock_ingestion_graph.get_state.return_value = snapshot
    resp = client.get("/papers/ingest/j3")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert data["error"] == "Network error"


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------

def test_resume_ingest_job_not_found(client):
    resp = client.post("/papers/ingest/no-such-job/resume")
    assert resp.status_code == 404


def test_resume_ingest_job_returns_202(client, test_thread_metadata):
    test_thread_metadata["j4"] = {"paper_id": "p1"}
    with patch("src.api.routers.papers.asyncio.create_task", side_effect=lambda c: c.close()):
        resp = client.post("/papers/ingest/j4/resume")
    assert resp.status_code == 202
    assert resp.json()["status"] == "running"


# ---------------------------------------------------------------------------
# List / get
# ---------------------------------------------------------------------------

def test_ingest_no_abstract_skips_chroma_upsert(client):
    """Paper with no abstract should still return 202; ChromaDB upsert is skipped."""
    meta_no_abstract = _meta()
    meta_no_abstract = meta_no_abstract.__class__(
        **{**meta_no_abstract.__dict__, "abstract": None}
    )
    with (
        patch("src.api.routers.papers.arxiv_client.fetch_by_id", return_value=meta_no_abstract),
        patch("src.api.routers.papers.collections.upsert_paper") as mock_upsert,
        patch("src.api.routers.papers.asyncio.create_task", side_effect=lambda c: c.close()),
    ):
        resp = client.post("/papers/ingest", json={"arxiv_id": "2301.99999"})
    assert resp.status_code == 202
    mock_upsert.assert_not_called()


def test_list_papers_empty(client):
    resp = client.get("/papers")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_paper_not_found(client):
    resp = client.get("/papers/does-not-exist")
    assert resp.status_code == 404


def test_list_and_get_paper_roundtrip(client):
    with (
        patch("src.api.routers.papers.arxiv_client.fetch_by_id", return_value=_meta()),
        patch("src.api.routers.papers.collections.upsert_paper"),
        patch("src.api.routers.papers.asyncio.create_task", side_effect=lambda c: c.close()),
    ):
        ingest_resp = client.post("/papers/ingest", json={"arxiv_id": "2301.00001"})
    paper_id = ingest_resp.json()["paper_id"]

    list_resp = client.get("/papers")
    assert len(list_resp.json()) == 1

    get_resp = client.get(f"/papers/{paper_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["title"] == "Test Paper"
