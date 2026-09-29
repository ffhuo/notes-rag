# notes-rag MCP Integration Guide

[English](MCP_GUIDE_EN.md) | [简体中文](mcp-guide.md)

Connect your personal knowledge base to an AI assistant (Trae / WorkBuddy / OpenClaw, etc.) and let the agent **search, read, and ask questions** about your notes — no window switching, no manual copy-paste.

---

## 1. What You Get (effects)

Before integration: the agent only knows what's in its training data — it has no idea your notes exist.

After integration: the agent gets a set of "note tools" and your Obsidian vault becomes its external memory:

| You say | What the agent does | What you get |
|---|---|---|
| "What do my notes say about Go's sync.Mutex?" | Calls `search_notes` for semantic search | A hit list with sources: which note, which paragraph, relevance score |
| "Based on my notes, how should I pick a chunking strategy for RAG?" | Calls `search_notes` for your own note snippets first, then combines them with its own knowledge | An answer fusing "your take + general knowledge", citing real note paths |
| "Which note vaults do I have?" | Calls `list_vaults` | Vault list: names, note counts, index status |
| "Read the full text of `notes/example.md`" | Calls `get_note` | The entire note, ready for further analysis / summarization |
| "Answer from my notes: how do I use Go channels?" | Calls `ask_notes` (the service does retrieval + answer assembly) | An integrated answer + cited sources |

**In one sentence: your notes go from "files you have to dig through" to "memory the agent can casually ask".** Because the agent receives real, sourced snippets (not things it made up), answers are significantly more trustworthy — every claim links back to the original note.

> Data boundary: the agent can only access with the identity of "the key you issued to it" — your vaults are visible to it; others' are not (multi-user mode). When you no longer want it to have access, revoke the key with one click in the web UI.

---

## 2. Prerequisites

Confirm the server is ready before integrating (three things, all done in the web UI):

1. **The service is running**: `make dev` locally (or Docker); `http://localhost:8000/healthz` returns ok
2. **Models are configured**: the "Models" page has at least one `kind=embed` model (required for search; `ask_notes` also needs a `kind=llm` model)
3. **A vault is indexed**: a vault has been added on the "Vaults" page and synced at least once (otherwise search returns empty)

Transport-specific prerequisites:

| Transport | Extra prerequisite |
|---|---|
| stdio (local subprocess) | The repo code and the local Python venv are available |
| Remote HTTP | The agent's machine can reach the service address (cross-machine deployment needs the port open or a reverse proxy) |

---

## 3. Integration Steps

### Step 1: Issue a user-level API Key

From the web UI's "Settings → API Keys" page (or curl):

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/api-keys \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <your global key, if configured>" \
  -d '{"name": "workbuddy"}'
