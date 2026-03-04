"""LangGraph ingestion pipeline — 4-node StateGraph with SqliteSaver checkpointing.

Nodes (linear):
  1. fetch_content                  — arXiv ar5iv fetch
  2. extract_and_persist_concepts   — chunk → LLM extract → dedup → SQLite + ChromaDB
  3. classify_msc                   — LLM MSC codes → SQLite update
  4. extract_and_persist_relationships — LLM relationships → SQLite; status="done"
"""

import dataclasses
import logging
import re
import uuid
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph

from src.db.chroma import collections
from src.db.sqlite.models import Concept, ConceptRelationship, Paper
from src.db.sqlite.session import get_session
from src.ingestion import arxiv_client
from src.ingestion.extractor import ExtractedConcept, build_concept_embedding_text
from src.model.extraction import (
    chunker,
    concept_extractor,
    deduplicator,
    relationship_extractor,
)
from src.model.providers.registry import cheap as _cheap_default
from src.model.providers.registry import primary as _primary_default
from src.model.reasoning import msc_classifier

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class IngestionState(TypedDict):
    paper_id: str
    arxiv_id: str
    content: Optional[str]
    extracted_concepts: list[dict]   # dataclasses.asdict(ExtractedConcept) for new concepts
    name_to_id: dict[str, str]       # concept_name → concept_id (all, incl. deduped)
    new_concept_ids: list[str]
    concepts_created: int
    concepts_deduplicated: int
    relationships_created: int
    status: str                      # "running" | "done"


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def fetch_content(state: IngestionState) -> dict:
    """Fetch full paper text from ar5iv. Skips fetch if content is already provided (e.g. PDF upload)."""
    if state["content"] is not None:
        return {}
    content = arxiv_client.fetch_content_transiently(state["arxiv_id"])
    if content is None:
        raise RuntimeError(f"Could not fetch ar5iv content for {state['arxiv_id']!r}")
    return {"content": content}


def extract_and_persist_concepts(state: IngestionState) -> dict:
    """Chunk paper → LLM extract → deduplicate → persist to SQLite + ChromaDB."""
    content = state["content"]
    paper_id = state["paper_id"]

    with get_session() as session:
        db_paper = session.get(Paper, paper_id)
        title = db_paper.title if db_paper else paper_id

    chunks = chunker.chunk_paper(content)
    logger.info("Paper %s: split into %d chunks", paper_id, len(chunks))

    all_extracted: list[ExtractedConcept] = []
    for i, chunk in enumerate(chunks):
        try:
            extracted = concept_extractor.extract_concepts(
                chunk, provider=_primary_default, source_hint=title
            )
            all_extracted.extend(extracted)
        except Exception as exc:
            logger.warning("Extraction failed on chunk %d of paper %s: %s", i, paper_id, exc)

    logger.info("Paper %s: extracted %d raw concepts", paper_id, len(all_extracted))

    name_to_id: dict[str, str] = {}
    new_concepts: list[ExtractedConcept] = []
    new_concept_ids: list[str] = []
    concepts_created = 0
    concepts_deduplicated = 0

    for extracted in all_extracted:
        try:
            existing_id = deduplicator.find_duplicate(extracted, provider=_cheap_default)
        except Exception as exc:
            logger.warning("Dedup check failed for concept %s: %s", extracted.name, exc)
            existing_id = None

        if existing_id is not None:
            concepts_deduplicated += 1
            name_to_id[extracted.name] = existing_id
            continue

        concept_id = str(uuid.uuid4())
        with get_session() as session:
            db_concept = Concept(
                id=concept_id,
                name=extracted.name,
                concept_type=extracted.concept_type,
                latex_statement=extracted.latex_statement,
                description=extracted.description,
                msc_codes=extracted.msc_codes,
                source_paper_id=paper_id,
                lean_verification_status="unverified",
                chroma_embedding_id=concept_id,
            )
            session.add(db_concept)

        embedding_text = build_concept_embedding_text(
            extracted.name, extracted.latex_statement, extracted.description
        )
        collections.upsert_concept(
            concept_id=concept_id,
            text=embedding_text,
            metadata={
                "name": extracted.name,
                "concept_type": extracted.concept_type,
                "source_paper_id": paper_id,
            },
        )

        name_to_id[extracted.name] = concept_id
        new_concepts.append(extracted)
        new_concept_ids.append(concept_id)
        concepts_created += 1

    return {
        "extracted_concepts": [dataclasses.asdict(c) for c in new_concepts],
        "name_to_id": name_to_id,
        "new_concept_ids": new_concept_ids,
        "concepts_created": concepts_created,
        "concepts_deduplicated": concepts_deduplicated,
    }


