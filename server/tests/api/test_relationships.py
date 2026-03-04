"""Tests for /relationships routes."""

import uuid

from src.db.sqlite.models import Concept
from src.db.sqlite.session import get_session


def _insert_concept(name: str = "C") -> str:
    cid = str(uuid.uuid4())
    with get_session() as session:
        session.add(Concept(
            id=cid,
            name=name,
            concept_type="theorem",
            latex_statement=r"x = 1",
            lean_verification_status="unverified",
        ))
    return cid


_REL_TYPE = "depends_on"


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

def test_list_relationships_empty(client):
    resp = client.get("/relationships")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def test_create_relationship_success(client):
    src = _insert_concept("Source")
    tgt = _insert_concept("Target")

    payload = {
        "source_concept_id": src,
        "target_concept_id": tgt,
        "relationship_type": _REL_TYPE,
        "weight": 1.0,
        "description": None,
        "source_paper_id": None,
    }
    resp = client.post("/relationships", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["relationship_type"] == _REL_TYPE
    assert data["source_concept_id"] == src
    assert "id" in data


def test_create_relationship_missing_source_returns_404(client):
    tgt = _insert_concept("Target")
    payload = {
        "source_concept_id": "no-such-id",
        "target_concept_id": tgt,
        "relationship_type": _REL_TYPE,
        "weight": 1.0,
        "description": None,
        "source_paper_id": None,
    }
    resp = client.post("/relationships", json=payload)
    assert resp.status_code == 404


def test_create_relationship_missing_target_returns_404(client):
    src = _insert_concept("Source")
    payload = {
        "source_concept_id": src,
        "target_concept_id": "no-such-id",
        "relationship_type": _REL_TYPE,
        "weight": 1.0,
        "description": None,
        "source_paper_id": None,
    }
    resp = client.post("/relationships", json=payload)
    assert resp.status_code == 404


def test_create_relationship_persisted_to_sqlite(client):
    """Created relationship is retrievable via GET /relationships."""
    src = _insert_concept("A")
    tgt = _insert_concept("B")

    client.post("/relationships", json={
        "source_concept_id": src,
        "target_concept_id": tgt,
        "relationship_type": "generalizes",
        "weight": 1.0,
        "description": None,
        "source_paper_id": None,
    })

    list_resp = client.get(f"/relationships?source_concept_id={src}")
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert len(data) == 1
    assert data[0]["relationship_type"] == "generalizes"


def test_create_relationship_duplicate_returns_409(client):
    src = _insert_concept("P")
    tgt = _insert_concept("Q")

    payload = {
        "source_concept_id": src,
        "target_concept_id": tgt,
        "relationship_type": _REL_TYPE,
        "weight": 1.0,
        "description": None,
        "source_paper_id": None,
    }
    client.post("/relationships", json=payload)
    resp = client.post("/relationships", json=payload)
    assert resp.status_code == 409


def test_list_relationships_filter_by_type(client):
    src = _insert_concept("X")
    tgt = _insert_concept("Y")

    for rel_type in ("depends_on", "generalizes"):
        client.post("/relationships", json={
            "source_concept_id": src,
            "target_concept_id": tgt,
            "relationship_type": rel_type,
            "weight": 1.0,
            "description": None,
            "source_paper_id": None,
        })

    resp = client.get("/relationships?relationship_type=depends_on")
    assert resp.status_code == 200
    assert all(r["relationship_type"] == "depends_on" for r in resp.json())
