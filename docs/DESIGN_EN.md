# Design Overview — notes-rag

[English](DESIGN_EN.md) | [简体中文](design.md)

> **This document keeps only the "outline + fundamentals + global conventions".**
> Module-level design details (data model, ingestion pipeline, retrieval, chat, Vault/multi-user, frontend, multi-model, MCP, deployment, multi-format parsing, testing)
> live in separate internal design docs — see **§10 Module Design Document Index**.
>
> All `.py` business logic in this project is meant to be hand-written; the repo provides the directory skeleton and design docs.
> Requirements and scope boundaries: §1 (Project Overview).

---

## 1. Project Overview

`notes-rag` is a **self-hosted personal knowledge base RAG application**: Obsidian vault / local notes directory → parse & chunk → embed & store → semantic retrieval → retrieval-augmented Q&A — and it can be invoked as a tool by agents (WorkBuddy / OpenClaw, etc.).

**Positioning**:

| Audience | Description |
|---|---|
| Learning | Complete layered architecture (api / services / repositories / rag) — great practice for FastAPI + SQLAlchemy async + RAG engineering |
| Practical | Deploy directly as a self-hosted knowledge base service (local / Docker / remote access) |
| Extensible | Vector store, LLM, Embedding, relational DB, and file formats are all swappable extension points |

**Key capabilities**:

- Multi-source vault ingestion (local reference / zip upload / git / remote), with file and folder filtering
- Multi-format parsing (`.md` / `.txt` / `.docx` / `.pdf` / `.xlsx`). Scanned PDFs are supported:
  text-less pages are rendered to images and recognized by a multimodal LLM — no OCR engine introduced
- **Multiple LLMs / Embeddings, configurable and selectable** (LLM switchable per request; Embedding bound to the index — switching requires re-indexing)
- Frontend SPA (Vault management / search / chat / model management), same-origin hosting on a single port
- Optional multi-user switch (single-user personal mode by default)
- Agent integration (MCP server: stdio / Streamable HTTP)

---

## 2. Architecture

Layered architecture; dependencies flow downward (`api → services → repositories / rag → core / models`):

```
Client (curl / frontend SPA / Obsidian plugin / Agent)
   │  HTTP (JSON / SSE)
   ▼
app/api/          Route layer: receive, validate, call services, assemble responses — no business logic
   │
   ▼
app/services/     Service layer: orchestrate ingest / retrieval / chat / vault / model flows
   ├─────────────► app/repositories/   Data access: SQLite reads/writes (note metadata, conversations, config)
   └─────────────► app/rag/            RAG pipeline: chunker / embedder / vectorstore / llm_client
   │
   ▼
app/core/         Cross-cutting: config / security / database / middleware
app/models/       Pydantic schemas + ORM definitions
app/parsers/      Parsing layer: route to parser by extension (format differences isolated here)
app/mcp/          Agent integration: expose services as MCP tools
```

**Dependency principles**

- Route layer holds no business logic; services never touch HTTP; repositories never touch RAG; rag never touches FastAPI.
- **The `rag` layer only accepts an already-resolved `ModelRuntime`** — it knows nothing about DB / users / defaults (avoids dependency inversion).
- Dependencies are injected via FastAPI `Depends` (config, db session, clients).
- `core` can be imported by any layer, but `core` must not import business layers (`database.py` depending on `models.orm` is an allowed downward dependency).

**Two storage responsibilities**: SQLite holds structured metadata (authoritative); Chroma holds vectors (**a rebuildable derived index** — inconsistencies are fixed by re-indexing).

---

## 3. Layout & Responsibilities (hand-written map overview)

