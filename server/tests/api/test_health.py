"""Tests for GET /health."""

import uuid

from src.db.sqlite.models import Concept, ConceptRelationship
from src.db.sqlite.session import get_session


def test_health_ok_empty(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["graph_nodes"] == 0
    assert data["graph_edges"] == 0


def test_health_reflects_sqlite_counts(client):
    cid1 = str(uuid.uuid4())
    cid2 = str(uuid.uuid4())
    rel_id = str(uuid.uuid4())

    with get_session() as session:
        session.add(Concept(
            id=cid1, name="A", concept_type="theorem",
            latex_statement=r"x=1", lean_verification_status="unverified",
        ))
        session.add(Concept(
            id=cid2, name="B", concept_type="lemma",
            latex_statement=r"y=2", lean_verification_status="unverified",
        ))
        session.add(ConceptRelationship(
            id=rel_id,
            source_concept_id=cid1,
            target_concept_id=cid2,
            relationship_type="depends_on",
        ))

    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["graph_nodes"] == 2
    assert data["graph_edges"] == 1
