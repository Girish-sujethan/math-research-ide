# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**HEAVEN** — an AI-native research assistant for mathematicians. Users apply new properties to existing mathematical concepts and the system shows what changes, what conflicts arise, how other concepts are affected, and where corrections can be made. Theoretical discoveries can then be stress-tested against real-world scenarios.

Three planned layers (implement in order):
1. **Data Layer** ✓ complete
2. **Model Layer** ✓ complete — LLM orchestration, autoformalization, concept extraction
3. **Orchestration Layer** ✓ complete — FastAPI server, LangGraph pipelines, chat endpoint

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
| SQLite (`heaven_checkpoints.db`) | LangGraph checkpoint state for all pipeline runs — enables resume after failure |
| ChromaDB (`chroma_data/`) | Vector embeddings: concept statements (for semantic search), paper abstracts |
| NetworkX (on-demand) | Knowledge graph rebuilt from SQLite on every call to `build_graph()` — no shared in-memory instance |

**Paper content is never stored.** Only metadata (title, authors, abstract, arXiv ID, DOI, URL) is persisted. Full paper text is fetched on demand from external APIs and discarded after concept extraction.

### Key Data Flow

```
User triggers paper ingest (POST /papers/ingest)
  → arxiv_client.fetch_by_id() — get metadata
  → Persist Paper row to SQLite
  → Spawn background asyncio task (asyncio.create_task)
  → ingestion_graph.invoke(IngestionState, config={thread_id})
      Node 1: fetch_content          — arxiv_client.fetch_content_transiently()
      Node 2: extract_and_persist    — chunk → LLM extract → dedup → SQLite + ChromaDB
      Node 3: classify_msc           — LLM MSC codes → SQLite update
      Node 4: extract_relationships  — LLM relationships → SQLite
  → Each node checkpointed to heaven_checkpoints.db
  → GET /papers/ingest/{job_id} polls snapshot.values["status"]
  → POST /papers/ingest/{job_id}/resume replays from last checkpoint on failure

User creates a Discovery (POST /discoveries)
  → Spawn background asyncio task
  → discovery_graph.invoke(DiscoveryState, config={thread_id})
      Node 1: initialize        — persist Discovery row, load base concept
      Node 2: symbolic_check    — SymPy/Wolfram → update SQLite status
      Node 3: formalize         — LaTeX normalize + Lean 4 → update SQLite
      Node 4: analyze_graph     — build_graph() on-demand → impact + conflict traversal
      Node 5: explain_impacts   — LLM → impacts list
      Node 6: explain_conflicts — LLM → conflict explanations
      Node 7: persist_impacts   — DiscoveryImpact rows → SQLite; status="done"
  → POST /discoveries/jobs/{job_id}/resume replays from last checkpoint on failure
```

### Module Map

