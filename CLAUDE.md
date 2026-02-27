# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**HEAVEN** — an AI-native research assistant for mathematicians. Users apply new properties to existing mathematical concepts and the system shows what changes, what conflicts arise, how other concepts are affected, and where corrections can be made. Theoretical discoveries can then be stress-tested against real-world scenarios.

Three planned layers (implement in order):
1. **Data Layer** ← current focus
2. **Model Layer** — LLM orchestration, autoformalization, concept extraction
3. **Orchestration Layer** — session management, user-facing API

## Development Setup

All server code is Python. Use `uv` as the package manager.

```bash
cd server

# Install dependencies
uv sync

# Run database migrations
uv run alembic upgrade head

# Run tests
uv run pytest

# Lint
uv run ruff check src/
uv run ruff format src/

# Run a single test file
uv run pytest tests/path/to/test_file.py

# Run a single test by name
uv run pytest -k "test_name"
```

## Architecture

### Storage — what goes where

| Store | Contents |
|---|---|
| SQLite (`heaven.db`) | Structured relational data: papers metadata, extracted concepts, graph relationships, discoveries, impact analysis results |
| ChromaDB (`chroma_data/`) | Vector embeddings: concept statements (for semantic search), paper abstracts |
| NetworkX (in-memory) | Live knowledge graph reconstructed from SQLite `concept_relationships` at startup |

**Paper content is never stored.** Only metadata (title, authors, abstract, arXiv ID, DOI, URL) is persisted. Full paper text is fetched on demand from external APIs and discarded after concept extraction.

### Key Data Flow

```
User query
  → ChromaDB semantic search (concepts + paper abstracts)
  → Identify relevant papers by metadata
  → Fetch paper content live (arXiv ar5iv / Scholar)
  → Model layer extracts concepts (not yet implemented)
  → Store extracted concepts in SQLite + ChromaDB
  → Build NetworkX edges from concept relationships
  → Discard raw paper content

User creates a Discovery (modification to a concept)
  → SymPy pre-check (fast, symbolic) → src/verification/sympy_check.py
  → Model layer autoformalizes to Lean 4 syntax (not yet implemented)
  → Lean 4 formal verification → src/verification/lean.py
  → NetworkX impact traversal → src/graph/knowledge_graph.py
  → Store discovery + impacts in SQLite
```

### Module Map

```
server/
├── src/
│   ├── config.py                   # Pydantic settings from .env
│   ├── db/
│   │   ├── sqlite/
│   │   │   ├── models.py           # SQLAlchemy ORM (Paper, Concept, ConceptRelationship, Discovery, DiscoveryImpact)
│   │   │   └── session.py          # get_session() context manager
│   │   └── chroma/
│   │       └── collections.py      # ChromaDB get/upsert/query helpers
│   ├── graph/
│   │   └── knowledge_graph.py      # build_graph(), get_impact_subgraph(), get_dependencies(), find_potential_conflicts()
│   ├── ingestion/
│   │   ├── arxiv_client.py         # On-demand arXiv search + fetch
│   │   ├── wolfram_client.py       # On-demand Wolfram Alpha queries
│   │   ├── scholar_client.py       # On-demand Semantic Scholar search
│   │   └── extractor.py            # Concept extraction stub (requires model layer)
│   ├── verification/
│   │   ├── sympy_check.py          # Symbolic pre-verification (fast)
│   │   └── lean.py                 # Lean 4 subprocess wrapper (authoritative)
│   └── schemas/
│       └── models.py               # Pydantic schemas for all entities
└── alembic/                        # Database migrations
    └── versions/001_initial_schema.py
```

### SQLite Schema (key tables)

- **`papers`** — metadata only; `arxiv_id` and `doi` are unique keys
- **`concepts`** — extracted mathematical knowledge; `concept_type` is one of: theorem, definition, lemma, axiom, conjecture, corollary, proposition
- **`concept_relationships`** — persisted graph edges; `relationship_type` is one of: proves, depends_on, generalizes, is_special_case_of, contradicts, cited_by, equivalent_to, extends
- **`discoveries`** — user mutations of concepts; has both `sympy_check_status` and `lean_verification_status`
- **`discovery_impacts`** — what a discovery affects; `impact_type` is one of: extends, contradicts, generalizes, enables, invalidates

### Data Sources

| Source | Client | Notes |
|---|---|---|
| arXiv | `src/ingestion/arxiv_client.py` | Uses ar5iv.org HTML for structured content |
| Semantic Scholar | `src/ingestion/scholar_client.py` | Preferred over Google Scholar scraping |
| Wolfram Alpha | `src/ingestion/wolfram_client.py` | Requires `WOLFRAM_APP_ID` in `.env` |

### Verification Pipeline

Two-stage: SymPy first (cheap, catches most hallucinations), then Lean 4 (authoritative).

**Lean 4 prerequisites** — must be set up manually before `src/verification/lean.py` is usable:
1. Install Lean 4 via elan: `curl https://elan.lean-lang.org/elan-init.sh -sSf | sh`
2. Fetch pre-compiled Mathlib binaries (never compile from scratch — takes hours):
   `cd server/lean_project && lake exe cache get`
3. Verify setup: `lake env lean HEAVEN/Basic.lean` — should print nothing (no errors)

The lean_project is already scaffolded at `server/lean_project/`. `lake env lean <file>` is used (not bare `lean <file>`) so Mathlib imports resolve correctly.

**Autoformalization** (LaTeX → Lean 4 syntax) is handled by the model layer — not yet implemented. `lean.py` assumes it receives valid Lean 4 source.

### Embeddings

Default embedding model: `all-MiniLM-L6-v2` (via `sentence-transformers`). Configured via `EMBEDDING_MODEL` in `.env`. This is a placeholder — swap for a math-aware model when the model layer is decided. ChromaDB uses cosine similarity.

### MSC Codes

Mathematics Subject Classification codes are stored as JSON arrays on both `papers` and `concepts`. Use standard 2-digit or 5-character MSC codes (e.g., `"57"` for Manifolds, `"11A41"` for Primes). arXiv does not expose MSC codes directly — they must be inferred or manually assigned.