```

The `key` in the response (starting with `nr_`) **is shown only once** — copy and save it immediately. Once the dialog closes it is gone; if lost you can only revoke and re-issue.

This key is the agent's identity: it determines which vaults the agent can see, and whose access gets cut when revoked.

### Step 2: Configure the agent's MCP

Choose **one** of the two options below, based on where the agent and the service run.

#### Option A: stdio (recommended for local use)

The agent launches the MCP server as a subprocess — zero ports, simplest. Edit the agent's MCP config file (e.g. `~/.workbuddy/mcp.json`, or Trae's MCP settings) and add:

```json
{
  "mcpServers": {
    "notes-rag": {
      "command": "<absolute path to this repo>/.venv/bin/python",
      "args": ["-m", "app.mcp.server"],
      "env": { "NOTES_RAG_API_KEY": "nr_paste-your-key" }
    }
  }
}
```

- `command` must be an **absolute path** — replace `<absolute path to this repo>` with where you cloned this repo, pointing at its `.venv/bin/python`
- The agent launches this subprocess at startup; it lives and dies with the agent and occupies no port
- For single-user local use with no global Key configured, `env` can be omitted (identity becomes `default`); in all other cases it is **required**, otherwise the process exits at startup (fail fast, see §5)

#### Option B: remote HTTP (recommended for cross-machine / centralized deployment)

The MCP endpoint is mounted on the main service — same port, same process — and the agent connects by URL:

```json
{
  "mcpServers": {
    "notes-rag": {
      "url": "http://localhost:8000/mcp/",
      "headers": { "X-API-Key": "nr_paste-your-key" }
    }
  }
}
```

Key points:

- The URL is `<service address>/mcp/`, and the **trailing slash is mandatory**: the endpoint is hosted by a Starlette Mount which only matches the slash-suffixed path; `/mcp` returns 405 or the frontend page (see §5). For cross-machine access, replace `localhost` with the server's IP / domain.
- **`headers` is required**: every tool call re-resolves the identity from the `X-API-Key` request header; without it you get 401.
- For production, put this behind a **reverse proxy** with HTTPS — this endpoint has no DNS-rebinding protection (see §7); the security boundary is this key, and over plaintext HTTP the key travels naked.
- Advantage: one service instance shared by multiple agents / machines; server upgrades take effect immediately with no agent-side config change.

### Step 3: Restart and verify

1. Restart the agent (the MCP list is loaded at startup) and click "Trust" for the new server in the connector management page
2. Tell the agent: "**list my note vaults**" — it should call `list_vaults` and return your vault list
3. Seeing the vault list means integration succeeded ✅

---

## 4. Available Tools

Phase 1 is **read-only**, four tools:

| Tool | Purpose | Typical trigger phrase |
|---|---|---|
| `search_notes(query, top_k?, vault_id?)` | Semantic search; returns hit snippets + sources (`file_path` / `title` / `score` / `vault_id`) | "Find notes about XX in my notes" |
| `get_note(file_path, vault_id?)` | Read a full note by its path relative to the vault root | "Open / read note X" |
| `list_vaults()` | List vaults and index status (`note_count` / `indexed_at`, etc.) | "Which vaults do I have" |
| `ask_notes(question, vault_id?, conversation_id?, top_k?)` | Retrieval-augmented Q&A returning an integrated answer + citations (best for thin clients; capable agents like Trae / WorkBuddy should prefer `search_notes` and compose themselves — cheaper on tokens) | "Answer XX from my notes" |

Conventions and boundaries:

- `vault_id` may be omitted **only when the current identity has exactly one vault**; with multiple vaults it errors explicitly and lists the options rather than silently picking one (picking the wrong vault is worse than an error).
- `get_note` caps a single note at 1MB; over the limit it suggests `search_notes` for snippets; the resolved path must stay inside the vault root — traversal is rejected.
- `search_notes` / `get_note` consume no LLM quota, so the agent can call them freely to build context.

> Tool docstrings are how the agent decides "when to call me" — if the agent should use a tool but doesn't, first check whether its description in `app/mcp/server.py` explains "when to use me".

---

## 5. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| The agent shows no notes-rag tools at all | Malformed MCP config / wrong python path (Option A) or unreachable URL (Option B) / not restarted | Option A: run `<python> -m app.mcp.server` from a terminal to see the error; Option B: probe the endpoint with `curl`; restart the agent after any change |
| (stdio) the server exits immediately at startup | `NOTES_RAG_API_KEY` missing / invalid / revoked (fail-fast is intentional) | Re-issue the key and update `env` in the config |
| Tools report "auth failed" / HTTP 401 | Option B missing the `X-API-Key` header, or wrong key | Check `headers` in the config; confirm the key isn't revoked |
| `POST /mcp` returns 405, `GET /mcp` returns a web page | URL in the config lacks the trailing slash (the mount only matches `/mcp/`) | Change the URL to `http://<host>:8000/mcp/` |
| `GET /mcp/` directly returns 400 | Normal: this endpoint speaks the Streamable HTTP protocol; a bare GET lacks session headers | Use an MCP-capable client; don't treat it as plain REST |
| `search_notes` returns empty | The vault has never been indexed, or the retrieval model differs from the indexing model | Submit a sync from the "Vaults" page; check the embed config on the "Models" page |
| Tool reports "no embedding model configured" | No `kind=embed` profile for the current identity | Add a `kind=embed` profile on the "Models" page and retry |
| Tool reports "vault (id=N) not indexed yet" | The vault exists but has never been synced | Submit a sync job from the "Vaults" page |
| Tool reports "never indexed with this embedding model" | The embed model was changed without re-indexing | Re-sync (reindex) from the "Vaults" page |
| `ask_notes` reports "no LLM configured" | No `kind=llm` profile | Add one on the "Models" page |
| In multi-user mode, another user's vault shows up | Should never happen (isolated by user_id) | Check the key was issued to the right account; revoke immediately and report if you see cross-user access |
| Answers contain no citations | The agent used its own knowledge instead of search results | Say explicitly "search **in my notes** for…", or check the tool description |

---

## 6. Other Agents (OpenClaw / plain curl)

- **OpenClaw**: `~/.openclaw/mcp.json` uses exactly the same format as §3 — copy either the stdio or HTTP variant as-is
- **Agents without MCP support**: the repo ships a Skill text instruction (see M09 §5.4) teaching the agent to call `/api/v1/search` via `curl` — zero deployment
- **Scripts / service-to-service calls**: skip MCP; plain REST + the `X-API-Key` header (same user-level key)

---

## 7. Implementation Status

| Item | Status |
|---|---|
| User-level API Key issue / revoke | ✅ Implemented (`api_keys` table + `/api/v1/auth/api-keys`, see M06 §5.7) |
| `search_notes` / `get_note` / `list_vaults` / `ask_notes` | ✅ Implemented (reuses the services layer, read-only; see `app/mcp/server.py`) |
| stdio transport + pre-authorization | ✅ Implemented (`python -m app.mcp.server`; identity resolved at startup, fail fast) |
| Streamable HTTP transport | ✅ Implemented (mounted at `/mcp/`; identity resolved per request from headers; URL must have the trailing slash) |
| Write tools (ingest) async adaptation | ⏸ Phase 2: indexing is an async job — how agents should follow it (polling / blocking wait) is undecided; phase 1 stays read-only |

Auth chain: global `X-API-Key` → user-level API Key (`api_keys` table, `nr_` prefix) → `Authorization: Bearer <JWT>`; all three paths share one `resolve_user_id` (`app/core/security.py`), so REST and MCP can never drift apart.

Known boundaries:

- **The MCP endpoint does not authenticate at the initialize stage**; identity is verified on every **tool call**. Protocol handshake (listing tools etc.) returns no user data, and all data-access paths are key-protected.
- **DNS-rebinding protection is disabled** (`TransportSecuritySettings(enable_dns_rebinding_protection=False)`): that protection requires preset allowed_hosts, but deployment hostnames vary by environment — enabling it would 421 every request. The boundary is guaranteed by the user-level key (browsers don't send custom headers automatically); in production, put it behind a reverse proxy doing Host allowlisting + HTTPS.

Related design: M09 (agent-mcp) · M06 §5.7 (user-level API Keys) · M03 §5.13 (async jobs) · `DESIGN_EN.md`