def _build_relationship_candidate_pairs(
    all_concept_infos: list[ExtractedConcept],
    name_to_id: dict[str, str],
) -> list[tuple[str, str]]:
    """Build candidate (source_name, target_name) pairs using semantic similarity and keyword overlap."""
    if not all_concept_infos or not name_to_id:
        return []
    id_to_name = {v: k for k, v in name_to_id.items()}
    valid_ids = set(name_to_id.values())
    pairs: set[tuple[str, str]] = set()

    # 1. Semantic: ChromaDB similarity within this concept set
    for c in all_concept_infos:
        try:
            text = build_concept_embedding_text(c.name, c.latex_statement, c.description or "")
            result = collections.query_concepts(text, n_results=16)
            ids = result.get("ids", [[]])[0]
            distances = result.get("distances", [[]])[0]
            for cid, dist in zip(ids or [], distances or []):
                if cid not in valid_ids or cid == name_to_id.get(c.name):
                    continue
                if dist is not None and dist > 0.80:
                    continue
                other = id_to_name.get(cid)
                if other and other != c.name:
                    key = (c.name, other) if c.name < other else (other, c.name)
                    pairs.add(key)
        except Exception as exc:
            logger.debug("Semantic candidate query failed for %s: %s", c.name, exc)

    # 2. Keyword overlap: shared meaningful words from name + description
    _stop = {"the", "and", "for", "that", "this", "with", "from", "are", "was", "were", "have", "has", "can", "may", "not", "any", "all", "each", "both", "its", "than", "when", "which", "into", "such", "then", "only", "out", "one", "two", "if", "or", "an", "is", "in", "to", "of", "as", "by", "on", "at", "be", "it"}
    def _keywords(t: str) -> set[str]:
        words = set(re.findall(r"[a-zA-Z0-9]{2,}", (t or "").lower()))
        return words - _stop

    name_to_kw: dict[str, set[str]] = {}
    for c in all_concept_infos:
        name_to_kw[c.name] = _keywords(c.name) | _keywords(c.description or "")

    for i, a in enumerate(all_concept_infos):
        for b in all_concept_infos[i + 1 :]:
            if a.name == b.name:
                continue
            overlap = name_to_kw.get(a.name, set()) & name_to_kw.get(b.name, set())
            if len(overlap) >= 1:
                key = (a.name, b.name) if a.name < b.name else (b.name, a.name)
                pairs.add(key)

    return list(pairs)


def classify_msc(state: IngestionState) -> dict:
    """Classify MSC codes for the paper and write back to SQLite."""
    paper_id = state["paper_id"]
    with get_session() as session:
        db_paper = session.get(Paper, paper_id)
        if db_paper is not None and db_paper.abstract:
            msc_text = f"{db_paper.title}\n\n{db_paper.abstract}"
            try:
                msc_codes = msc_classifier.classify_msc(msc_text, provider=_cheap_default)
                if msc_codes:
                    db_paper.msc_codes = msc_codes
            except Exception as exc:
                logger.warning("MSC classification failed for paper %s: %s", paper_id, exc)
    return {}


