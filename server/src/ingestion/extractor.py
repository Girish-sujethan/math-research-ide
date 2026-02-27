"""Math concept extractor.

Takes transiently fetched paper content and extracts structured mathematical
knowledge (theorems, definitions, lemmas, etc.) for persistence in SQLite + ChromaDB.

The extraction logic here is a stub — it will be driven by the model layer
once that is implemented. The interface is stable.
"""

from dataclasses import dataclass, field
from typing import Literal

ConceptType = Literal["theorem", "definition", "lemma", "axiom", "conjecture", "corollary", "proposition"]


@dataclass
class ExtractedConcept:
    name: str
    concept_type: ConceptType
    latex_statement: str
    description: str
    msc_codes: list[str] = field(default_factory=list)
    context_snippet: str = ""   # surrounding text for provenance, not stored long-term


def extract_from_text(
    content: str,
    source_hint: str = "",
) -> list[ExtractedConcept]:
    """Extract mathematical concepts from raw paper text.

    Args:
        content: Transiently fetched paper content (HTML or plain text).
        source_hint: Paper title or ID for logging — not stored.

    Returns:
        List of extracted concepts ready for persistence.

    Note:
        This is a placeholder. The model layer will implement the actual
        extraction logic using an LLM with structured outputs.
        Typical approach: identify LaTeX environments (theorem, definition,
        lemma, proof), extract statement + label, infer concept_type from
        environment name.
    """
    raise NotImplementedError(
        "extract_from_text requires the model layer. "
        "Implement using an LLM with structured output once the model layer is ready."
    )


def build_concept_embedding_text(
    name: str,
    latex_statement: str,
    description: str,
) -> str:
    """Compose the text that gets embedded in ChromaDB for a concept.

    Keeps LaTeX notation intact — embedding model must handle it.
    """
    parts = [f"Name: {name}"]
    if description:
        parts.append(f"Description: {description}")
    parts.append(f"Statement: {latex_statement}")
    return "\n".join(parts)
