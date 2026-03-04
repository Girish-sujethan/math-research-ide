"""NetworkX knowledge graph — built on demand from persisted SQLite relationships.

Nodes represent Concepts. Edges represent ConceptRelationships.
The graph is reconstructed from SQLite each time ``build_graph()`` is called;
there is no shared in-memory graph instance.

Key operations:
- Impact analysis: what concepts are affected when a discovery modifies a base concept
- Conflict detection: find concepts that may contradict a new statement
- Dependency traversal: what does a concept depend on (and transitively)
"""

from typing import Literal

import networkx as nx

from src.db.sqlite.models import Concept, ConceptRelationship
from src.db.sqlite.session import get_session

ImpactType = Literal["extends", "contradicts", "generalizes", "enables", "invalidates"]


def build_graph() -> nx.DiGraph:
    """Reconstruct the full knowledge graph from SQLite."""
    G = nx.DiGraph()

    with get_session() as session:
        concepts = session.query(Concept).all()
        for c in concepts:
            G.add_node(
                c.id,
                name=c.name,
                concept_type=c.concept_type,
                lean_status=c.lean_verification_status,
                msc_codes=c.msc_codes,
            )

        relationships = session.query(ConceptRelationship).all()
        for r in relationships:
            G.add_edge(
                r.source_concept_id,
                r.target_concept_id,
                relationship_type=r.relationship_type,
                weight=r.weight,
                description=r.description,
            )

    return G


def get_impact_subgraph(
    G: nx.DiGraph,
    concept_id: str,
    max_depth: int = 3,
) -> dict[str, list[str]]:
    """Return concepts reachable from concept_id within max_depth hops.

    Returns a dict mapping relationship_type → list of affected concept_ids.
    Used to show what changes when a discovery modifies a base concept.
    """
    if concept_id not in G:
        return {}

    affected: dict[str, list[str]] = {}
    visited = set()

    def traverse(node_id: str, depth: int) -> None:
        if depth > max_depth or node_id in visited:
            return
        visited.add(node_id)

        for _, target, data in G.out_edges(node_id, data=True):
            rel_type = data.get("relationship_type", "unknown")
            affected.setdefault(rel_type, [])
            if target not in affected[rel_type]:
                affected[rel_type].append(target)
            traverse(target, depth + 1)

    traverse(concept_id, 0)
    affected.pop(concept_id, None)  # exclude the source itself
    return affected


def get_dependencies(
    G: nx.DiGraph,
    concept_id: str,
) -> list[str]:
    """Return all concepts that `concept_id` transitively depends on."""
    if concept_id not in G:
        return []
    dep_edges = [
        (u, v) for u, v, d in G.in_edges(concept_id, data=True)
        if d.get("relationship_type") == "depends_on"
    ]
    deps: list[str] = []
    queue = [u for u, _ in dep_edges]
    visited = set()
    while queue:
        node = queue.pop()
        if node in visited:
            continue
        visited.add(node)
        deps.append(node)
        for u, _, d in G.in_edges(node, data=True):
            if d.get("relationship_type") == "depends_on" and u not in visited:
                queue.append(u)
    return deps


def find_potential_conflicts(
    G: nx.DiGraph,
    concept_id: str,
) -> list[str]:
    """Return concepts connected via a 'contradicts' edge to concept_id."""
    if concept_id not in G:
        return []

    conflicts = []
    for _, target, data in G.out_edges(concept_id, data=True):
        if data.get("relationship_type") == "contradicts":
            conflicts.append(target)
    for source, _, data in G.in_edges(concept_id, data=True):
        if data.get("relationship_type") == "contradicts":
            conflicts.append(source)
    return list(set(conflicts))