```
server/
├── src/
│   ├── config.py                   # Pydantic settings from .env (incl. anthropic_api_key)
│   ├── db/
│   │   ├── sqlite/
│   │   │   ├── models.py           # SQLAlchemy ORM (Paper, Concept, ConceptRelationship, Discovery, DiscoveryImpact)
│   │   │   └── session.py          # get_session() context manager
│   │   └── chroma/
│   │       └── collections.py      # ChromaDB get/upsert/query helpers
│   ├── graph/
│   │   └── knowledge_graph.py      # build_graph(), get_impact_subgraph(), get_dependencies(), find_potential_conflicts()
│   │                               # No shared state — every caller builds a fresh graph from SQLite
│   ├── ingestion/
│   │   ├── arxiv_client.py         # On-demand arXiv search + fetch
│   │   ├── wolfram_client.py       # On-demand Wolfram Alpha queries
│   │   └── extractor.py            # Delegates to model/extraction/concept_extractor.py
│   ├── model/                      # ← Model layer
│   │   ├── providers/
│   │   │   ├── base.py             # LLMProvider ABC + LLMResponse dataclass
│   │   │   ├── claude.py           # ClaudeProvider (Anthropic SDK)
│   │   │   ├── openai_compatible.py# OpenAICompatibleProvider (httpx; OpenRouter/DeepSeek/Gemini/vLLM)
│   │   │   └── registry.py         # primary + cheap singletons resolved from .env settings
│   │   ├── extraction/
│   │   │   ├── chunker.py          # chunk_paper(): LaTeX-env-aware text splitter
│   │   │   ├── concept_extractor.py# extract_concepts(): LLM → list[ExtractedConcept]
│   │   │   ├── relationship_extractor.py # extract_relationships(): LLM → list[PendingRelationship]
│   │   │   └── deduplicator.py     # find_duplicate(): ChromaDB + LLM duplicate check
│   │   ├── formalization/
│   │   │   ├── latex_normalizer.py # normalize(): pure-text LaTeX cleanup
│   │   │   └── formalizer.py       # formalize(): LaTeX → Lean 4 with retry loop
│   │   ├── symbolic/
│   │   │   └── router.py           # route_and_check(): SymPy → Wolfram → SKIP heuristic
│   │   ├── reasoning/
│   │   │   ├── conflict_explainer.py # explain_conflicts(): LLM severity + explanation per conflict
│   │   │   ├── impact_explainer.py # explain_impacts(): batched LLM impact descriptions
│   │   │   └── msc_classifier.py   # classify_msc(): LLM → MSC 2020 code list
│   │   └── graphs/                 # ← LangGraph pipeline implementations
│   │       ├── checkpointer.py     # get_checkpointer() → SqliteSaver on heaven_checkpoints.db
│   │       ├── ingestion_graph.py  # 4-node StateGraph: IngestionState, build_ingestion_graph()
│   │       └── discovery_graph.py  # 7-node StateGraph: DiscoveryState, build_discovery_graph()
│   ├── verification/
│   │   ├── sympy_check.py          # Symbolic pre-verification (fast)
│   │   └── lean.py                 # Lean 4 subprocess wrapper (authoritative)
│   ├── api/                        # ← Orchestration layer
│   │   ├── app.py                  # FastAPI factory + lifespan: compiles both LangGraph pipelines
│   │   ├── dependencies.py         # FastAPI Depends(): get_ingestion_graph, get_discovery_graph,
│   │   │                           #   get_running_threads, get_thread_metadata, get_sessions
│   │   ├── schemas.py              # API request/response models (JobStatus, ChatRequest, …)
│   │   └── routers/
│   │       ├── papers.py           # POST /papers/ingest → ingestion_graph; GET status; POST resume
│   │       ├── concepts.py         # GET /concepts; POST /concepts/search; GET /concepts/{id}/impact
│   │       ├── discoveries.py      # POST /discoveries → discovery_graph; GET status; POST resume
│   │       ├── relationships.py    # GET/POST /relationships (SQLite only — no graph mutation)
│   │       ├── search.py           # POST /search — cross-entity ChromaDB semantic search
│   │       └── chat.py             # POST /chat — LLM intent detection + session history
│   └── schemas/
│       └── models.py               # Pydantic schemas for all entities
├── main.py                         # Entry point: uv run uvicorn main:app --reload
└── alembic/                        # Database migrations
    └── versions/001_initial_schema.py
```

### Model Layer — LLM Selection

Models are configured via `.env`. The registry exports two singletons used throughout the codebase:
- `registry.primary` — high-capability model; used for extraction, formalization, relationship reasoning
- `registry.cheap` — cost-optimised model; used for dedup confirmation, MSC classification, impact/conflict descriptions

| Task | Provider role | Rationale |
|---|---|---|
| Concept extraction | `primary` | High accuracy needed; math notation is complex |
| Relationship extraction | `primary` | Semantic reasoning between statements |
| Autoformalization (LaTeX → Lean 4) | `primary` | Code generation requires strong reasoning |
| Deduplication confirmation | `cheap` | Binary yes/no; cost-sensitive at scale |
| MSC classification | `cheap` | Classification from fixed taxonomy; simple |
| Impact/conflict explanation | `cheap` | Descriptions, not mathematical proofs |

To switch providers, edit `.env` — no code changes needed. Supported values for `PRIMARY_PROVIDER` / `CHEAP_PROVIDER`:
- `"claude"` — Anthropic API (requires `ANTHROPIC_API_KEY`)
- `"openai_compatible"` — any OpenAI-format API (requires `OPENAI_API_KEY` + `OPENAI_BASE_URL`)

### Model Layer — Key Design Decisions