def extract_and_persist_relationships(state: IngestionState) -> dict:
    """Extract relationships between all concepts (new + deduplicated) and persist to SQLite.

    Previously we only passed new concepts, so relationships involving deduplicated
    (existing) concepts were never created. We now load deduplicated concepts from
    the DB and pass the full set to the relationship extractor.
    """
    paper_id = state["paper_id"]
    name_to_id = state["name_to_id"]
    extracted_concepts_dicts = state["extracted_concepts"]
    new_concept_ids = set(state.get("new_concept_ids") or [])

    new_concepts = [ExtractedConcept(**d) for d in extracted_concepts_dicts]
    new_ids = {name_to_id.get(c.name) for c in new_concepts if name_to_id.get(c.name)}
    new_ids.discard(None)

    # Include deduplicated concepts so we can create relationships that involve them
    all_concept_infos: list[ExtractedConcept] = list(new_concepts)
    deduplicated_ids = [cid for cid in name_to_id.values() if cid not in new_ids]
    if deduplicated_ids:
        with get_session() as session:
            for db_c in session.query(Concept).filter(Concept.id.in_(deduplicated_ids)).all():
                ctype = db_c.concept_type
                if hasattr(ctype, "value"):
                    ctype = ctype.value
                all_concept_infos.append(
                    ExtractedConcept(
                        name=db_c.name,
                        concept_type=ctype,
                        latex_statement=db_c.latex_statement or "",
                        description=db_c.description or "",
                        msc_codes=db_c.msc_codes or [],
                    )
                )

    if not all_concept_infos:
        return {"relationships_created": 0, "status": "done"}

    candidate_pairs = _build_relationship_candidate_pairs(all_concept_infos, name_to_id)
    if candidate_pairs:
        logger.info("Paper %s: %d candidate pairs (semantic + keyword) for relationship extraction", paper_id, len(candidate_pairs))

    try:
        pending_rels = relationship_extractor.extract_relationships(
            all_concept_infos,
            provider=_primary_default,
            candidate_pairs=candidate_pairs,
        )
    except Exception as exc:
        logger.warning("Relationship extraction failed for paper %s: %s", paper_id, exc)
        pending_rels = []

    existing_pairs: set[tuple[str, str]] = {
        (pending.source_concept_name, pending.target_concept_name)
        for pending in pending_rels
    }
    relationships_created = 0
    for pending in pending_rels:
        src_id = name_to_id.get(pending.source_concept_name)
        tgt_id = name_to_id.get(pending.target_concept_name)
        if not src_id or not tgt_id:
            logger.debug(
                "Could not resolve concept names for relationship: %s → %s",
                pending.source_concept_name, pending.target_concept_name,
            )
            continue

        rel_id = str(uuid.uuid4())
        try:
            with get_session() as session:
                db_rel = ConceptRelationship(
                    id=rel_id,
                    source_concept_id=src_id,
                    target_concept_id=tgt_id,
                    relationship_type=pending.relationship_type,
                    description=pending.description,
                    source_paper_id=paper_id,
                )
                session.add(db_rel)
            relationships_created += 1
        except Exception as exc:
            logger.warning(
                "Failed to persist relationship %s → %s: %s",
                pending.source_concept_name, pending.target_concept_name, exc,
            )

    # Auto-add "related_to" for candidate pairs the LLM did not label (semantic/keyword only)
    for a, b in candidate_pairs:
        if (a, b) in existing_pairs or (b, a) in existing_pairs:
            continue
        src_id = name_to_id.get(a)
        tgt_id = name_to_id.get(b)
        if not src_id or not tgt_id:
            continue
        rel_id = str(uuid.uuid4())
        try:
            with get_session() as session:
                db_rel = ConceptRelationship(
                    id=rel_id,
                    source_concept_id=src_id,
                    target_concept_id=tgt_id,
                    relationship_type="related_to",
                    description="Semantically or keyword-related (auto-linked).",
                    source_paper_id=paper_id,
                )
                session.add(db_rel)
            relationships_created += 1
            existing_pairs.add((a, b))
        except Exception as exc:
            logger.debug("Could not add related_to %s -> %s: %s", a, b, exc)

    return {"relationships_created": relationships_created, "status": "done"}


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_ingestion_graph(checkpointer):
    """Compile and return the ingestion StateGraph with the given checkpointer."""
    workflow = StateGraph(IngestionState)

    workflow.add_node("fetch_content", fetch_content)
    workflow.add_node("extract_and_persist_concepts", extract_and_persist_concepts)
    workflow.add_node("classify_msc", classify_msc)
    workflow.add_node("extract_and_persist_relationships", extract_and_persist_relationships)

    workflow.set_entry_point("fetch_content")
    workflow.add_edge("fetch_content", "extract_and_persist_concepts")
    workflow.add_edge("extract_and_persist_concepts", "classify_msc")
    workflow.add_edge("classify_msc", "extract_and_persist_relationships")
    workflow.add_edge("extract_and_persist_relationships", END)

    return workflow.compile(checkpointer=checkpointer)
