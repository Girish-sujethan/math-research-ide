"""LangGraph discovery pipeline — 7-node StateGraph with SqliteSaver checkpointing.

Nodes (linear):
  1. initialize          — persist Discovery row, load base concept from SQLite
  2. symbolic_check      — SymPy/Wolfram → update SQLite status
  3. formalize           — normalize LaTeX + Lean 4 formalizer → update SQLite
  4. analyze_graph       — build_graph() from SQLite → impact subgraph + conflicts
  5. explain_impacts     — LLM → impacts: list[dict]
  6. explain_conflicts   — LLM → conflict_explanations: list[dict]
  7. persist_impacts     — write DiscoveryImpact rows → status="done"
"""

import dataclasses
import logging
import uuid
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph

from src.db.sqlite.models import Concept, Discovery, DiscoveryImpact
from src.db.sqlite.session import get_session
from src.graph import knowledge_graph
from src.model.formalization import formalizer, latex_normalizer
from src.model.providers.registry import cheap as _cheap_default
from src.model.providers.registry import primary as _primary_default
from src.model.reasoning import conflict_explainer, impact_explainer
from src.model.symbolic import router as symbolic_router
from src.schemas.models import ConceptRead, DiscoveryCreate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class DiscoveryState(TypedDict):
    # Inputs (set from DiscoveryCreate before first invoke)
    name: str
    base_concept_id: Optional[str]
    modified_latex_statement: str
    modification_description: str
    # Set by initialize node
    discovery_id: str
    concept_type: str
    base_concept: Optional[dict]       # ConceptRead.model_dump(mode="json")
    # Set by symbolic_check node
    sympy_passed: Optional[bool]
    sympy_output: Optional[str]
    sympy_status: str
    # Set by formalize node
    lean_success: bool
    lean_output: Optional[str]
    lean_status: str
    # Set by analyze_graph node
    affected: dict                     # relationship_type → list[concept_id]
    conflict_ids: list
    # Set by explain_impacts / explain_conflicts nodes
    impacts: list                      # list[dict] — dataclasses.asdict(ExplainedImpact)
    conflict_explanations: list        # list[dict] — dataclasses.asdict(ConflictExplanation)
    # Terminal status
    status: str                        # "running" | "done"


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def initialize(state: DiscoveryState) -> dict:
    """Persist the Discovery row and load the base concept from SQLite."""
    discovery_id = str(uuid.uuid4())

    with get_session() as session:
        db_discovery = Discovery(
            id=discovery_id,
            name=state["name"],
            base_concept_id=state["base_concept_id"],
            modified_latex_statement=state["modified_latex_statement"],
            modification_description=state["modification_description"],
            sympy_check_status="unchecked",
            lean_verification_status="unverified",
        )
        session.add(db_discovery)

    concept_type = "theorem"
    base_concept_dict: Optional[dict] = None

    if state["base_concept_id"]:
        with get_session() as session:
            db_concept = session.get(Concept, state["base_concept_id"])
            if db_concept is not None:
                concept_type = db_concept.concept_type
                base_concept_dict = ConceptRead.model_validate(db_concept).model_dump(mode="json")

    return {
        "discovery_id": discovery_id,
        "concept_type": concept_type,
        "base_concept": base_concept_dict,
    }


def symbolic_check(state: DiscoveryState) -> dict:
    """Run SymPy/Wolfram symbolic pre-check and update SQLite status."""
    sympy_result = symbolic_router.route_and_check(
        state["modified_latex_statement"],
        concept_type=state["concept_type"],
    )

    sympy_status = "unchecked"
    if sympy_result.passed is True:
        sympy_status = "passed"
    elif sympy_result.passed is False:
        sympy_status = "failed"

    discovery_id = state["discovery_id"]
    with get_session() as session:
        db_discovery = session.get(Discovery, discovery_id)
        if db_discovery is not None:
            db_discovery.sympy_check_status = sympy_status
            db_discovery.sympy_check_output = sympy_result.output

    return {
        "sympy_passed": sympy_result.passed,
        "sympy_output": sympy_result.output,
        "sympy_status": sympy_status,
    }


def formalize(state: DiscoveryState) -> dict:
    """Normalize LaTeX, run Lean 4 formalizer, and update SQLite status."""
    normalized_latex = latex_normalizer.normalize(state["modified_latex_statement"])
    formalization_result = formalizer.formalize(
        latex_statement=normalized_latex,
        concept_name=state["name"],
        provider=_primary_default,
        max_attempts=3,
    )

    lean_status = "verified" if formalization_result.success else "failed"
    discovery_id = state["discovery_id"]

    with get_session() as session:
        db_discovery = session.get(Discovery, discovery_id)
        if db_discovery is not None:
            db_discovery.lean_verification_status = lean_status
            db_discovery.lean_output = formalization_result.final_lean_output

    return {
        "lean_success": formalization_result.success,
        "lean_output": formalization_result.final_lean_output,
        "lean_status": lean_status,
    }


