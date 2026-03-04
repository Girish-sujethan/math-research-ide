# HEAVEN — Project Overview

> **H**euristic **E**valuation and **A**nalysis of **V**erifiable **E**volutionary **N**umber-theory

An AI-native research assistant for mathematicians. Users propose modifications to existing mathematical concepts — the system extracts, formalizes, and stress-tests those modifications against a growing knowledge base of ingested papers.

---

## Table of Contents

1. [What It Does](#1-what-it-does)
2. [Tech Stack](#2-tech-stack)
3. [Repository Layout](#3-repository-layout)
4. [Core Use Cases](#4-core-use-cases)
5. [Data Layer](#5-data-layer)
6. [Model Layer](#6-model-layer)
7. [Orchestration Layer (Server)](#7-orchestration-layer-server)
8. [Client Layer](#8-client-layer)
9. [Key Workflows End-to-End](#9-key-workflows-end-to-end)
10. [LLM Provider System](#10-llm-provider-system)
11. [Verification Pipeline](#11-verification-pipeline)
12. [Configuration Reference](#12-configuration-reference)
13. [Running the Project](#13-running-the-project)
14. [Test Suite](#14-test-suite)

---

## 1. What It Does

HEAVEN gives mathematicians a structured environment to:

- **Ingest papers** from arXiv, DOI (CrossRef), or PDF upload — concepts are automatically extracted, deduplicated, embedded, and stored in a searchable knowledge base.
- **Explore the knowledge graph** — every concept, theorem, lemma, and definition is linked by typed relationships (proves, depends_on, contradicts, generalizes, etc.).
- **Propose discoveries** — modify a concept's LaTeX statement and instantly see which downstream concepts are affected, what conflicts arise, and how severe those conflicts are.
- **Verify formally** — modifications are passed through SymPy (fast symbolic check), then optionally through Lean 4 (authoritative proof assistant).
- **Chat with HEAVEN** — a conversational AI agent grounded in staged papers produces structured reasoning that is written directly into the block editor.
- **Write research** — a three-pane IDE (Knowledge Vault / Block Editor / Reasoning Engine) lets users draft LaTeX documents, get inline AI suggestions via Cmd+K, and receive automatic fact-checks and proactive nudges from staged sources.
- **Run computations** — a Python Visualization agent executes NumPy/SciPy/Matplotlib code in a sandboxed subprocess and embeds the output (plot + stdout) as a native document block.

---

## 2. Tech Stack

### Server

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11 |
| Package manager | `uv` |
| HTTP server | FastAPI + Uvicorn |
| Pipeline orchestration | LangGraph (`StateGraph` + `SqliteSaver`) |
| Relational DB | SQLite via SQLAlchemy 2.0 |
| Vector DB | ChromaDB (cosine similarity, `all-MiniLM-L6-v2`) |
| Knowledge graph | NetworkX (built on-demand from SQLite) |
| Symbolic math | SymPy + Wolfram Alpha |
| Formal verification | Lean 4 + Mathlib (subprocess) |
| Computation | NumPy · SciPy · Matplotlib (Python subprocess sandbox) |
| LLM (primary) | Claude Sonnet 4.6 (or any OpenAI-compatible endpoint) |
| LLM (cheap) | Claude Haiku 4.5 (or any OpenAI-compatible endpoint) |
| Migrations | Alembic |

### Client

| Layer | Technology |
|-------|-----------|
| Framework | Next.js 16 (App Router) |
| Language | TypeScript |
| Styling | Tailwind CSS v4 |
| Block editor | BlockNote.js v0.47 |
| LaTeX rendering | KaTeX (inline + block) |
| State management | Zustand (localStorage-persisted) |
| Server state | TanStack React Query |
| Icons | Lucide React |

---

## 3. Repository Layout

```
HEAVEN/
├── server/                         # Python FastAPI backend
│   ├── src/
│   │   ├── config.py               # Pydantic settings (reads .env)
│   │   ├── api/                    # HTTP routes + schemas
│   │   │   ├── app.py              # FastAPI factory + lifespan
│   │   │   ├── dependencies.py     # FastAPI Depends() injectors
│   │   │   ├── schemas.py          # API request/response models
│   │   │   └── routers/
│   │   │       ├── chat.py         # POST /chat
│   │   │       ├── papers.py       # POST /papers/ingest, GET /papers
│   │   │       ├── concepts.py     # GET /concepts, POST /concepts/search
│   │   │       ├── discoveries.py  # POST /discoveries, GET status
│   │   │       ├── relationships.py# GET/POST /relationships
│   │   │       ├── search.py       # POST /search (cross-entity)
│   │   │       ├── research.py     # Deep research synthesis
│   │   │       ├── upload.py       # POST /papers/upload (PDF)
│   │   │       ├── verify.py       # POST /verify/nudge
│   │   │       └── agents/
│   │   │           ├── matlab.py   # POST /agents/python-visual (Python visualization)
│   │   │           └── fact_check.py # POST /agents/fact-check
│   │   ├── db/
│   │   │   ├── sqlite/
│   │   │   │   ├── models.py       # SQLAlchemy ORM models
│   │   │   │   └── session.py      # get_session() context manager
│   │   │   └── chroma/
│   │   │       └── collections.py  # ChromaDB upsert/query helpers
│   │   ├── graph/
│   │   │   └── knowledge_graph.py  # NetworkX ops (build, impact, conflicts)
│   │   ├── ingestion/
│   │   │   ├── arxiv_client.py     # arXiv API + ar5iv HTML parsing
│   │   │   ├── wolfram_client.py   # Wolfram Alpha integration
│   │   │   └── extractor.py        # Delegates to model/extraction/
│   │   ├── model/
│   │   │   ├── providers/          # LLM abstraction + registry
│   │   │   ├── extraction/         # Concept + relationship extraction
│   │   │   ├── formalization/      # LaTeX → Lean 4
│   │   │   ├── symbolic/           # SymPy/Wolfram routing
│   │   │   ├── reasoning/          # Impact/conflict/MSC explanation
│   │   │   └── graphs/             # LangGraph pipelines
│   │   │       ├── ingestion_graph.py  # 4-node ingestion pipeline
│   │   │       └── discovery_graph.py  # 7-node discovery pipeline
│   │   └── verification/
│   │       ├── sympy_check.py      # Symbolic pre-verification
│   │       └── lean.py             # Lean 4 subprocess wrapper
│   ├── tests/                      # Pytest suite (65 tests)
│   ├── alembic/                    # DB migrations
│   ├── heaven.db                   # Main SQLite database
│   ├── heaven_checkpoints.db       # LangGraph checkpoint store
│   ├── chroma_data/                # ChromaDB vector store
│   ├── lean_project/               # Lean 4 project scaffolding
│   ├── main.py                     # Uvicorn entry point
│   └── pyproject.toml              # uv dependency config
│
├── client/                         # Next.js TypeScript frontend
│   ├── app/
│   │   ├── workspace/page.tsx      # Main three-pane IDE
│   │   ├── concepts/page.tsx       # Concept browser
│   │   ├── papers/page.tsx         # Paper library
│   │   └── discoveries/page.tsx    # Discovery viewer
│   ├── components/
│   │   ├── knowledge-vault/        # Paper search + staging UI
│   │   ├── editor/
│   │   │   ├── blocknote-editor.tsx    # BlockNote editor with custom schema
│   │   │   ├── latex-block.tsx         # Custom LaTeX block (KaTeX live preview)
│   │   │   ├── matlab-output-block.tsx # Python visualization output block
│   │   │   ├── matlab-runner.tsx       # Python Visualization code runner modal
│   │   │   └── cmd-k-toolbar.tsx       # Cmd+K floating AI edit palette
│   │   ├── agents/
│   │   │   └── fact-check-panel.tsx    # Manual fact-check UI (standalone)
│   │   └── reasoning-engine/
│   │       ├── reasoning-engine.tsx    # Chat + nudges + auto fact-check card
│   │       ├── thinking-block.tsx      # Collapsible AI reasoning
│   │       ├── source-chip.tsx         # Paper reference pill
│   │       └── proactive-nudges.tsx    # Staged-paper nudge list
│   └── lib/
│       ├── api.ts                  # Typed fetch wrappers
│       ├── types.ts                # TypeScript interfaces
│       ├── editor-store.ts         # Editor UI state (Zustand) + BlockNote ref helpers
│       ├── vault-store.ts          # Staged papers state (Zustand)
│       └── parse-reply-to-blocks.ts# AI reply → BlockNote block parser
│
└── OVERVIEW.md                     # This file
```

---

## 4. Core Use Cases

### Use Case A — Ingest a Paper
User searches arXiv or Exa → clicks Stage → the paper's concepts are extracted in the background. Concepts are chunked, deduplicated against ChromaDB, classified with MSC codes, and stored with their relationships. The staged paper then grounds the AI's chat responses and fact-checks.

### Use Case B — Write a Research Document
User opens the workspace, adds blocks (text, LaTeX, headings, bullets) using the BlockNote.js editor. They stage 1–2 papers and ask HEAVEN a question. The AI's response is parsed and written directly into the block editor. Cmd+K opens a floating toolbar to request inline AI edits — the new content replaces the block directly. A non-intrusive fact-check card then appears automatically in the reasoning engine showing whether the edit is supported/contradicted/uncertain against staged sources.

### Use Case C — Run a Computation
User types `/` and selects "Python Visualization" from the slash menu. A modal opens with a Python code editor (NumPy, SciPy, Matplotlib pre-imported). On Run, the server executes the code in a sandboxed subprocess (20s timeout), captures stdout and any Matplotlib figure as a base64 PNG, and inserts a `matlabOutput` block directly into the document.

### Use Case D — Propose a Discovery
User picks an existing concept and proposes a modified LaTeX statement (e.g., relaxing a condition on a theorem). The discovery pipeline runs in the background:
1. SymPy checks symbolic consistency.
2. Lean 4 attempts autoformalization.
3. The knowledge graph is traversed to find affected concepts (BFS, depth 3).
4. Conflicts are identified (contradicts edges).
5. An LLM explains the impact of the modification on each downstream concept.
6. Results are stored and displayed.

### Use Case E — Get Proactive Nudges
While editing, HEAVEN periodically scans the document blocks against staged papers via ChromaDB. If the document content semantically matches a staged concept, HEAVEN surfaces nudges: connections ("this relates to Lemma 3"), warnings ("your LaTeX differs from the staged source"), or expansion suggestions.

---

## 5. Data Layer

### Storage Systems

| Store | File | Contents |
|-------|------|----------|
| SQLite (main) | `heaven.db` | Papers, Concepts, Relationships, Discoveries, Impacts |
| SQLite (checkpoints) | `heaven_checkpoints.db` | LangGraph pipeline snapshots (for resumability) |
| ChromaDB | `chroma_data/` | Concept statement embeddings + paper abstract embeddings |
| NetworkX | (in-memory only) | Knowledge graph; rebuilt fresh from SQLite on every call |

**Paper content is never stored.** Only metadata (title, authors, abstract, arXiv ID, DOI) is persisted. Full text is fetched transiently during ingestion and discarded.

### SQLite Schema

**`papers`**
- `id`, `source_type` (arxiv/other), `arxiv_id` (unique), `doi` (unique), `title`, `authors` (JSON array), `abstract`, `url`, `pdf_url`, `published_at`, `msc_codes` (JSON array)

**`concepts`**
- `id`, `name`, `concept_type` (theorem/definition/lemma/axiom/conjecture/corollary/proposition), `latex_statement`, `description`, `msc_codes` (JSON), `source_paper_id` (FK), `lean_verification_status`, `chroma_embedding_id`

**`concept_relationships`**
- `id`, `source_concept_id` (FK), `target_concept_id` (FK), `relationship_type` (proves/depends_on/generalizes/is_special_case_of/contradicts/cited_by/equivalent_to/extends), `description`, `weight`, `source_paper_id` (FK)

**`discoveries`**
- `id`, `name`, `base_concept_id` (FK), `modified_latex_statement`, `modification_description`, `sympy_check_status`, `sympy_check_output`, `lean_verification_status`, `lean_output`

**`discovery_impacts`**
- `id`, `discovery_id` (FK), `affected_concept_id` (FK), `impact_type` (extends/contradicts/generalizes/enables/invalidates), `description`, `confidence_score`

### ChromaDB Collections

| Collection | What's embedded | Used for |
|-----------|----------------|---------|
| `concepts` | `latex_statement` of each Concept | Semantic deduplication, nudge generation, fact-check, concept search |
| `papers` | `abstract` of each Paper | Paper semantic search |

Embedding model: `all-MiniLM-L6-v2` (configurable via `EMBEDDING_MODEL` in `.env`). Similarity metric: cosine distance.

---

## 6. Model Layer

The model layer (`server/src/model/`) contains all LLM and symbolic logic. It is **synchronous throughout** — async is handled at the orchestration layer.

### 6.1 LLM Providers

`model/providers/` defines an `LLMProvider` ABC with a single `complete(prompt, system)` method. Two implementations:
- `ClaudeProvider` — Anthropic SDK, native `claude-*` models.
- `OpenAICompatibleProvider` — httpx, any OpenAI-format endpoint (DeepSeek, OpenRouter, Gemini, vLLM, etc.).

`model/providers/registry.py` exposes two singletons resolved from `.env`:
- `primary` — high-capability model; used for concept extraction, relationship extraction, autoformalization.
- `cheap` — cost-optimised model; used for deduplication confirmation, MSC classification, impact/conflict descriptions, nudge generation.

### 6.2 Concept Extraction

`model/extraction/concept_extractor.py`
- Input: text chunk (from `chunker.py` — LaTeX-environment-aware splitter).
- Output: `list[ExtractedConcept]` — each has `name`, `concept_type`, `latex_statement`, `description`, `msc_codes`.
- Prompt instructs the primary LLM to extract only definitions/theorems/lemmas (not prose).

`model/extraction/deduplicator.py`
- Before persisting, queries ChromaDB for existing concepts.
- If cosine distance ≤ 0.08 (similarity ≥ 0.92), calls the cheap LLM to confirm duplicate.
- Returns `existing_id` (merge) or `None` (new concept).

`model/extraction/relationship_extractor.py`
- Input: list of concept names/statements from a paper.
- Output: `list[PendingRelationship]` — typed edges between concepts.

### 6.3 Autoformalization

`model/formalization/formalizer.py`
- Converts a LaTeX statement to valid Lean 4 source.
- Retry loop (up to 3 rounds): on failure, Lean 4's error output is fed back to the LLM as a correction request.
- Aborts early if consecutive rounds produce identical errors (no progress).

`model/formalization/latex_normalizer.py`
- Pure-text LaTeX cleanup before formalization (removes display math delimiters, normalizes spacing).

### 6.4 Symbolic Verification

`model/symbolic/router.py` — routes to the right verifier:
1. SymPy (`verification/sympy_check.py`) — fast algebraic check; catches hallucinated equalities.
2. Wolfram Alpha (`ingestion/wolfram_client.py`) — fallback for expressions SymPy cannot parse.
3. SKIP — if the statement is too abstract for symbolic tools.

### 6.5 Knowledge Graph

`graph/knowledge_graph.py`
- `build_graph()` — queries all `Concept` and `ConceptRelationship` rows from SQLite; constructs a `networkx.DiGraph`. No shared instance — every call rebuilds from scratch.
- `get_impact_subgraph(G, concept_id, max_depth=3)` — BFS from a concept; returns all reachable concepts grouped by relationship type.
- `find_potential_conflicts(G, concept_id)` — returns concepts reachable via `contradicts` edges (bidirectional).

### 6.6 Reasoning

`model/reasoning/impact_explainer.py` — batched LLM: for each affected concept, describe how the discovery changes it.

`model/reasoning/conflict_explainer.py` — LLM: for each conflict pair, estimate severity and explain implications.

`model/reasoning/msc_classifier.py` — cheap LLM: given title + abstract, return a list of MSC 2020 codes.

---

## 7. Orchestration Layer (Server)

### 7.1 FastAPI App

`src/api/app.py` — FastAPI factory. Lifespan handler:
1. Runs `init_db()` — creates all SQLite tables (idempotent).
2. Opens checkpoint DB via `get_checkpointer()`.
3. Compiles both LangGraph pipelines: `ingestion_graph`, `discovery_graph`.
4. Initialises in-memory state caches on `app.state`:
   - `running_threads: set[str]` — thread IDs of currently executing jobs.
   - `thread_metadata: dict[str, dict]` — `{job_id: {paper_id, error?}}`.
   - `sessions: dict[str, list]` — chat session history (rolling 20 turns).

### 7.2 Ingestion Pipeline (4 nodes)

File: `model/graphs/ingestion_graph.py`

```
fetch_content → extract_and_persist_concepts → classify_msc → extract_and_persist_relationships
```

| Node | What it does |
|------|-------------|
| `fetch_content` | Fetches ar5iv HTML → LaTeX-friendly plain text. Skipped if content already provided (PDF upload path). |
| `extract_and_persist_concepts` | Chunks paper → LLM extracts concepts → deduplicates vs ChromaDB → persists new Concepts to SQLite + ChromaDB. |
| `classify_msc` | LLM classifies MSC 2020 codes from title + abstract → updates Paper row. |
| `extract_and_persist_relationships` | LLM extracts typed edges between extracted concepts → persists ConceptRelationship rows. Sets `status="done"`. |

Each node is checkpointed to `heaven_checkpoints.db`. On failure, `POST /papers/ingest/{job_id}/resume` re-invokes the graph with `None` state — LangGraph replays from the last successful checkpoint node.

### 7.3 Discovery Pipeline (7 nodes)

File: `model/graphs/discovery_graph.py`

```
initialize → symbolic_check → formalize → analyze_graph → explain_impacts → explain_conflicts → persist_impacts
```

| Node | What it does |
|------|-------------|
| `initialize` | Persists Discovery row to SQLite. Loads base concept if provided. |
| `symbolic_check` | Runs SymPy/Wolfram on the modified LaTeX. Updates `sympy_check_status`. |
| `formalize` | Normalizes LaTeX → Lean 4 formalization (retry ×3). Updates `lean_verification_status`. |
| `analyze_graph` | Rebuilds NetworkX graph from SQLite. BFS for affected concepts (depth 3). Detects conflict edges. |
| `explain_impacts` | Cheap LLM: per-concept impact description. |
| `explain_conflicts` | Cheap LLM: conflict severity + implications. |
| `persist_impacts` | Writes DiscoveryImpact rows to SQLite. Sets `status="done"`. |

### 7.4 Job Status Polling Pattern

Used by both `/papers/ingest/{job_id}` and `/discoveries/jobs/{job_id}`:

```
thread_metadata[job_id] is None       → 404 Not Found
job_id in running_threads             → RUNNING
snapshot is None or empty             → PENDING  (registered but not started)
snapshot.values["status"] == "done"   → DONE     (read result from snapshot)
else                                  → FAILED   (error in thread_metadata[job_id]["error"])
```

### 7.5 Chat Endpoint

`src/api/routers/chat.py` — the autonomous chat agent.

**Request:** `{message, session_id?, context: {staged_paper_ids, canvas_summary}}`

**Flow:**
1. Load session history from `app.state.sessions`.
2. Load staged papers + top-8 concepts per paper from SQLite (`_load_staged_papers`).
3. Build contextual system prompt (`_build_system`):
   - No staged papers → appends: *"No papers staged. Prompt user to Stage a Source."*
   - With staged papers → injects paper titles, abstracts, extracted concepts + document summary.
4. Call primary LLM. Parse structured JSON: `{thinking, reply, sources, action?}`.
5. Execute action if present (search concepts, ingest paper, create discovery — all without confirmation).
6. Store turn in session history (trim to 20 turns).
7. Return `ChatResponse` with `reply`, `thinking`, `sources`, `session_id`, `canvas_items`.

**On the client**, the reasoning engine parses `reply` into typed blocks via `parse-reply-to-blocks.ts` and inserts them into the BlockNote editor automatically.

### 7.6 Nudge Endpoint

`src/api/routers/verify.py` — `POST /verify/nudge`

1. For each block with ≥ 20 characters, query ChromaDB for nearest concepts.
2. Distance < 0.2 → "connection" nudge (related concept found).
3. Distance < 0.15 + LaTeX differs → "warning" nudge (your statement disagrees with source).
4. Cheap LLM → up to 2 "expansion" nudges suggesting deeper use of staged papers.
5. Deduplicates, returns top 5.

### 7.7 Agent Endpoints

#### Python Visualization Agent — `POST /agents/python-visual`

File: `src/api/routers/agents/matlab.py`

**Request:** `{code: str, title?: str}`

**Flow:**
1. Safety check: reject patterns that import `os`, `subprocess`, `socket`, `sys.exit`, file writes, etc.
2. Wrap user code in a preamble that imports numpy, scipy, matplotlib, and captures stdout + matplotlib figures.
3. Execute in a temp file via `subprocess.run([sys.executable, tmp], timeout=20)`.
4. Parse JSON from stdout: `{output, image, error}`.
5. Return `PythonVisualResponse {output, image_base64, error}`.

**On the client**, the Python Visualization runner modal (`matlab-runner.tsx`) sends the code and inserts a `matlabOutput` block (dark header + collapsible source + plot image + stdout) at the cursor position.

#### Fact-Check Agent — `POST /agents/fact-check`

File: `src/api/routers/agents/fact_check.py`

**Request:** `{statement: str, staged_paper_ids: list[str]}`

**Flow:**
1. Query ChromaDB `concepts` collection for the top 6 semantically nearest concepts.
2. Load full metadata for any concept whose `source_paper_id` is in `staged_paper_ids`.
3. Build a system prompt instructing the primary LLM to grade the statement as `supported | contradicted | uncertain` with a 0–1 confidence score, explanation, supporting evidence, issues, and an optional suggestion.
4. Return `FactCheckResponse`.

**On the client**, this is triggered **automatically** (fire-and-forget) after every successful Cmd+K edit. The result appears as a non-intrusive coloured card in the reasoning engine panel — green for supported, red for contradicted, amber for uncertain — and is dismissed with ×.

---

## 8. Client Layer

### 8.1 Three-Pane IDE (`/workspace`)

```
+---- Knowledge Vault (260px) ----+------ BlockNote Editor (flex-1) ---+--- Reasoning Engine (320px) ---+
|                                 |                                     |                                |
| [Search arXiv / Exa]            | # Heading block                    | Reasoning Engine               |
| [Upload PDF] [DOI import]       | Paragraph block                    |                                |
|                                 | [LaTeX block — KaTeX rendered]     | [Supported · 92%] Edit was    |
| ── Staged Papers ──             | • Bullet block                     | consistent with staged sources |
| ● Paper A  [×]                 | [Python visualization block]      |                                |
| ● Paper B  [×]                 |                                     | ── Nudges ──                   |
|                                 | [+ Add block via slash menu /]     | ⚠ Contradicts Lemma 3         |
| ── Search Results ──            |                                     | 💡 Expand using EDCN formula   |
| [arxiv:2301] [Stage]           |   [Cmd+K floating toolbar]         |                                |
|                                 |                                     | ── Chat ──                     |
|                                 |                                     | ▶ thinking… [source chips]     |
|                                 |                                     | [input]                        |
+---------------------------------+-------------------------------------+--------------------------------+
```

### 8.2 Knowledge Vault

- Search input → debounced fan-out to arXiv + Exa in parallel (`Promise.allSettled`).
- Results deduplicated by `arxiv_id`; source badges (orange "arXiv" / teal "Exa").
- **Stage** button → calls `api.ingestPaper(arxiv_id)` + `vaultStore.stagePaper(...)`.
- Staged section: title + authors, `[×]` unstage button.
- Staged paper IDs are sent with every chat request and fact-check so the AI is grounded in them.

### 8.3 BlockNote Editor

Built on [BlockNote.js](https://www.blocknotejs.org/) v0.47. Custom block schema extends `defaultBlockSpecs` with two additional block types:

| Block type | Description |
|-----------|-------------|
| `latex` | Display-mode LaTeX equation. Edit mode shows a live KaTeX preview below the textarea. View mode renders KaTeX + shows a ✓/✗ validation icon on hover. |
| `matlabOutput` | Output from the Python Visualization agent. Shows a collapsible code section, Matplotlib plot (base64 PNG), and stdout. |

**Slash menu (`/`)** — custom items in the "Math & Science" group:
- "LaTeX Math" → inserts a `latex` block at the cursor.
- "Python Visualization" → opens the computation runner modal.

**Cmd+K** — global keyboard listener. Opens a floating overlay, sends the instruction + current block content to the chat API with `transform_mode: true`, then replaces the block with the AI reply. Triggers a fire-and-forget fact-check on the new content.

**Auto-save** — every document change is debounced and written to `localStorage` under key `heaven-blocknote-v1`. On mount, the editor restores this content.

### 8.4 Parse Reply to Blocks

`lib/parse-reply-to-blocks.ts` — two-pass parser converts AI reply strings into `ParsedBlock[]`:
1. Split on `$$...$$` display math → `latex` blocks.
2. Classify remaining lines:
   - `# ` → `heading1`, `## ` / `### ` → `heading2`
   - `- ` / `* ` → `bullet`, `1. ` → `bullet` (numbered lists flattened)
   - `> ` → `text` (blockquote stripped)
   - Code fences (`` ``` ``) → skipped entirely
   - Horizontal rules (`---`) → skipped
   - Everything else → `text`

Parsed blocks are inserted via `insertAIBlocks()` (a module-level helper in `editor-store.ts`) which calls BlockNote's `insertBlocks` / `replaceBlocks` on the live editor ref.

### 8.5 Reasoning Engine

- Shows amber banner if no papers are staged.
- **Automatic fact-check card** — appears after every successful Cmd+K edit. Coloured pill shows verdict (Supported / Contradicted / Uncertain), confidence %, and a one-line explanation. Dismissed with ×. No user action required.
- **Proactive nudges** — debounced 1.2s after any document change; ChromaDB-matched + LLM-generated suggestions from staged papers. Each nudge is individually dismissible.
- **Chat** — each message sent with `{staged_paper_ids, canvas_summary}`. Assistant messages show:
  - Collapsible `ThinkingBlock` (AI's internal monologue, hidden by default)
  - Reply text
  - Source chips (paper title pills for cited staged papers)
  - "N blocks → document" indicator when blocks were inserted

### 8.6 State Management

**`lib/vault-store.ts`** — Zustand, persisted to `localStorage` key `heaven-vault-store`.
- `stagedPapers: StagedPaper[]`, `stagePaper()`, `unstagePaper()`

**`lib/editor-store.ts`** — module-level `_editor` ref (BlockNote instance) + minimal Zustand store.
- Module-level: `setEditorRef(editor)`, `getEditorRef()`, `insertAIBlocks(parsed[])`, `getEditorContent()`
- Zustand UI state: `cmdKBlockId`, `pyVisTargetBlockId`, `lastInsertedAt`, `lastFactCheck`
- No block arrays in Zustand — BlockNote owns all document state internally.

---

## 9. Key Workflows End-to-End

### Paper Ingestion

```
User clicks "Stage" on an arXiv result
  → api.ingestPaper("2301.00001")
  → POST /papers/ingest {arxiv_id: "2301.00001"}
  → Server: arxiv_client.fetch_by_id() → persist Paper to SQLite
  → Upsert abstract to ChromaDB
  → asyncio.create_task(ingestion_graph.invoke(...))
  → Return 202 {job_id, paper_id, status: "pending"}

  Background (ingestion_graph):
    fetch_content       → ar5iv HTML → plain text
    extract_concepts    → chunk → LLM → dedup → SQLite + ChromaDB
    classify_msc        → LLM → update Paper row
    extract_relations   → LLM → ConceptRelationship rows → status="done"

  Client polls GET /papers/ingest/{job_id} every 2s
  → On "done": vaultStore.stagePaper({paper_id, title, ...})
```

### Chat Turn with Grounded Response

```
User types in Reasoning Engine → presses Enter
  → api.chat(text, sessionId, {staged_paper_ids, canvas_summary})
  → POST /chat
  → Server: _load_staged_papers() → load Paper + top-8 Concepts per staged paper
  → _build_system() → inject paper context into system prompt
  → Call primary LLM → JSON: {thinking, reply, sources, action?}
  → Execute action if present
  → Return ChatResponse {reply, thinking, sources, session_id}

  Client:
    parseReplyToBlocks(reply) → ParsedBlock[]
    insertAIBlocks(parsedBlocks) → appended to BlockNote document
    Show ThinkingBlock (collapsible) + source chips
    Fetch nudges (debounced 1200ms)
```

### Cmd+K Inline Edit + Auto Fact-Check

```
User focuses block → presses Cmd+K
  → cmd-k-toolbar.tsx opens (fixed overlay)
  → User types instruction → Submit
  → api.chat(instruction, session, {transform_mode: true, transform_content: blockContent})
  → Server returns reply (the rewritten block content)
  → editor.updateBlock(block, {content: proposed})  — live BlockNote mutation
  → closeCmdK()

  Fire-and-forget (non-blocking):
    → api.factCheck(proposed, staged_paper_ids)
    → POST /agents/fact-check
    → ChromaDB semantic search → LLM grading
    → useEditorStore.setFactCheck(result)
    → FactCheckCard appears in Reasoning Engine (auto-dismissed with ×)
```

### MATLAB / Python Computation

```
User types "/" → selects "Python Visualization"
  → matlab-runner.tsx modal opens with example code
  → User writes NumPy/Matplotlib code → clicks Run (or ⌘↵)
  → api.runPythonVisual(code)
  → POST /agents/python-visual
  → Server: safety check → temp file → subprocess.run(timeout=20s)
  → Capture stdout + plt.savefig() → base64 PNG
  → Return {output, image_base64, error}

  Client:
    → insertBlocks([{type: "matlabOutput", props: {code, imageBase64, stdout}}])  # block type unchanged for backward compat
    → Block appears in editor with dark header, collapsible code, embedded plot
```

### Discovery Analysis

```
User: POST /discoveries {name, base_concept_id, modified_latex_statement, ...}
  → asyncio.create_task(discovery_graph.invoke(DiscoveryState, config))
  → Return 202 {job_id, status: "pending"}

  Background (discovery_graph):
    initialize      → persist Discovery row, load base concept
    symbolic_check  → SymPy → update sympy_check_status
    formalize       → LaTeX → Lean 4 (retry ×3) → update lean_verification_status
    analyze_graph   → build_graph() → BFS impact subgraph → find conflicts
    explain_impacts → cheap LLM → per-concept descriptions
    explain_conflicts → cheap LLM → severity + implications
    persist_impacts → DiscoveryImpact rows → status="done"

  Client polls GET /discoveries/jobs/{job_id}
  → On "done": display impacts + conflict analysis
```

---

## 10. LLM Provider System

Configure via `.env`. No code changes needed to switch providers.

```env
PRIMARY_PROVIDER=claude
PRIMARY_MODEL=claude-sonnet-4-6

CHEAP_PROVIDER=claude
CHEAP_MODEL=claude-haiku-4-5-20251001

ANTHROPIC_API_KEY=sk-ant-...

# For OpenAI-compatible providers:
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.deepseek.com/v1   # omit for standard OpenAI
```

| Task | Provider | Why |
|------|----------|-----|
| Concept extraction | primary | High accuracy; complex math notation |
| Relationship extraction | primary | Semantic reasoning between statements |
| Autoformalization (LaTeX → Lean 4) | primary | Code generation requires strong reasoning |
| Chat / transform (Cmd+K) | primary | Full conversational context + action dispatch |
| Fact-check grading | primary | Nuanced mathematical judgment required |
| Deduplication confirmation | cheap | Binary yes/no; cost-sensitive at scale |
| MSC classification | cheap | Fixed taxonomy; classification task |
| Impact/conflict descriptions | cheap | Prose descriptions, not mathematical proofs |
| Nudge generation | cheap | Few-shot suggestions; low stakes |

---

## 11. Verification Pipeline

### Stage 1 — SymPy (fast, symbolic)

`verification/sympy_check.py` — converts LaTeX to SymPy expression tree, evaluates equality/consistency symbolically. Catches most LLM hallucinations (wrong signs, missing terms) in milliseconds.

### Stage 2 — Wolfram Alpha (fallback)

`ingestion/wolfram_client.py` — for expressions SymPy cannot parse (special functions, integrals). Requires `WOLFRAM_APP_ID` in `.env`. Slower and has API rate limits; used only when SymPy returns `UNSUPPORTED`.

### Stage 3 — Lean 4 (authoritative)

`verification/lean.py` — calls `lake env lean <file>` in a subprocess. Uses the Lean 4 project at `server/lean_project/` (pre-configured with Mathlib). The autoformalization loop retries up to 3 times, feeding Lean's error output back to the LLM.

**Prerequisites (one-time setup):**
```bash
# Install Lean 4 via elan
curl https://elan.lean-lang.org/elan-init.sh -sSf | sh

# Fetch pre-compiled Mathlib binaries (never compile from scratch)
cd server/lean_project && lake exe cache get

# Verify
lake env lean HEAVEN/Basic.lean   # should print nothing
```

---

## 12. Configuration Reference

### Server `.env`

```env
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# OpenAI-compatible (if using DeepSeek, OpenRouter, etc.)
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.deepseek.com/v1

# LLM selection
PRIMARY_PROVIDER=claude               # claude | openai_compatible
PRIMARY_MODEL=claude-sonnet-4-6
CHEAP_PROVIDER=claude
CHEAP_MODEL=claude-haiku-4-5-20251001

# External APIs (optional)
WOLFRAM_APP_ID=...

# Embeddings
EMBEDDING_MODEL=all-MiniLM-L6-v2

# Databases
DATABASE_URL=sqlite:///heaven.db
CHECKPOINT_DATABASE_URL=sqlite:///heaven_checkpoints.db
```

### Client `.env.local`

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## 13. Running the Project

### Server

```bash
cd server

# Install dependencies
uv sync

# Run migrations (creates heaven.db schema)
uv run alembic upgrade head

# Start server (hot reload)
uv run uvicorn main:app --reload
# → http://localhost:8000
# → http://localhost:8000/docs  (Swagger UI)
```

### Client

```bash
cd client

# Install dependencies
npm install

# Start dev server
npm run dev
# → http://localhost:3000

# TypeScript build check
npm run build
```

---

## 14. Test Suite

Location: `server/tests/api/`

```bash
cd server
uv run pytest tests/api/ -q     # run all 65 API tests
uv run pytest -k "test_name"    # run single test
```

**Fixtures** (`tests/api/conftest.py`):
- `client` — FastAPI `TestClient` with mocked `app.state`
- `mock_ingestion_graph` — `MagicMock()` replacing the compiled LangGraph pipeline
- `mock_discovery_graph` — same
- `test_thread_metadata` — in-memory dict
- `test_running_threads` — in-memory set

**Coverage:**
- Paper search (arXiv + Exa), ingest, dedup, status polling, resume, list/get
- Discovery create, status polling, resume, impact retrieval
- Chat (session management, context injection)
- Nudge generation
- Python visualization execution (safety check, subprocess, image capture)
- Fact-check (ChromaDB search, LLM grading, verdict/confidence)
- Concept search, impact analysis
- Cross-entity semantic search

**Note:** Two benign warnings appear (unawaited coroutines in background task mocking). These do not affect test results.
