"""LLM-based relationship extractor.

Given a list of extracted concepts, asks Claude to identify directed
relationships between them (proves, depends_on, generalizes, etc.).
Relationships use concept names rather than IDs — the pipeline resolves
names to UUIDs after persistence.
"""

import json
import logging
from dataclasses import dataclass

from src.ingestion.extractor import ExtractedConcept
from src.model.providers.base import LLMProvider

logger = logging.getLogger(__name__)

VALID_RELATIONSHIP_TYPES = frozenset({
    "proves",
    "depends_on",
    "generalizes",
    "is_special_case_of",
    "contradicts",
    "cited_by",
    "equivalent_to",
    "extends",
    "related_to",
})

_SYSTEM_PROMPT = """\
You are an expert in mathematical reasoning and knowledge graphs.

Given a list of mathematical concepts (theorems, definitions, lemmas, etc.), \
identify directed relationships between them.

For each relationship, output a JSON object with:
- "source_concept_name": name of the source concept (exactly as given)
- "target_concept_name": name of the target concept (exactly as given)
- "relationship_type": one of: proves, depends_on, generalizes, is_special_case_of, \
contradicts, cited_by, equivalent_to, extends, related_to
- "description": one sentence explaining the relationship

Use "related_to" when concepts are semantically or thematically related but do not fit \
proves/depends_on/generalizes/etc. Use the more specific types when the relationship is clear.

Output ONLY a JSON array. Include relationships that are clearly supported by the \
mathematical statements or by strong semantic/keyword overlap. Do not leave out pairs \
that were suggested as candidates if a relationship is plausible.
"""


@dataclass
class PendingRelationship:
    """A relationship between concepts identified by name (not yet resolved to IDs)."""
    source_concept_name: str
    target_concept_name: str
    relationship_type: str
    description: str


def extract_relationships(
    concepts: list[ExtractedConcept],
    provider: LLMProvider,
    candidate_pairs: list[tuple[str, str]] | None = None,
) -> list[PendingRelationship]:
    """Extract relationships between a set of concepts.

    Args:
        concepts: Concepts extracted from a paper (and any deduplicated from DB).
        provider: LLM backend to use.
        candidate_pairs: Optional list of (source_name, target_name) pairs suggested by
            semantic similarity or keyword overlap; the LLM will consider these explicitly.

    Returns:
        List of PendingRelationship with string concept names.
        Returns [] on empty input or parse failure.
    """
    if not concepts:
        return []

    known_names = {c.name for c in concepts}

    # Build a compact concept listing for the prompt
    concept_lines = []
    for c in concepts:
        concept_lines.append(
            f"- [{c.concept_type.upper()}] {c.name}: {c.latex_statement}"
        )
    concept_block = "\n".join(concept_lines)

    # Filter candidate pairs to only include names we know
    if candidate_pairs:
        valid_pairs = [
            (a, b) for a, b in candidate_pairs
            if a in known_names and b in known_names and a != b
        ]
        # Deduplicate and limit size for prompt
        seen = set()
        unique_pairs = []
        for a, b in valid_pairs:
            key = (a, b) if a < b else (b, a)
            if key not in seen and len(unique_pairs) < 150:
                seen.add(key)
                unique_pairs.append((a, b))
    else:
        unique_pairs = []

    candidate_block = ""
    if unique_pairs:
        candidate_block = (
            "\n\nThese concept pairs were identified as semantically similar or sharing important keywords. "
            "Consider each for a relationship (proves, depends_on, related_to, etc.):\n"
            + "\n".join(f"- {a} <-> {b}" for a, b in unique_pairs[:100])
        )

    user_message = (
        f"Identify relationships between the following {len(concepts)} mathematical concepts:\n\n"
        f"{concept_block}"
        f"{candidate_block}\n\n"
        "Output a JSON array of relationships. Include any relationship that is supported by the statements or by the candidate pairs above."
    )

    try:
        response = provider.complete(
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=2048,
            temperature=0.0,
        )
    except Exception as exc:
        logger.warning("LLM call failed during relationship extraction: %s", exc)
        return []

    raw = response.content.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse relationship extraction response as JSON: %s", exc)
        return []

    if not isinstance(items, list):
        return []

    # Build name set for validation
    known_names = {c.name for c in concepts}
    relationships: list[PendingRelationship] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        src = item.get("source_concept_name", "")
        tgt = item.get("target_concept_name", "")
        rel = item.get("relationship_type", "")
        desc = item.get("description", "")

        if src not in known_names or tgt not in known_names:
            logger.debug("Skipping relationship with unknown concept names: %s -> %s", src, tgt)
            continue
        if rel not in VALID_RELATIONSHIP_TYPES:
            logger.debug("Skipping relationship with invalid type: %s", rel)
            continue

        relationships.append(PendingRelationship(
            source_concept_name=src,
            target_concept_name=tgt,
            relationship_type=rel,
            description=str(desc),
        ))

    return relationships
