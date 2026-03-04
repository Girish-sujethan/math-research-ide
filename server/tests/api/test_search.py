"""Tests for POST /search."""

from unittest.mock import patch


_EMPTY_CHROMA = {"ids": [[]], "distances": [[]], "metadatas": [[]]}


def test_search_concepts_empty(client):
    with (
        patch("src.api.routers.search.collections.query_concepts", return_value=_EMPTY_CHROMA),
        patch("src.api.routers.search.collections.query_papers", return_value=_EMPTY_CHROMA),
    ):
        resp = client.post("/search", json={"query": "Riemann"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["concepts"] == []
    assert data["papers"] == []


def test_search_concepts_only(client):
    mock_concepts = {
        "ids": [["c1"]],
        "distances": [[0.05]],
        "metadatas": [[{"name": "Theorem A", "concept_type": "theorem"}]],
    }
    with (
        patch("src.api.routers.search.collections.query_concepts", return_value=mock_concepts),
    ):
        resp = client.post("/search", json={
            "query": "topology", "search_concepts": True, "search_papers": False
        })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["concepts"]) == 1
    assert data["concepts"][0]["concept_id"] == "c1"
    assert data["papers"] == []


def test_search_papers_only_no_db_hit(client):
    mock_papers = {"ids": [["p1"]], "distances": [[0.1]], "metadatas": [[{"title": "X"}]]}
    # Paper p1 not in DB → no result in papers list
    with patch("src.api.routers.search.collections.query_papers", return_value=mock_papers):
        resp = client.post("/search", json={
            "query": "manifold", "search_concepts": False, "search_papers": True
        })
    assert resp.status_code == 200
    # p1 not in test DB, so papers list is empty
    assert resp.json()["papers"] == []


def test_search_both_fields(client):
    with (
        patch("src.api.routers.search.collections.query_concepts", return_value=_EMPTY_CHROMA),
        patch("src.api.routers.search.collections.query_papers", return_value=_EMPTY_CHROMA),
    ):
        resp = client.post("/search", json={"query": "anything"})
    assert resp.status_code == 200
    assert "concepts" in resp.json()
    assert "papers" in resp.json()