```
app/
  main.py                # FastAPI instance, lifespan (create tables + recover stale jobs + scheduled sync), routes, CORS, exception handlers, static hosting   ← hand-written
  api/
    deps.py              # DI: get_settings / get_session / get_current_api_key / get_current_user_id / get_vector_store
    routes/
      ingest.py          # POST /api/v1/ingest (submit job, 202)
      search.py          # POST /api/v1/search
      chat.py            # POST /api/v1/chat (SSE streaming)
      health.py          # GET /healthz
      vaults.py          # /api/v1/vaults CRUD + sync / reindex / runs / runs/{rid} / cancel / doctor
      auth.py            # register / login / me / API Keys (multi-user mode)
      models.py          # model profile CRUD / set default / test connection
  core/
    config.py            # Settings (pydantic-settings) reads .env
    security.py          # API Key / JWT verification
    database.py          # SQLite async engine / session (incl. session_scope outside requests) / table creation
    middleware.py        # Request logging middleware
  models/
    schemas.py           # Request / response Pydantic models (Vault / User / Token / ModelRuntime / SyncRunOut ...)
    orm.py               # SQLAlchemy tables: users / vaults / notes / chunks / conversations / messages / model_profiles / sync_runs / api_keys
  repositories/
    note_repo.py         # Note & chunk metadata CRUD
    conversation_repo.py # Conversation & message CRUD
    vault_repo.py        # vault / user CRUD
    model_repo.py        # Model profile CRUD / set default / count
    sync_repo.py         # Job records CRUD / progress updates / cancel / trimming / startup recovery
  services/
    run_service.py       # Job layer: submit/lock, throttled progress reporting, cooperative cancel, startup recovery, scheduled sync
    sync_service.py      # Reconciliation layer: change detection, four change actions, deletion guardrails, dry_run, doctor
    ingest_service.py    # Primitive layer: per-file index_file / drop_file / move_file (parse → chunk → embed → write)
    retrieval_service.py # query → embedding → vector search → context assembly
    chat_service.py      # retrieval + LLM streaming generation + history
    vault_service.py     # resolve vault to local path / unzip uploads / submit jobs (no indexing logic)
    model_service.py     # multi-model resolution (three-level priority) / client construction / embedding consistency guard
    watcher.py           # Filesystem watching (phase 2): mark-dirty only + debounced job submission
  rag/
    chunker.py           # split_markdown (with heading breadcrumbs) / split_text (generic)
    embedder.py          # text → vector (OpenAI-compatible embedding, async)
    vectorstore.py       # Chroma wrapper: add / query / reset
    llm_client.py        # LLM calls (chat.completions.create, stream=True)
  parsers/               # Multi-format parsing (md/txt/docx/pdf/xlsx implemented)
    base.py              # DocumentParser abstract base + ParsedDocument (self-registering)
    registry.py          # register / get_parser
    markdown.py · text.py            # phase 1
    docx.py · pdf.py                 # implemented (python-docx / pymupdf, main deps)
    excel.py                         # implemented (openpyxl, main dep; .xlsx / .xlsm)
  mcp/
    server.py            # MCP server (stdio / Streamable HTTP), wraps services as tools   ← hand-written
  static/                # Built frontend assets (produced by frontend/, gitignored)
tests/
  conftest.py, test_ingest.py, test_search.py, test_chat.py,
  test_security.py, test_vault.py, test_auth.py, fixtures/sample_vault/
scripts/
  init_db.py             # Table creation script (or create_all inside database.py)
frontend/                # Vue 3 + Vite SPA source, build → app/static
  src/jobs.js            # Shared job constants: stage labels / status semantics / progress shapes / poll intervals
  src/components/TasksView.vue     # Jobs & progress page (/tasks)
  src/components/JobProgress.vue   # Progress bar (3 adaptive shapes, shared by card / tasks page)
deploy/                  # Deployment templates
  Dockerfile             # Multi-stage: node builds frontend → python:3.12-slim + uv
  docker-compose.yml     # Service + data volumes + optional reverse proxy
  nginx.conf.example     # Reverse proxy + TLS termination + rate limiting + buffering-off example
docs/
  design.md              # ← this document (Chinese); DESIGN_EN.md is the English version
```

---

## 4. Technology Choices & Rationale