- **Synchronous throughout** — matches data layer; async deferred to orchestration layer.
- **Formalizer retry strategy** — up to 3 LLM+Lean rounds. Each failure feeds Lean error output back to the LLM as a correction request. Early-abort if consecutive rounds produce identical errors.
- **Deduplication threshold** — ChromaDB cosine distance ≤ 0.08 (i.e., similarity ≥ 0.92) triggers an LLM confirmation step before declaring a duplicate.
- **Partial ingestion** — chunk-level failures are logged and skipped; a paper is never fully rejected due to a single bad chunk.
- **No content stored** — the ingestion graph node receives transiently fetched text and discards it; only structured concepts are persisted.

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
| Wolfram Alpha | `src/ingestion/wolfram_client.py` | Requires `WOLFRAM_APP_ID` in `.env` |

### Verification Pipeline

Two-stage: SymPy first (cheap, catches most hallucinations), then Lean 4 (authoritative).

**Lean 4 prerequisites** — must be set up manually before `src/verification/lean.py` is usable:
1. Install Lean 4 via elan: `curl https://elan.lean-lang.org/elan-init.sh -sSf | sh`
2. Fetch pre-compiled Mathlib binaries (never compile from scratch — takes hours):
   `cd server/lean_project && lake exe cache get`
3. Verify setup: `lake env lean HEAVEN/Basic.lean` — should print nothing (no errors)

The lean_project is already scaffolded at `server/lean_project/`. `lake env lean <file>` is used (not bare `lean <file>`) so Mathlib imports resolve correctly.

**Autoformalization** (LaTeX → Lean 4 syntax) is handled by `src/model/formalization/formalizer.py`. `lean.py` assumes it receives valid Lean 4 source.

### Embeddings

Default embedding model: `all-MiniLM-L6-v2` (via `sentence-transformers`). Configured via `EMBEDDING_MODEL` in `.env`. This is a placeholder — swap for a math-aware model when the model layer is decided. ChromaDB uses cosine similarity.

### MSC Codes

Mathematics Subject Classification codes are stored as JSON arrays on both `papers` and `concepts`. Use standard 2-digit or 5-character MSC codes (e.g., `"57"` for Manifolds, `"11A41"` for Primes). arXiv does not expose MSC codes directly — they must be inferred or manually assigned.

### Orchestration Layer — Startup Contract

The lifespan in `src/api/app.py` handles all startup logic automatically. At startup it:

1. Calls `init_db()` — creates all SQLite tables (idempotent)
2. Calls `get_checkpointer()` — opens a connection to `heaven_checkpoints.db`
3. Compiles both LangGraph pipelines with the checkpointer:

```python
app.state.ingestion_graph = build_ingestion_graph(checkpointer)
app.state.discovery_graph = build_discovery_graph(checkpointer)
app.state.running_threads = set()     # in-flight thread IDs (status cache)
app.state.thread_metadata = {}        # {thread_id: {"paper_id": ..., "error": ...}}
app.state.sessions = {}               # chat session history
```

**There is no `app.state.graph`.** The NetworkX graph is built on-demand by each caller via `knowledge_graph.build_graph()` (reconstructed fresh from SQLite). This eliminates shared-mutable-graph issues and the need for any locks.

### Orchestration Layer — Pipeline Invocation

Both pipelines are invoked via `asyncio.to_thread` inside a background `asyncio.create_task`:

```python
# Paper ingestion
config = {"configurable": {"thread_id": thread_id}}
initial_state: IngestionState = {
    "paper_id": paper_id, "arxiv_id": arxiv_id, "content": None,
    "extracted_concepts": [], "name_to_id": {}, "new_concept_ids": [],
    "concepts_created": 0, "concepts_deduplicated": 0, "relationships_created": 0,
    "status": "running",
}
ingestion_graph.invoke(initial_state, config)   # runs in asyncio.to_thread

# Discovery processing
initial_state: DiscoveryState = { ...all fields from DiscoveryCreate... }
discovery_graph.invoke(initial_state, config)   # runs in asyncio.to_thread

# Resuming after failure (re-invokes from last checkpoint node)
ingestion_graph.invoke(None, config)
discovery_graph.invoke(None, config)
```

### Orchestration Layer — Job Status Polling

```python
# Status derivation for GET /papers/ingest/{job_id} and GET /discoveries/jobs/{job_id}

meta = thread_metadata.get(job_id)
if meta is None:
    raise HTTPException(404)

if job_id in running_threads:
    return RUNNING

snapshot = graph.get_state({"configurable": {"thread_id": job_id}})
if snapshot is None or not snapshot.values:
    return PENDING   # registered but task hasn't started yet

if snapshot.values.get("status") == "done":
    return DONE      # read result fields from snapshot.values

return FAILED        # interrupted — error string in thread_metadata[job_id]["error"]
```