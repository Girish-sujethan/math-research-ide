"""Tests for /concepts routes."""

import uuid
from unittest.mock import patch

from src.db.sqlite.models import Concept
from src.db.sqlite.session import get_session


def _insert_concept(name: str = "Riemann Hypothesis", concept_type: str = "theorem") -> str:
    concept_id = str(uuid.uuid4())
    with get_session() as session:
        session.add(Concept(
            id=concept_id,
            name=name,
            concept_type=concept_type,
            latex_statement=r"\zeta(s) \neq 0",
            description="All non-trivial zeros lie on the critical line.",
            msc_codes=["11M26"],
            lean_verification_status="unverified",
            chroma_embedding_id=concept_id,
        ))
    return concept_id


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

def test_list_concepts_empty(client):
    resp = client.get("/concepts")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_concepts_returns_inserted(client):
    _insert_concept()
    resp = client.get("/concepts")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_list_concepts_filter_by_type(client):
    _insert_concept("Theorem A", "theorem")
    _insert_concept("Def B", "definition")
    resp = client.get("/concepts?concept_type=theorem")
    assert resp.status_code == 200
    data = resp.json()
    assert all(c["concept_type"] == "theorem" for c in data)


def test_list_concepts_filter_by_source_paper_id(client):
    cid = _insert_concept()
    # Manually set source_paper_id by creating with session
    import uuid as _uuid
    from src.db.sqlite.session import get_session
    from src.db.sqlite.models import Concept
    paper_id = str(_uuid.uuid4())
    linked_cid = str(_uuid.uuid4())
    with get_session() as session:
        session.add(Concept(
            id=linked_cid,
            name="Linked Concept",
            concept_type="lemma",
            latex_statement=r"y = x",
            source_paper_id=paper_id,
            lean_verification_status="unverified",
            chroma_embedding_id=linked_cid,
        ))
    resp = client.get(f"/concepts?source_paper_id={paper_id}")
    assert resp.status_code == 200
    ids = [c["id"] for c in resp.json()]
    assert linked_cid in ids
    assert cid not in ids


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------

def test_get_concept_not_found(client):
    resp = client.get("/concepts/no-such-id")
    assert resp.status_code == 404


def test_get_concept_found(client):
    cid = _insert_concept()
    resp = client.get(f"/concepts/{cid}")
    assert resp.status_code == 200
    assert resp.json()["id"] == cid
    assert resp.json()["name"] == "Riemann Hypothesis"


# ---------------------------------------------------------------------------
# Semantic search
# ---------------------------------------------------------------------------

def test_search_concepts_returns_results(client):
    mock_results = {
        "ids": [["abc", "def"]],
        "distances": [[0.1, 0.2]],
        "metadatas": [[
            {"name": "Concept A", "concept_type": "theorem"},
            {"name": "Concept B", "concept_type": "lemma"},
        ]],
    }
    with patch("src.api.routers.concepts.collections.query_concepts", return_value=mock_results):
        resp = client.post("/concepts/search", json={"query": "Riemann", "n_results": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["concept_id"] == "abc"
    assert data[0]["name"] == "Concept A"


def test_search_concepts_empty(client):
    mock_results = {"ids": [[]], "distances": [[]], "metadatas": [[]]}
    with patch("src.api.routers.concepts.collections.query_concepts", return_value=mock_results):
        resp = client.post("/concepts/search", json={"query": "nothing"})
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Impact
# ---------------------------------------------------------------------------

def test_get_impact_not_found(client):
    resp = client.get("/concepts/no-such-id/impact")
    assert resp.status_code == 404


def test_get_impact_empty_graph(client):
    cid = _insert_concept()
    resp = client.get(f"/concepts/{cid}/impact")
    assert resp.status_code == 200
    data = resp.json()
    assert data["concept_id"] == cid
    assert data["affected_by_relationship"] == {}
    assert data["potential_conflicts"] == []
    assert data["dependencies"] == []