| Component | Choice | Rationale |
|------|------|------|
| Web framework | FastAPI | Async-native, Pydantic validation, automatic OpenAPI docs |
| Config | pydantic-settings | Unified config & schema, type-safe `.env` reading |
| ORM | SQLAlchemy 2.0 (async) + aiosqlite | Metadata/history persistence; practice ORM + async sessions |
| Vector store | Chroma (chromadb) | Local persistence, zero deployment, simple API; swap to pgvector / Qdrant later |
| LLM (chat) | openai SDK (compatible) | Switching models is config-only; multi-model see M08 |
| Embedding | openai SDK (compatible) | Falls back to the LLM endpoint/key by default, or point independently at BGE-M3 / local services |
| Frontend | Vue 3 + Vite | Pure SPA without SSR; build output served same-origin by FastAPI |
| MCP | Official `mcp` Python SDK | stdio / Streamable HTTP; a server takes ~15 lines |
| Server | Uvicorn | ASGI server |
| Deployment | Docker (python:3.12-slim + uv) | Same image locally and on servers; data volumes for persistence |
| Reverse proxy | Nginx / Caddy (optional, production) | TLS termination, HTTP→HTTPS, rate limiting, protecting the `0.0.0.0` port |
| Retry / logging | tenacity / loguru (optional) | LLM call retries, structured logging |

> Detailed comparison of candidates and the full RAG strategy live in internal development docs (not published with this repo); this section keeps the conclusions and rationale.

---

## 5. Data Flow Overview

> The three flows below are skeletons only; full sequences, error handling, and degradations live in M03 / M04 / M05.

### 5.1 Ingest

**Indexing is always an async job**: the API returns `202 + run_id` immediately; execution advances in a background coroutine (see M03 §5.13).

```
POST /ingest (or /vaults/{id}/sync)
  → normalize sources → idempotent upsert of vault entities → submit jobs one by one, return { run_ids } (HTTP request ends here)
  ---- everything below runs inside the background job; the frontend polls progress ----
  → probe  check source reachable (unreachable → ABORT; never treat as "all content deleted")
  → scan   walk + filter (excluded dirs → extension whitelist → exclude glob → include glob → size cap)
  → diff   reconcile against notes (added / modified / moved / unchanged / deleted / out-of-scope)
  → plan   evaluate the three deletion guardrails
  → index  per file: get_parser(ext) → parse() → ParsedDocument (plain text + metadata)
           chunker: .md uses split_markdown (keeps heading breadcrumbs); others use split_text
           embedder.embed(chunks, runtime) → vectorstore.add(...)
           note_repo.upsert_note(...)        (SQLite authoritative metadata)
  → prune  clean up files that no longer exist on disk
  → done   write sync_runs terminal status and counters
```

**Write order**: SQLite first, then Chroma — missing vectors can be repaired by `doctor --repair` / reindex.

### 5.1.1 Incremental Sync (change management)

First-time ingestion and daily maintenance share the same pipeline; the differences are "one extra reconciliation step" and "file-granularity writes":

```
POST /vaults/{id}/sync (or /ingest?mode=sync) → 202 { run_id }, then runs in the background:
  → precheck: source reachable? (unreachable → ABORT; never treat as "all content deleted")
  → walk + filter → seen; reconcile against known (notes.file_path)
  → classify: added / modified / moved / unchanged / deleted / out-of-scope
      criteria: L1 = size_bytes + mtime_ns (free from the walk's stat)
                L2 = content_hash (computed only when L1 mismatches; identifies "timestamp changed but content didn't")
  → dry_run? → job stops at stage=plan_ready, producing a SyncPlan (writes nothing)
  → three deletion guardrails (source reachable / scan complete / deletion ratio ≤ threshold) → if unmet, this run only adds
  → execute: per changed file "delete old chunks + old vectors first, then write new ones" (file-level replacement)
  → record sync_runs (counters + failed file list + terminal status)

Progress: GET /vaults/{id}/runs/{rid}   Cancel: POST /vaults/{id}/runs/{rid}/cancel (takes effect at file boundaries)
```

> Full details (four-quadrant criteria, move pairing, guardrail thresholds, `sync_runs` observability, `doctor` three-way check) see **M03 §5.8–§5.12**;
> job execution & progress visualization (stage model, throttled reporting, cooperative cancel, three failure terminal states) see **M03 §5.13**.

### 5.2 Search

```
POST /search
  → retrieval_service.retrieve(query, top_k, threshold, vault_id)
  → resolve the vault's effective embedding (vaults.embed_profile_id) → consistency guard
  → embedder.embed([query]) → vectorstore.query(vector, top_k, threshold)
  → assemble ChunkHit (note_id / file_path / title / content / score)
```

**The API deliberately does not expose `embed_profile`** — retrieval must use the model that built the index (see M04 §5.3).

### 5.3 Chat (SSE streaming)

