"""Relationships router — list and manually create concept relationships."""

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src.db.sqlite.models import Concept, ConceptRelationship
from src.db.sqlite.session import get_session
from src.schemas.models import RelationshipCreate, RelationshipRead

router = APIRouter(prefix="/relationships", tags=["relationships"])


@router.get("", response_model=list[RelationshipRead])
def list_relationships(
    source_concept_id: Optional[str] = Query(None),
    target_concept_id: Optional[str] = Query(None),
    relationship_type: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> list[RelationshipRead]:
    """List concept relationships with optional filters."""
    with get_session() as session:
        q = session.query(ConceptRelationship)
        if source_concept_id:
            q = q.filter(ConceptRelationship.source_concept_id == source_concept_id)
        if target_concept_id:
            q = q.filter(ConceptRelationship.target_concept_id == target_concept_id)
        if relationship_type:
            q = q.filter(ConceptRelationship.relationship_type == relationship_type)
        return [RelationshipRead.model_validate(r) for r in q.offset(offset).limit(limit).all()]


@router.post("", response_model=RelationshipRead, status_code=201)
def create_relationship(rel: RelationshipCreate) -> RelationshipRead:
    """Manually assert a relationship between two concepts (no LLM — user asserted)."""
    rel_id = str(uuid.uuid4())
    with get_session() as session:
        src = session.get(Concept, rel.source_concept_id)
        tgt = session.get(Concept, rel.target_concept_id)
        if src is None:
            raise HTTPException(
                status_code=404,
                detail=f"Source concept {rel.source_concept_id!r} not found",
            )
        if tgt is None:
            raise HTTPException(
                status_code=404,
                detail=f"Target concept {rel.target_concept_id!r} not found",
            )
        existing = (
            session.query(ConceptRelationship)
            .filter(
                ConceptRelationship.source_concept_id == rel.source_concept_id,
                ConceptRelationship.target_concept_id == rel.target_concept_id,
                ConceptRelationship.relationship_type == rel.relationship_type,
            )
            .first()
        )
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Relationship {rel.relationship_type!r} from "
                    f"{rel.source_concept_id!r} to {rel.target_concept_id!r} "
                    f"already exists (id={existing.id})"
                ),
            )
        db_rel = ConceptRelationship(
            id=rel_id,
            source_concept_id=rel.source_concept_id,
            target_concept_id=rel.target_concept_id,
            relationship_type=rel.relationship_type,
            description=rel.description,
            weight=rel.weight,
            source_paper_id=rel.source_paper_id,
        )
        session.add(db_rel)

    return RelationshipRead(id=rel_id, **rel.model_dump())
