"""Concepts router — list, retrieve, semantic search, and impact analysis."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_

from src.api.schemas import ConceptEdge, ConceptGraphResponse, ConceptNode, ConceptSearchRequest, ConceptSearchResult
from src.db.chroma import collections
from src.db.sqlite.models import Concept
from src.db.sqlite.session import get_session
from src.graph import knowledge_graph
from src.schemas.models import ConceptRead, ImpactAnalysisResult

router = APIRouter(prefix="/concepts", tags=["concepts"])


@router.get("", response_model=list[ConceptRead])
def list_concepts(
    concept_type: Optional[str] = Query(None),
    source_paper_id: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
) -> list[ConceptRead]:
    """List persisted concepts with optional filters. Ordered by name for stable pagination."""
    with get_session() as session:
        q = session.query(Concept)
        if concept_type:
            q = q.filter(Concept.concept_type == concept_type)
        if source_paper_id:
            q = q.filter(Concept.source_paper_id == source_paper_id)
        q = q.order_by(Concept.name)
        return [ConceptRead.model_validate(c) for c in q.offset(offset).limit(limit).all()]


@router.get("/graph", response_model=ConceptGraphResponse)
def get_concept_graph(
    paper_ids: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=500),
) -> ConceptGraphResponse:
    """Return concept nodes + edges for graph visualization.

    When paper_ids are given: returns all concepts from those papers and any relationship
    that touches them (including edges to concepts from other papers). When no paper_ids,
    returns up to `limit` concepts and all edges between them.
    """
    from src.db.sqlite.models import ConceptRelationship

    ids_list = [p.strip() for p in paper_ids.split(",") if p.strip()] if paper_ids else []
    with get_session() as session:
        q = session.query(Concept)
        if ids_list:
            q = q.filter(Concept.source_paper_id.in_(ids_list))
        concepts = q.limit(limit).all()
        cid_set = {c.id for c in concepts}
        # Any relationship that has source OR target in staged concepts (so we show cross-paper links too)
        rels = (
            session.query(ConceptRelationship)
            .filter(
                or_(
                    ConceptRelationship.source_concept_id.in_(cid_set),
                    ConceptRelationship.target_concept_id.in_(cid_set),
                )
            )
            .all()
        )
        # Include concept IDs that appear as the other end of an edge (so we have nodes for them)
        linked_ids = cid_set | {r.source_concept_id for r in rels} | {r.target_concept_id for r in rels}
        missing_ids = linked_ids - cid_set
        if missing_ids:
            extra = session.query(Concept).filter(Concept.id.in_(missing_ids)).all()
            concepts = list(concepts) + list(extra)
        # Build response inside session so ORM objects are not accessed after detach
        node_ids = {c.id for c in concepts}
        nodes = [
            ConceptNode(
                id=c.id,
                name=c.name,
                concept_type=c.concept_type,
                paper_id=c.source_paper_id,
            )
            for c in concepts
        ]
        edges = [
            ConceptEdge(
                source=r.source_concept_id,
                target=r.target_concept_id,
                relationship_type=r.relationship_type,
            )
            for r in rels
            if r.source_concept_id in node_ids and r.target_concept_id in node_ids
        ]
        # Cross-paper links: same concept name in different papers → "same_as" edge
        if ids_list and len(ids_list) > 1:
            name_to_concepts: dict[str, list[tuple[str, str]]] = {}  # normalized_name -> [(concept_id, paper_id)]
            for c in concepts:
                key = " ".join(c.name.lower().split()) if c.name else ""
                if not key:
                    continue
                if key not in name_to_concepts:
                    name_to_concepts[key] = []
                name_to_concepts[key].append((c.id, c.source_paper_id or ""))
            seen_edges: set[tuple[str, str]] = set()
            for _name, concept_list in name_to_concepts.items():
                for i, (cid_a, pid_a) in enumerate(concept_list):
                    for cid_b, pid_b in concept_list[i + 1 :]:
                        if pid_a != pid_b and cid_a != cid_b:
                            pair = (cid_a, cid_b) if cid_a < cid_b else (cid_b, cid_a)
                            if pair not in seen_edges:
                                seen_edges.add(pair)
                                edges.append(
                                    ConceptEdge(
                                        source=cid_a,
                                        target=cid_b,
                                        relationship_type="same_as",
                                    )
                                )
    return ConceptGraphResponse(nodes=nodes, edges=edges)


@router.get("/{concept_id}", response_model=ConceptRead)
def get_concept(concept_id: str) -> ConceptRead:
    """Retrieve a single concept by ID."""
    with get_session() as session:
        concept = session.get(Concept, concept_id)
        if concept is None:
            raise HTTPException(status_code=404, detail=f"Concept {concept_id!r} not found")
        return ConceptRead.model_validate(concept)


@router.post("/search", response_model=list[ConceptSearchResult])
def search_concepts(req: ConceptSearchRequest) -> list[ConceptSearchResult]:
    """Semantic search over concept embeddings in ChromaDB."""
    results = collections.query_concepts(req.query, n_results=req.n_results)
    ids = results.get("ids", [[]])[0]
    distances = results.get("distances", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    return [
        ConceptSearchResult(
            concept_id=cid,
            name=meta.get("name", ""),
            concept_type=meta.get("concept_type", ""),
            distance=dist,
        )
        for cid, dist, meta in zip(ids, distances, metadatas)
    ]


@router.get("/{concept_id}/impact", response_model=ImpactAnalysisResult)
def get_concept_impact(concept_id: str) -> ImpactAnalysisResult:
    """Return impact subgraph, potential conflicts, and dependencies for a concept."""
    with get_session() as session:
        if session.get(Concept, concept_id) is None:
            raise HTTPException(status_code=404, detail=f"Concept {concept_id!r} not found")

    g = knowledge_graph.build_graph()
    return ImpactAnalysisResult(
        concept_id=concept_id,
        affected_by_relationship=knowledge_graph.get_impact_subgraph(g, concept_id),
        potential_conflicts=knowledge_graph.find_potential_conflicts(g, concept_id),
        dependencies=knowledge_graph.get_dependencies(g, concept_id),
    )