```
POST /chat  { query, conversation_id?, top_k, vault_id?, llm_profile? }
  → resolve LLM (three-level priority) → retrieval_service.retrieve(...)
  → assemble system (answer only from <context>, no fabrication) + context chunks + history
  → llm_client.stream_chat(messages, runtime) → yield token by token
  → SSE: data:{"type":"token","text":"..."} … {"type":"sources",...} {"type":"done"}
  → persist user / assistant messages (partial generations are saved on disconnect too)
```

The frontend reads the stream with `fetch` (`EventSource` cannot send auth headers).

---

## 6. API Overview

> All business endpoints are mounted under `/api/v1`; `/healthz` is unauthenticated. Detailed contracts (validation, error semantics) live in the module docs.

| Method | Path | Purpose | Details |
|---|---|---|---|
| POST | `/api/v1/ingest` | **Submit indexing job** (CLI / MCP; multi-source = multiple jobs) → `202` | M03 §5.7 |
| POST | `/api/v1/search` | Semantic search (`vault_id` filter; no `embed_profile`) | M04 |
| POST | `/api/v1/chat` | Retrieval-augmented Q&A (SSE streaming; optional `llm_profile`) | M05 |
| GET | `/healthz` | Health check | — |
| GET / POST | `/api/v1/vaults` | List / create vault (JSON) | M06 |
| POST | `/api/v1/vaults/upload` | Upload vault (multipart `.zip`) | M06 |
| GET / DELETE | `/api/v1/vaults/{id}` | Detail / delete (also clears index and chunks) | M06 |
| POST | `/api/v1/vaults/{id}/sync` | **Submit sync job** → `202 { run_id }`; `dry_run` previews the plan | M03 §5.8–§5.10 |
| POST | `/api/v1/vaults/{id}/reindex` | **Submit full rebuild job** → `202` (with `?embed_profile=` to switch embedding) | M06 / M08 |
| GET | `/api/v1/vaults/{id}/runs` | Job history (including running; pinned by the frontend) | M03 §5.11 |
| GET | `/api/v1/vaults/{id}/runs/{rid}` | Job detail & **progress polling** (`stage` / `total` / `processed` / `current_item`) | M03 §5.13 |
| POST | `/api/v1/vaults/{id}/runs/{rid}/cancel` | Request cancellation → `204` (cooperative, effective at file boundaries) | M03 §5.13 |
| GET / POST | `/api/v1/vaults/{id}/doctor` | Three-way consistency check (ghost vectors / missing vectors / orphan notes / model mismatch) | M03 §5.12 |
| GET / POST | `/api/v1/models` | List (keys masked only) / create model profile | M08 |
| POST | `/api/v1/models/test` | Test an unsaved profile | M08 |
| GET / PATCH / DELETE | `/api/v1/models/{id}` | Detail / partial update / delete (409 if referenced) | M08 |
| POST | `/api/v1/models/{id}/default`, `/test` | Set as kind default / test a saved profile | M08 |
| POST | `/api/v1/auth/register`, `/login` | Register / login (`ENABLE_MULTIUSER=true`) | M06 |
| GET | `/api/v1/auth/me` | Current user identity | M06 |

**Auth**: protected endpoints take header `X-API-Key: <key>` or `Authorization: Bearer <JWT>`; the backend **checks the API Key first, then the JWT**.

**Write endpoints always return `202` immediately** — they never wait for the job — a full rebuild takes 2–10 min and a synchronous response would always hit gateway timeouts.
Clients poll `runs/{rid}` with the returned `run_id` (M03 §5.13.1 / ADR-12).