def analyze_graph(state: DiscoveryState) -> dict:
    """Build fresh graph from SQLite, run impact traversal and conflict detection."""
    base_concept_id = state["base_concept_id"]
    if not base_concept_id or state["base_concept"] is None:
        return {"affected": {}, "conflict_ids": []}

    g = knowledge_graph.build_graph()
    affected = knowledge_graph.get_impact_subgraph(g, base_concept_id)
    conflict_ids = knowledge_graph.find_potential_conflicts(g, base_concept_id)

    return {"affected": affected, "conflict_ids": conflict_ids}


def explain_impacts(state: DiscoveryState) -> dict:
    """Ask LLM to explain each affected concept's impact."""
    affected = state["affected"]
    base_concept_dict = state["base_concept"]

    if not affected or not base_concept_dict:
        return {"impacts": []}

    discovery_create = DiscoveryCreate(
        name=state["name"],
        base_concept_id=state["base_concept_id"],
        modified_latex_statement=state["modified_latex_statement"],
        modification_description=state["modification_description"],
    )
    base_concept = ConceptRead.model_validate(base_concept_dict)

    try:
        results = impact_explainer.explain_impacts(
            discovery=discovery_create,
            base_concept=base_concept,
            affected=affected,
            provider=_cheap_default,
        )
        return {"impacts": [dataclasses.asdict(i) for i in results]}
    except Exception as exc:
        logger.warning("Impact explanation failed for discovery %s: %s", state["discovery_id"], exc)
        return {"impacts": []}


def explain_conflicts(state: DiscoveryState) -> dict:
    """Ask LLM to explain each potential conflict."""
    conflict_ids = state["conflict_ids"]
    base_concept_dict = state["base_concept"]

    if not conflict_ids or not base_concept_dict:
        return {"conflict_explanations": []}

    discovery_create = DiscoveryCreate(
        name=state["name"],
        base_concept_id=state["base_concept_id"],
        modified_latex_statement=state["modified_latex_statement"],
        modification_description=state["modification_description"],
    )
    base_concept = ConceptRead.model_validate(base_concept_dict)

    try:
        results = conflict_explainer.explain_conflicts(
            discovery=discovery_create,
            base_concept=base_concept,
            conflict_ids=conflict_ids,
            provider=_cheap_default,
        )
        return {"conflict_explanations": [dataclasses.asdict(e) for e in results]}
    except Exception as exc:
        logger.warning(
            "Conflict explanation failed for discovery %s: %s", state["discovery_id"], exc
        )
        return {"conflict_explanations": []}


def persist_impacts(state: DiscoveryState) -> dict:
    """Write DiscoveryImpact rows to SQLite and mark the pipeline done."""
    discovery_id = state["discovery_id"]
    for impact_dict in state["impacts"]:
        impact_id = str(uuid.uuid4())
        try:
            with get_session() as session:
                db_impact = DiscoveryImpact(
                    id=impact_id,
                    discovery_id=discovery_id,
                    affected_concept_id=impact_dict["affected_concept_id"],
                    impact_type=impact_dict["impact_type"],
                    description=impact_dict["description"],
                    confidence_score=impact_dict["confidence_score"],
                )
                session.add(db_impact)
        except Exception as exc:
            logger.warning("Failed to persist impact %s: %s", impact_id, exc)

    return {"status": "done"}


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_discovery_graph(checkpointer):
    """Compile and return the discovery StateGraph with the given checkpointer."""
    workflow = StateGraph(DiscoveryState)

    workflow.add_node("initialize", initialize)
    workflow.add_node("symbolic_check", symbolic_check)
    workflow.add_node("formalize", formalize)
    workflow.add_node("analyze_graph", analyze_graph)
    workflow.add_node("explain_impacts", explain_impacts)
    workflow.add_node("explain_conflicts", explain_conflicts)
    workflow.add_node("persist_impacts", persist_impacts)

    workflow.set_entry_point("initialize")
    workflow.add_edge("initialize", "symbolic_check")
    workflow.add_edge("symbolic_check", "formalize")
    workflow.add_edge("formalize", "analyze_graph")
    workflow.add_edge("analyze_graph", "explain_impacts")
    workflow.add_edge("explain_impacts", "explain_conflicts")
    workflow.add_edge("explain_conflicts", "persist_impacts")
    workflow.add_edge("persist_impacts", END)

    return workflow.compile(checkpointer=checkpointer)