**Submitting while a job runs for the same vault → `409` + `existing_run_id` (no queueing)**; the frontend jumps to that job's progress view
instead of silently losing the request (M06 ADR-8). **Cancellation uses `POST`, not `DELETE`**: cancel only requests a stop —
the record must be kept (it's the audit trail and history); `DELETE /runs/{rid}` would read as "delete the record".

**Why "create" and "upload" are separate endpoints**: a FastAPI endpoint cannot receive both a Pydantic JSON body and an `UploadFile` (the body can only be parsed once).

---

## 7. Data Model Overview

> Field-level design, index constraints, isolation and consistency strategies see **M02 Data Model & Persistence**.

**SQLite tables (SQLAlchemy ORM, see `models/orm.py`)**

```sql
users(id PK, username UNIQUE, password_hash, is_admin, created_at)
vaults(id PK, user_id, name, source_type, source_value,
       embed_profile_id, embed_indexed_profiles, filters_json,
       origin, created_at, indexed_at)
notes(id PK, user_id, vault_id, file_path, title,
      size_bytes, mtime_ns, content_hash, indexed_at, last_seen_at)
       -- UNIQUE(vault_id, file_path); file_path is relative to the vault root
chunks(id PK, user_id, vault_id, note_id FK, idx, content,
       char_start, char_end, vector_id UNIQUE, embed_profile_id)
conversations(id PK, user_id, vault_id, created_at)
messages(id PK, conversation_id FK, user_id, role, content, created_at)
model_profiles(id PK, user_id, kind, name, provider, base_url, api_key, model,
               params_json, is_default, enabled, origin, created_at)
api_keys(id PK, user_id, name, key_hash UNIQUE, key_prefix,
         created_at, last_used_at, revoked_at)
sync_runs(id PK, user_id, vault_id, trigger, mode, dry_run,
          status,  -- queued|running|success|partial|failed|cancelled|aborted
          stage, total, processed, current_item, message, cancel_requested,
          adds, updates, moves, deletes, unchanged, failed_cnt,
          embed_profile_id, blocked_reason, error, detail_json,
          started_at, finished_at, elapsed_ms)
```

- **Isolation columns**: `notes` / `chunks` / `conversations` / `messages` all carry `user_id` + `vault_id`; in single-user mode `user_id` is always `"default"`.
- **Key semantics**: `vaults.embed_profile_id` = the embedding used by retrieval now; `vaults.embed_indexed_profiles` = models the vault has been indexed with (switching back is instant, no re-ingestion).
- **Change-detection fields**: `notes.size_bytes` + `notes.mtime_ns` are the fast check; `notes.content_hash` is authoritative (see §5.1.1).
- **Sync audit trail**: `sync_runs` records counters, guardrail blocks, and failed file lists for every sync / rebuild (see M03 §5.11).
- **Job carrier**: `sync_runs` doubles as the persistence for async tasks — `status` has seven states; `stage` / `total` / `processed` / `current_item` are progress columns,
  where `total IS NULL` means **the stage's total is unknown** (`scan`), and the frontend progress bar switches to "indeterminate" accordingly (M03 §5.13.3).
  Why one table for both "observable record" and "task state": they are one-to-one with the same lifecycle — splitting only adds a join (M03 ADR-13).

**Vector store (Chroma)**

- `collection` named `v{vault_id}_m{profile_id}`, **physically isolated** by (vault, embedding model).
- `ids` = `chunks.vector_id`; `documents` = chunk text; `metadatas` = `{ note_id, file_path, title, chunk_idx }`.
- **Dimension consistency**: changing dimensions = changing model = new collection + re-index.

---

## 8. Configuration Overview

> Field-level semantics, list-field parsing pitfalls, and derived methods see **M01 Core Framework & Config**; deployment shapes see **M10 Deployment**.

**Model config is not in `.env`**: all three kinds (LLM / Embedding / ASR) live in the `model_profiles` table, configured via the frontend "Models" page
or `POST /api/v1/models` (§10 module index M08). With an empty table, chat / indexing / transcription all return `409` pointing to the config page —
**no `.env` fallback**, avoiding two sources of truth for the same thing.

**Other groups**:

| Group | Fields |
|---|---|
| Runtime | `DEBUG`, `VERSION` |
| Ingestion filters | `INGEST_EXTS` (default `md,txt,docx,pdf`), `INGEST_EXCLUDE_DIRS` (default excludes `node_modules` / `.git` / `.obsidian` / `.trash` / `__pycache__` / `.venv`) |
| Change management | `INGEST_SYNC_INTERVAL` (scheduled sync seconds, 0=off), `INGEST_SYNC_ON_STARTUP`, `INGEST_SETTLE_SECONDS`, `INGEST_MAX_CONCURRENCY`, `PRUNE_ENABLED`, `PRUNE_RATIO_LIMIT` (default 0.5), `SYNC_RUNS_KEEP` (default 50), `PROGRESS_FLUSH_MS` (min progress-write interval, default 500; stage jumps and terminal states force writes), `WATCH_ENABLED`, `WATCH_DEBOUNCE_MS`, `MAX_FILE_SIZE` (see M03 §8 / M01 §5.2) |
| Storage | `CHROMA_DIR`, `SQLITE_PATH` |
| Service | `API_KEY`, `CORS_ORIGINS`, `HOST`, `PORT`, `PUBLIC_BASE_URL` |
| Multi-user / frontend | `ENABLE_MULTIUSER` (default false), `JWT_SECRET`, `UPLOAD_DIR`, `UI_ENABLED` |
| Logging | `LOG_LEVEL`, `LOG_FILE`, `LOG_ROTATION`, `LOG_RETENTION`, `LOG_ERROR_FILE` |

**Four easy-to-trip config rules**:

1. **List fields accept two syntaxes**: `INGEST_EXTS` / `INGEST_EXCLUDE_DIRS` use `Annotated[List[str], NoDecode]` + a custom validator — comma-separated or JSON arrays both work, empty returns `[]` (pydantic-settings JSON-decodes by default; writing `a,b` crashes with `SettingsError` — see M01 §5.2).
2. **The DB is the only runtime source of truth**: `vaults` / `model_profiles` tables rule; `.env` **provides neither vault seeds nor model config** (both tables start empty; add via frontend or API: vaults via `POST /vaults`, models via `POST /models`).
3. **`HOST` defaults to `127.0.0.1`**; container / server deployments must override it to `0.0.0.0` explicitly and **must** sit behind a reverse proxy + HTTPS + API Key.
4. **Deletion is a guardrail-constrained operation**: when vault files are deleted, sync cleans the index only after three guardrails pass (source reachable / scan complete / deletion ratio ≤ `PRUNE_RATIO_LIMIT`); for a read-only mirror (never delete) set `PRUNE_ENABLED=false`. See M03 ADR-7.

**Other conventions**: `.env` is never committed; API Keys use constant-time comparison (`hmac.compare_digest`); responses never return plaintext model keys (masked only).

---

## 9. Global Conventions

### 9.1 Testing & Quality

- **Everything offline by default**: `embedder` / `llm_client` / vector store are replaced with deterministic stand-ins in unit tests; **tests must not require real API keys**.
- **Layers**: L1 pure functions → L2 service orchestration (mock the rag layer) → L3 `TestClient` integration → L4 security (401 / cross-user) → L5 smoke (start server + `/healthz`).
- **Quality gates**: `compileall` → import check → `pytest` → config parsing regression → smoke → secret-leak scan.
- Integration tests use temp dirs with self-made sample vaults — **never** write to the repo's `./data`, never use real notes.
- Full methodology, gate checklist, and regression checklist live in **Appendix A: Testing Strategy & Quality Assurance**.

### 9.2 Risks & Notes (global)

| Risk | Notes & mitigation |
|---|---|
| Embedding dimension / model must match the index | Switching models requires re-indexing; the API layer never exposes the retrieval embedding (M04 §5.3) |
| LLM stream interruption | Graceful finish and save partial messages so history stays complete (M05 §5.5) |
| Large vault memory / duration | Cap files per scan, batch embeddings, set `max_file_size` (M03 §9) |
| Indexing timeouts / client disconnects | **Always async jobs**: endpoints return `202 + run_id` immediately, work runs in a background coroutine; **never** add synchronous waiting or a `wait` parameter to indexing endpoints (missing `shield` == "silently cancel on timeout", M03 ADR-12) |
| Concurrent indexing of one vault | `run_service` serializes with an in-memory lock; duplicate submissions return `409 + existing_run_id` (**no queueing**, M06 ADR-8). The lock is **valid only within one process** → deploy **single worker** in phase 1 (M10); multiple replicas need DB row locks + file locks (M03 §12 open item) |
| Crashed processes leave zombie jobs | At startup `run_service.recover_stale()` marks leftover `queued` / `running` as `aborted`, **no resume** (sync is idempotent; re-running beats persisting intermediate state). Without this, the "does this vault have a running job" check stays blocked forever (M03 §5.13.6) |
| Model state after failed / cancelled jobs | `vaults.embed_profile_id` / `embed_indexed_profiles` are **written back only after job success (success / partial)**; otherwise a vault could claim "indexed with model X" with no vectors in the collection — retrieval would **silently return empty** (M06 ADR-9) |
| Chroma version compatibility | Locked by `uv.lock`; `pyproject.toml` constrains the major version with `^`; platform-specific wheel gaps can be handled with `[tool.uv] required-environments` as needed (personal preferences go in an untracked `uv.toml`) |
| `.env` / `data/` never in VCS or images | `.gitignore` + `.dockerignore`; Docker uses `--env-file` |
| Exposed remote access | Mandatory API Key + HTTPS + tightened CORS + path whitelist (M10 §5.4 checklist) |

### 9.3 Open Source & Extensibility

- The project is open-sourced under **MIT** — **no usage restrictions**: personal, team, and commercial self-hosting are all fine.
- The layered architecture keeps every piece replaceable:
  - **Vector store**: Chroma → pgvector / Qdrant / Milvus (just implement the `VectorStore` abstraction)
  - **LLM / Embedding**: OpenAI-compatible → any compatible endpoint (only `base_url` / `api_key` change)
  - **Relational DB**: SQLite → Postgres (change the engine URL and driver; the ORM stays)
  - **File formats**: add a parser to support a new format (RAG pipeline untouched; see M11)
- **Multi-tenant / multi-vault**: realized through the `user_id` / `vault_id` columns reserved in the data model + auth middleware pass-through (see M02 / M06).
- Community contributions welcome: new retrieval strategies (reranker / hybrid), new vector backends, frontend, deployment templates (Docker / compose / Helm), etc.
- **Deployment templates included**: `deploy/` provides Dockerfile / docker-compose.yml / nginx examples; local and server share the same code and config.
- Commit conventions and PR flow: root `CONTRIBUTING.md`.

---

## 10. Module Design Document Index

Module-level designs are split into separate documents (numbered M01–M11 + Appendix A). These module docs are **internal development documents, not published with this repository**; the table below keeps summaries so the responsibilities and priorities stay understandable.


| ID | Module | Priority | Coverage |
|:---:|---|:---:|---|
| M01 | Core framework & config | **P0** | All `Settings` fields, list-field parsing, DB engine, security primitives, app assembly, DI, logging middleware |
| M02 | Data model & persistence | **P1** | 8 ORM tables (incl. `sync_runs`), indexes & constraints, isolation, schemas inventory, note / conversation repos |
| M03 | Ingestion pipeline | **P2** | Parser contract, three-layer filter merge, chunking, embedding, vector writes, file primitives (`index_file` / `drop_file` / `move_file`); **change management** (incremental reconciliation, deletion guardrails, `sync_runs`, `doctor`); **job execution & progress visualization** (async job model, stage progress, throttled reporting, cooperative cancel) |
| M04 | Retrieval service | **P3** | `retrieve` contract, vector query semantics, embedding consistency guard, thresholds & tuning |
| M05 | Chat service (SSE) | **P4** | Prompt templates, context assembly, SSE event protocol, persistence timing, anti-hallucination |
| M06 | Vault & multi-user auth | **P5** | Authoritative vault model, source types, upload safety, reindex, multi-user switch & upgrade path |
| M07 | Frontend SPA | **P6** | Page responsibilities, API client & SSE consumption, **jobs & progress view** (two progress-bar shapes, stage localization, cancel UX, polling strategy), build & same-origin hosting, multi-stage build |
| M08 | Multi-model management | **P7** | `model_profiles`, LLM/Embedding/ASR constraint differences, three-level resolution, collection naming, config page (no `.env` fallback) |
| M09 | Agent integration (MCP / Skill) | **P8** | MCP tool wrappers, stdio / Streamable HTTP trade-offs, client config, Skill supplement |
| M10 | Deployment | **P9** | Local / Docker, data volumes, reverse proxy essentials, remote-access checklist, capacity estimation |
| M11 | Multi-format parsing & filtering | **P10** | Type matrix, per-format parsing notes, enablement path (md/txt/docx/pdf/xlsx implemented) |
| Appendix A | Testing strategy & quality | Cross-cutting | Test layering, mock contracts, sample data, quality gates, regression checklist |
