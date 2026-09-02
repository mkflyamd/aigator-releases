# AI Gator: Agent Memory System — Design Document

**Status**: Ready for review
**Date**: August 2026
**Implementation model**: DeepSeek V4 / Qwen 30B (primary), GLM (reviewer)
**Companion to**: `docs/shell-automation-workflows-design.md` (workflows consume this memory system)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Decisions Log](#2-decisions-log)
3. [Current State — What's Missing](#3-current-state--whats-missing)
4. [Scope Model — Preventing Context Contamination](#4-scope-model--preventing-context-contamination)
5. [Storage Architecture — A+B Hybrid](#5-storage-architecture--ab-hybrid)
6. [Phase 1: Persistent Conversation Store + FTS5 Search](#6-phase-1-persistent-conversation-store--fts5-search)
7. [Phase 2: Learned Memory via `memory` Skill](#7-phase-2-learned-memory-via-memory-skill)
8. [Phase 3: Background Review Loop](#8-phase-3-background-review-loop)
9. [Workflow Integration](#9-workflow-integration)
10. [Community Best Practices Applied](#10-community-best-practices-applied)
11. [Cross-Platform Considerations](#11-cross-platform-considerations)
12. [What This Design Does NOT Adopt](#12-what-this-design-does-not-adopt)
13. [Build Order](#13-build-order)
14. [Implementation Guide for Small Models](#14-implementation-guide-for-small-models)
15. [Review Checklist for GLM](#15-review-checklist-for-glm)

---

## 1. Overview

### Goal

Give AI Gator a bounded, curated, persistent memory system that:

- Remembers user preferences, project conventions, and lessons learned across sessions
- Recalls specific past conversations on demand without bloating every prompt
- Learns proactively (with user consent) rather than requiring manual authorship
- Works identically for chat tabs, workflow runs, and headless execution
- Never contaminates one context (tab/project/workflow) with another's state

### What the agent gains

- **Tiered retrieval** instead of a fixed turn window — recent turns verbatim, older turns summarized, anything else searchable
- **Learned memory** (the analog to today's manually-authored Personas) that the agent curates itself
- **Cross-session recall** via FTS5 search over all past chats and workflow runs
- **Workflow awareness** — scheduled/headless runs get their own memory scope and stage writes for review

### Design influences

- **Hermes Agent** (`NousResearch/hermes-agent`, MIT) — the bounded-Markdown + FTS5 session search architecture. This is the primary reference design. See `docs/memory-system-research.md` (companion) for the full Hermes memory docs analysis.
- **Generative agents** (Stanford) — importance × recency × relevance ranking for recall
- **Reflexion** — episodic memory of failures and fixes is more valuable than declarative facts for coding agents
- **Community feedback** from Claude Code, Cursor, Cline, Aider, Continue, Roo Code — see §10

---

## 2. Decisions Log

| #   | Decision                         | Choice                                               | Rationale                                                                                                                                   |
| --- | -------------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Memory framework                 | None (custom, no external dependency)                | Gator is local-first desktop; no Neo4j/Qdrant/Postgres infra. Honors CLAUDE.md's no-framework stance.                                       |
| 2   | Conversation persistence         | SQLite + FTS5 (`~/.gator/sessions.db`)               | Matches existing `tasks.db`/`scheduler.db` convention; FTS5 ships with Python's sqlite3.                                                    |
| 3   | Learned memory storage           | A+B hybrid: Markdown source of truth + SQLite mirror | Markdown is human-readable/hand-editable; SQLite holds metadata + enables queries.                                                          |
| 4   | Turn window                      | Tiered retrieval, not fixed 20 turns                 | Token-budget-aware working set + summary + on-demand recall. The 20-turn limit was a RAM artifact.                                          |
| 5   | Memory bounds                    | Hard capacity limits, no auto-compaction             | Forces selectivity. Agent must consolidate in-turn when full. Hermes-validated pattern.                                                     |
| 6   | Scope model                      | 5 scopes (session/workflow/project/user/recall)      | Only session+user+active-project auto-inject; recall is explicit via tool. Prevents contamination.                                          |
| 7   | Write approval gate              | Default off for interactive, stage for headless      | Users hate agents saving wrong assumptions; unattended runs can't prompt inline.                                                            |
| 8   | Background review                | Phase 3, behind flag, cheaper model, stage-only      | Extra LLM cost per turn; ship Phases 1-2 first to validate curation quality.                                                                |
| 9   | External providers (Honcho etc.) | Not adopted in v1                                    | Honcho is AGPL-3.0 (enterprise blocker). Mem0 (Apache-2.0) is the fallback if ever needed.                                                  |
| 10  | Security scan on write           | Required                                             | Memory is injected into system prompt; untrusted SaaS content (workflow ingests) must be scanned for injection/exfiltration before persist. |
| 11  | Project-scoped memory            | `memory.md` + `memory.<project>.md`                  | A preference correct for repo A is wrong for repo B. Continue.dev/Cursor learned this.                                                      |
| 12  | Memory ↔ Skills bridge          | `promote_to_skill` path                              | Don't silo declarative memory from procedural memory (Gator's existing skills system).                                                      |

---

## 3. Current State — What's Missing

### What exists today

| Component                       | Location                          | Persists?               | "Agent memory"?                       |
| ------------------------------- | --------------------------------- | ----------------------- | ------------------------------------- |
| Conversation history            | `web/conversation_store.py:13`    | **No** (in-memory dict) | Working memory, lost on restart       |
| 20-turn window + `compact()`    | `conversation_store.py:39`, `:79` | **No**                  | RAM-bounded sliding window            |
| Personas (system-prompt prefix) | `web/routes/config_routes.py:447` | Yes (`config.json`)     | Manually-authored, not learned        |
| Pinned Context (per-tab)        | `web/skills/context/state.py`     | Yes (JSON)              | Manually pinned, not learned          |
| Task results                    | `~/.gator/tasks.db`               | Yes (SQLite)            | Final answer text only, no transcript |
| Turn telemetry                  | `~/.gator/tasks.db` (turn_log)    | Yes (SQLite)            | Metadata only — no message content    |
| Scheduled jobs                  | `~/.gator/scheduler.db`           | Yes (SQLite)            | Job state, not conversation context   |

### The gaps

1. **Every chat is lost on restart.** `ConversationStore` is a `dict` in process memory. Browser re-sends `history` but only text survives — no `tool_use` blocks (`web/routes/chat.py:1250`).
2. **No cross-session recall.** The agent cannot answer "did we discuss X last week?" — there's no searchable archive.
3. **No learned preferences.** Personas are hand-authored. The agent never remembers "user prefers TypeScript" unless the user writes it themselves.
4. **No project scoping.** A preference saved in a React project would leak into a Rust project.
5. **No workflow memory context.** Scheduled/headless workflow runs (per `docs/shell-automation-workflows-design.md`) have no memory namespace — they'd either get none or inherit the last active tab's.
6. **Zero memory framework references** repo-wide (`mem0|letta|zep|memgpt|hermes` → no matches). Greenfield.

### Where memory plugs in (existing seams)

| Seam                              | Location                                   | What lands here                                                           |
| --------------------------------- | ------------------------------------------ | ------------------------------------------------------------------------- |
| System-prompt assembly            | `web/routes/chat.py:843-1006`              | Inject memory block alongside persona/pinned context                      |
| Singleton store registry          | `web/shared.py:343` (`conversation_store`) | New `memory_store` singleton goes here                                    |
| Skills loader (zero app.py edits) | `web/skills/*/tools.py`                    | New `web/skills/memory/` package                                          |
| `compact()` summarization         | `web/conversation_store.py:79`             | Extract → persist summary to SQLite before discarding old turns           |
| User state directory              | `~/.gator/` (`web/config.py:12`)           | `sessions.db`, `memory.db`, `memory.md`, `user.md`, `memory.<project>.md` |

---

## 4. Scope Model — Preventing Context Contamination

The hardest integration problem. Gator already keys on `context_id` (tab ID) — the risk is the new persistent layers leaking across tabs, projects, and workflows.

### Five scopes, only three auto-inject

| Scope                    | What it holds                            | Auto-injected into prompt?                | Keyed by                                  |
| ------------------------ | ---------------------------------------- | ----------------------------------------- | ----------------------------------------- |
| **Session**              | Recent turns + rolling summary           | Yes — always                              | `context_id` (tab or `workflow:{run_id}`) |
| **Project**              | Memories scoped to a repo                | Yes — _only if project active in tab_     | project name                              |
| **User** (global)        | Cross-cutting prefs, comms style         | Yes — always                              | user (one Gator install)                  |
| **Workflow**             | Memories scoped to a workflow definition | Yes — _only for workflow runs_            | `workflow:{workflow_id}`                  |
| **Cross-session recall** | All past sessions, all projects          | **No** — agent must call `session_search` | FTS5 over everything                      |

**Contamination rule: auto-injection is scoped; recall is explicit.** Tab B (Rust) never silently gets facts from tab A (React) in its system prompt. The agent _can_ search across sessions, but only when it decides to — and search results come back as tool output, not as injected context.

### Session-start loader

```
on session start (context_id, active_project):
  if context_id starts with "workflow:":
    load workflow memory (workflow:{workflow_id}.md)
    load user.md (global)
    do NOT load project memory (workflows may span multiple projects)
  else:
    load session working memory (always, scoped to context_id)
    load user.md (always, global)
    if active_project:
      load memory.<project>.md (project-scoped)
    else:
      load memory.md (global agent notes, no project scope)
```

### Fork-to-new-tab rule

`POST /api/conversation/{context_id}/seed` (`web/routes/conversation_routes.py:20`) forks a tab today:

- **Copy**: session working memory (recent turns + summary) — that's the point of forking
- **Do NOT copy**: project-scoped learned memory. The forked tab's project memory is determined by _its_ active project, not the source tab's

Otherwise: fork a React conversation → switch the new tab to Rust → the agent still "remembers" React conventions from the source tab. That's contamination.

### `session_search` behavior

The FTS5 search is cross-session by design — that's its value. But:

- Results are **tool output**, never auto-injected into the system prompt
- System-prompt guidance for the tool: _search cross-session only when the user asks about prior work or you need to recall a specific past decision. Do not search as part of normal task execution._
- Results ranked by `BM25 × recency_decay × same_project_boost` — same-project hits rank higher, cross-project hits still visible (the agent asked for them)

---

## 5. Storage Architecture — A+B Hybrid

Two storage layers with different access patterns. Not either/or — both, for different things.

| Layer                          | Storage              | Why                                                                                                                                        |
| ------------------------------ | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Raw conversation log (Phase 1) | **B: SQLite + FTS5** | FTS5 requires it. Append-only, telemetry-grade, never hand-edited.                                                                         |
| Learned memory (Phase 2)       | **A+B hybrid**       | Markdown = source of truth (human-readable, hand-editable, diff-friendly). SQLite mirror = metadata, timestamps, provenance, fast queries. |

### Why Markdown-as-source-of-truth for learned memory

- Users will want to read and fix what the agent remembers about them. `~/.gator/memory.md` opens in Notepad. A SQLite row doesn't.
- Reviewable in PRs if someone syncs their `.gator/` to a dotfiles repo.
- Survives a DB schema migration even if the SQLite layout changes.
- Bounded size (~3,575 chars total) means the file is small enough to be a file.

### A+B reconciliation when user hand-edits Markdown

Markdown (A) is source of truth for content; SQLite (B) is source of truth for metadata (`created_at`, `source_turn_id`, `project`). User can edit A out-of-band. We detect drift and reconcile.

**Detection: hash check on session start**

```
on session start:
  current_hash = sha256(read(~/.gator/memory.md))
  if current_hash != stored_hash:
    reconcile(~/.gator/memory.md, sqlite_memory_table)
    stored_hash = current_hash
```

Cheap (one file read + hash). Runs once per session start, not per turn. Catches any out-of-band edit.

**Reconciliation: content-hash matching**

Parse Markdown into entries (split on `§` delimiters, matching Hermes format). For each entry, compute content hash. Match against SQLite rows by content hash:

| Markdown entry                     | SQLite row | Action                                                 |
| ---------------------------------- | ---------- | ------------------------------------------------------ |
| Content hash matches existing row  | Found      | No change — preserve `created_at`, `source_turn_id`    |
| New content hash (no match)        | None       | Insert with `source: 'manual_edit'`, `created_at: now` |
| No Markdown entry for existing row | Orphaned   | Delete the row (user removed it)                       |

**Accepted trade-off**: if user _edits_ an existing entry's text, content hash changes → treated as delete-old + add-new. `created_at` resets, `source_turn_id` (provenance) is lost. Acceptable because the user changed the content — old provenance is no longer accurate.

**Upgrade path** (only if metadata loss becomes a real complaint): embed stable IDs as HTML comments:

```markdown
<!-- id: f3a2b1 -->

User prefers TypeScript over JavaScript
```

Match by ID instead of content hash. Survives edits with metadata intact. Adds noise to the file. **Start with hash-based; add ID-comments only if users report the metadata loss.**

### Write path (agent → both stores)

Every `memory_add` / `replace` / `remove` call, in order:

1. Acquire file lock on the Markdown file
2. Write Markdown (atomic: write temp, rename)
3. Upsert/delete SQLite row
4. Update stored hash
5. Release lock

If step 3 fails, Markdown is already written — on next session start, hash check reconciles. **Markdown is always the recovery source.** SQLite is rebuildable from it (minus metadata).

### Edge cases

| Scenario                                       | Handling                                                                                                                                                           |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| User deletes `memory.md` entirely              | File missing on session start → treat as "memory cleared" → delete all SQLite rows for that store → log it. Becomes the undocumented `/memory clear` escape hatch. |
| User's editor has file open while agent writes | Agent writes atomically (temp + rename). Editor shows reload prompt. Standard behavior.                                                                            |
| User adds a brand-new entry by hand            | Content hash has no match → inserted as `source: 'manual_edit'`. Appears in next session's prompt.                                                                 |
| User adds an entry that duplicates an existing | Duplicate-prevention check (same as Hermes) — reject with "no duplicate added."                                                                                    |
| Concurrent: agent writes while user edits      | Last-writer-wins on the file. Next session-start hash check reconciles. Worst case: one entry lost. Acceptable for single-user desktop app.                        |

---

## 6. Phase 1: Persistent Conversation Store + FTS5 Search

**Goal**: Close the acute problem — every chat is lost on restart. Add cross-session recall.

**Implementer**: DeepSeek V4 / Qwen 30B
**Reviewer**: GLM

### 6a. New database

**File**: `~/.gator/sessions.db` (matches `tasks.db` / `scheduler.db` convention)

**Engine**: `aiosqlite` (same as `web/task_queue.py:30` and `web/turn_telemetry.py:44`)

### 6b. Schema

```sql
CREATE TABLE IF NOT EXISTS sessions (
  context_id   TEXT PRIMARY KEY,
  project      TEXT,                    -- active project at creation, for same-project boost
  created_at   TEXT NOT NULL,
  last_active  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  context_id   TEXT NOT NULL,
  role         TEXT NOT NULL,           -- 'user' | 'assistant' | 'system' | 'tool'
  content_json TEXT NOT NULL,           -- full content blocks (text, tool_use, tool_result)
  ts           TEXT NOT NULL,
  FOREIGN KEY (context_id) REFERENCES sessions(context_id) ON DELETE CASCADE
);
CREATE INDEX idx_messages_context ON messages(context_id, ts);

CREATE TABLE IF NOT EXISTS session_summaries (
  context_id   TEXT PRIMARY KEY,
  summary      TEXT NOT NULL,           -- compacted summary of older turns
  summary_up_to INTEGER NOT NULL,       -- message id the summary covers
  updated_at   TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
  content,
  source,                               -- 'chat' | 'workflow_step' | 'workflow_run_summary'
  context_id UNINDEXED,
  project UNINDEXED,
  workflow_id UNINDEXED,                -- null for chat
  step_id UNINDEXED,                    -- null for chat
  timestamp
);
```

**FTS5 availability check** at startup (see §11 for cross-platform):

```python
import sqlite3
conn = sqlite3.connect(":memory:")
try:
    conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
    FTS5_AVAILABLE = True
except sqlite3.OperationalError:
    FTS5_AVAILABLE = False  # fall back to LIKE-based search
```

### 6c. Tiered retrieval (replaces fixed 20-turn window)

`get_window(context_id, model)` returns `[summary_row, ...recent_turns]` instead of `[...recent_turns]`. Token-budget-aware, not turn-count-aware.

| Tier        | What's in the prompt                                         | Source                         | Cost               |
| ----------- | ------------------------------------------------------------ | ------------------------------ | ------------------ |
| **Working** | Last N turns verbatim (N tuned by token budget, ~8-12 turns) | SQLite, recent                 | Always paid        |
| **Summary** | Rolling compacted summary of older turns                     | `session_summaries` table      | Cheap (cached)     |
| **Recall**  | Older turns from _any_ session, on-demand                    | FTS5 via `session_search` tool | Free (no LLM call) |

The existing `compact()` logic at `conversation_store.py:79` stays — but its output (summary) becomes a row in `session_summaries` keyed by `context_id`, not a synthetic user message lost on restart. **Turns that get summarized are NOT deleted** — they move to FTS5-searchable cold storage. You compact for the prompt, you keep for search.

### 6d. `ConversationStore` rewrite

Replace the in-memory `dict` (`web/conversation_store.py:13`) with a SQLite-backed store. Keep the public API (`get_window`, `append`, `compact`) so call sites in `web/routes/chat.py:1455-1456, 1689-1695` don't change.

```python
class ConversationStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._lock = asyncio.Lock()

    async def append(self, context_id: str, turns: list[dict]) -> None: ...
    async def get_window(self, context_id: str, model: str) -> list[dict]: ...
    async def compact(self, context_id: str, model: str) -> None: ...
    async def search(self, query: str, context_id: str | None = None,
                     project: str | None = None, limit: int = 10) -> list[dict]: ...
```

Singleton in `web/shared.py:343` stays — just swap the class.

### 6e. `session_search` tool

**Location**: extend `web/skills/context/` (existing skill) or new `web/skills/search/` — TBD during implementation. Follow `docs/How_to_add_skill.md` contract.

**Tool def**:

```python
{
  "name": "session_search",
  "description": "Search past conversations and workflow runs by keyword. Returns ranked matches with snippets. Use when the user asks about prior work or you need to recall a specific past decision. Do not use as part of normal task execution.",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": {"type": "string", "description": "Search terms"},
      "limit": {"type": "integer", "default": 10, "maximum": 50}
    },
    "required": ["query"]
  }
}
```

**Ranking**: `BM25_score × recency_decay × same_project_boost`

- `recency_decay = exp(-days_old / 30)` — half-life ~21 days
- `same_project_boost = 1.5` if hit's project == current active project, else 1.0

**Fallback** (FTS5 unavailable): `SELECT * FROM messages WHERE content LIKE ? ORDER BY ts DESC LIMIT ?` — slower, unranked, but functional.

### 6f. FTS5 indexing of workflow outputs

To support the workflows feature (`docs/shell-automation-workflows-design.md` Phase 3), `messages_fts` indexes workflow step outputs too. The `source` column distinguishes them:

- `source = 'chat'` — normal chat messages
- `source = 'workflow_step'` — individual step output from `workflow_step_runs.output`
- `source = 'workflow_run_summary'` — workflow-run-level summary (generated by `compact()` logic applied to step outputs)

`session_search` returns hybrid results. A query like "jira sync failure" surfaces both the chat where you discussed it AND the workflow run that actually failed.

The workflow runner (Phase 3 of the workflows design) writes to `messages_fts` after each step completes. The `context_id` for a workflow run is `workflow:{run_id}`.

### 6g. Migration

On first run with the new schema:

1. Create `~/.gator/sessions.db` with the tables above
2. No data to migrate — `ConversationStore` was in-memory only
3. Log "sessions.db initialized" at startup

### Phase 1 review checklist (GLM)

- [ ] `~/.gator/sessions.db` created on first run with all 4 tables (including FTS5 virtual table)
- [ ] FTS5 availability checked at startup; LIKE fallback works if unavailable
- [ ] `ConversationStore` public API unchanged (`get_window`, `append`, `compact`, + new `search`)
- [ ] `get_window` returns `[summary, ...recent_turns]`, token-budget-aware
- [ ] `compact()` writes summary to `session_summaries` table, does NOT delete old turns
- [ ] Old turns remain searchable via FTS5 after compaction
- [ ] `session_search` tool registered, returns ranked results with snippets
- [ ] Ranking applies `recency_decay` and `same_project_boost`
- [ ] `messages_fts.source` column supports `chat` | `workflow_step` | `workflow_run_summary`
- [ ] Singleton in `web/shared.py:343` points to new class
- [ ] Chat works end-to-end after restart (turns persist)
- [ ] No `pyproject.toml` changes (uses stdlib `sqlite3` + existing `aiosqlite`)

---

## 7. Phase 2: Learned Memory via `memory` Skill

**Goal**: Agent curates its own persistent memory — preferences, conventions, lessons learned. The learned analog to today's manually-authored Personas.

**Implementer**: DeepSeek V4 / Qwen 30B
**Reviewer**: GLM

### 7a. New skill package

**Directory**: `web/skills/memory/`

```
web/skills/memory/
  __init__.py     (empty)
  tools.py        (TOOL_DEFS, TOOL_STATUS, TOOL_HANDLERS)
  state.py        (MemoryStore singleton, hash reconciliation, security scan)
```

Zero `app.py` changes — the skill loader (`_load_skill_modules()` in `app.py`) picks it up on restart per `docs/How_to_add_skill.md`.

### 7b. Storage files

| File                           | Purpose                               | Limit                  |
| ------------------------------ | ------------------------------------- | ---------------------- |
| `~/.gator/memory.md`           | Global agent notes                    | 2,200 chars (~800 tok) |
| `~/.gator/user.md`             | User profile (prefs, comms style)     | 1,375 chars (~500 tok) |
| `~/.gator/memory.<project>.md` | Project-scoped memory                 | 2,200 chars (~800 tok) |
| `~/.gator/memory.db`           | SQLite mirror (metadata + provenance) | unbounded              |

Bounded on purpose. No auto-compaction — tool errors when full, agent must consolidate in-turn (Hermes-validated pattern).

### 7c. Markdown format

Matches Hermes format — entries separated by `§` (section sign) delimiters:

```markdown
User's project is a Rust web service at ~/code/myapi using Axum + SQLx§
This machine runs Ubuntu 22.04, has Docker and Podman installed§
User prefers concise responses, dislikes verbose explanations
```

### 7d. SQLite mirror schema

```sql
CREATE TABLE IF NOT EXISTS memory_entries (
  id            INTEGER PRIMARY KEY,
  store         TEXT NOT NULL,          -- 'memory' | 'user' | 'memory.<project>' | 'workflow:<workflow_id>'
  content       TEXT NOT NULL,
  content_hash  TEXT NOT NULL,          -- sha256(content), for reconciliation
  created_at    TEXT NOT NULL,
  source_turn_id TEXT,                  -- null if manually added
  source        TEXT NOT NULL           -- 'agent' | 'manual_edit' | 'background_review' | 'workflow'
);
CREATE INDEX idx_memory_store ON memory_entries(store);

CREATE TABLE IF NOT EXISTS memory_meta (
  store         TEXT PRIMARY KEY,
  content_hash  TEXT NOT NULL,          -- hash of the source Markdown file
  updated_at    TEXT NOT NULL
);
```

`store` is the scoping key that ties back to the scope model in §4.

### 7e. Tools

Three tools, mirroring Hermes's `memory` tool actions:

| Tool             | Action                                    | HITL?                       |
| ---------------- | ----------------------------------------- | --------------------------- |
| `memory_add`     | Add new entry to `memory` or `user` store | Per `write_approval` config |
| `memory_replace` | Replace existing entry (substring match)  | Per `write_approval` config |
| `memory_remove`  | Remove entry (substring match)            | Per `write_approval` config |

No `read` action — memory content is auto-injected into the system prompt at session start.

**Tool def example**:

```python
{
  "name": "memory_add",
  "description": "Add a memory entry to your persistent memory. Use 'memory' target for environment facts, project conventions, lessons learned. Use 'user' target for user preferences, communication style, pet peeves. Do NOT save trivial/obvious info, easily re-discovered facts, raw data dumps, or info already in AGENTS.md/CLAUDE.md/the repo.",
  "input_schema": {
    "type": "object",
    "properties": {
      "target": {"type": "string", "enum": ["memory", "user"], "description": "Which store to write to"},
      "content": {"type": "string", "description": "The memory entry. Compact, information-dense."}
    },
    "required": ["target", "content"]
  }
}
```

### 7f. System-prompt injection

At `web/routes/chat.py:843-1006` (system-prompt assembly), load memory stores per the session-start loader (§4) and render as a frozen block alongside the persona prompt (line 848) and pinned context (line 1008):

```
══════════════════════════════════════════════MEMORY (your personal notes) [67% — 1,474/2,200 chars]══════════════════════════════════════════════User's project is a Rust web service at ~/code/myapi using Axum + SQLx§This machine runs Ubuntu 22.04, has Docker and Podman installed§User prefers concise responses, dislikes verbose explanations
══════════════════════════════════════════════
```

**Frozen snapshot pattern**: captured once at session start, never changes mid-session. Preserves prefix cache for performance. When agent adds/removes memory mid-session, changes persist to disk immediately but won't appear in system prompt until next session. Tool responses always show live state.

### 7g. Capacity management

When a write would exceed the limit, the tool returns an error (not silent drop):

```json
{
  "success": false,
  "error": "Memory at 2,100/2,200 chars. Adding this entry (250 chars) would exceed the limit. Consolidate now: use 'replace' to merge overlapping entries into shorter ones or 'remove' stale entries, then retry this add — all in this turn.",
  "current_entries": ["..."],
  "usage": "2,100/2,200"
}
```

Agent reads the error, consolidates, retries in the same turn.

### 7h. Security scan before accept

Memory entries are scanned for injection/exfiltration patterns before being accepted, since they're injected into the system prompt. Block content matching:

- Prompt injection ("ignore previous instructions", "you are now...")
- Credential exfiltration (API key patterns, `~/.ssh/` paths, AWS keys)
- SSH backdoors / reverse shell patterns
- Invisible Unicode characters (zero-width spaces, etc.)

Non-negotiable for the workflow context — workflows ingest untrusted SaaS content (Jira ticket descriptions, email bodies) that may contain injection.

### 7i. Duplicate prevention

Reject exact duplicate entries. Return success with "no duplicate added" message.

### 7j. `write_approval` config

```yaml
# In ~/.gator/config.json
memory:
  write_approval: false # false = write freely (default) | true = require approval
```

| Setting                        | Behavior                                                                      |
| ------------------------------ | ----------------------------------------------------------------------------- |
| `false` (default, interactive) | Write freely — including from background review                               |
| `true` (interactive)           | Foreground writes prompt inline. Background writes stage to `/memory pending` |
| **Workflow/headless context**  | **Always stage** regardless of setting (see §9)                               |

Review staged writes:

```
/memory pending             # list staged memory writes
/memory approve <id>        # apply one (or 'all')
/memory reject <id>         # drop one (or 'all')
/memory approval on         # turn gate on (or 'off') and persist
```

### 7k. `promote_to_skill` path

Don't silo declarative memory from procedural memory (Gator's existing skills system). `memory_add` accepts an optional `promote_to_skill: true` flag that creates a draft skill under `~/.gator/skills/` instead of a memory entry — for when the agent learns a _procedure_ (how to do something) rather than a _fact_ (that something is true).

The draft skill follows the existing skill contract (`docs/How_to_add_skill.md`). User reviews via `/skills pending` (same gate as Phase 3 background-review skill writes).

### 7l. `/memory` UI commands

| Command                | Action                                           |
| ---------------------- | ------------------------------------------------ |
| `/memory list`         | Show all entries in current scope                |
| `/memory pending`      | Show staged writes (when `write_approval: true`) |
| `/memory approve <id>` | Apply staged write                               |
| `/memory reject <id>`  | Drop staged write                                |
| `/memory clear`        | Wipe all memory (with confirmation)              |
| `/memory edit`         | Open `memory.md` in `$EDITOR`                    |

Settings panel mirrors the existing Personas UI (`web/static/app.js:5843`).

### Phase 2 review checklist (GLM)

- [ ] `web/skills/memory/` package created with `__init__.py`, `tools.py`, `state.py`
- [ ] Skill loader picks it up on restart (zero `app.py` changes)
- [ ] Three tools: `memory_add`, `memory_replace`, `memory_remove`
- [ ] Substring matching for `replace`/`remove` (error on multiple matches)
- [ ] Two targets: `memory` and `user`
- [ ] Hard capacity limits enforced (2,200 / 1,375 chars)
- [ ] Error on overflow includes `current_entries` and `usage`
- [ ] Security scan blocks injection/exfiltration patterns before write
- [ ] Duplicate prevention works
- [ ] Markdown written atomically (temp + rename)
- [ ] SQLite mirror row written on every agent write
- [ ] Hash check on session start reconciles hand-edited Markdown
- [ ] System-prompt injection at `web/routes/chat.py:843` (frozen snapshot)
- [ ] `write_approval` config key respected (false = write, true = stage)
- [ ] `/memory` commands work (`list`, `pending`, `approve`, `reject`, `clear`, `edit`)
- [ ] Project-scoped memory (`memory.<project>.md`) loads only when project active
- [ ] `promote_to_skill` flag creates draft skill instead of memory entry
- [ ] No `pyproject.toml` changes (uses stdlib only)

---

## 8. Phase 3: Background Review Loop

**Goal**: Agent proactively extracts memories after turns without being asked. The "learning loop."

**Implementer**: DeepSeek V4 / Qwen 30B
**Reviewer**: GLM

### 8a. Hook

After the agent loop completes in `web/routes/chat.py` (finally block, ~line 1689), fork a background task that:

1. Replays the turn through the gateway (`web/llm/gateway.py`) on a **cheaper model**
2. Decides what (if anything) to save via the Phase 2 `memory` tool
3. Writes only **staged** memories — never direct (respects `write_approval`)

### 8b. Gateway routing (non-negotiable)

Per CLAUDE.md, the review LLM call goes through `web/llm/gateway.py`, not direct to OpenAI. This is the integration work to scope — the review model must be gateway-routable.

### 8c. Configuration

```yaml
# In ~/.gator/config.json
memory:
  background_review:
    enabled: false # default off — opt-in
    model: 'auto' # 'auto' = main chat model | specific model id for cheaper model
  display:
    memory_notifications: on # off | on (default) | verbose
```

When `model` is set to a model **different** from the main chat model, the review runs there for lower cost (~3-5× in benchmarks). Replays a compact **digest** of the conversation (recent turns verbatim + summary of older ones) rather than full transcript.

### 8d. Workflow/headless context

If the review is running in a workflow context (`context_id` starts with `workflow:`):

- **Always stage** writes (never direct), regardless of `write_approval` setting
- Tag staged writes with `[workflow:{name}]` for source clarity

### 8e. Notifications

After a turn, if the background review saved a memory or patched a skill, surface a short `💾 Memory updated` line in chat. Controllable via `display.memory_notifications`:

| Value          | Behavior                                                                 |
| -------------- | ------------------------------------------------------------------------ |
| `off`          | No chat notification. Review still runs and writes.                      |
| `on` (default) | Generic line, e.g. `💾 Memory updated`                                   |
| `verbose`      | Includes compact preview, e.g. `💾 Memory ➕ User prefers terse replies` |

**Headless variant**: when no visible window (workflow headless mode), `memory_notifications` gains a `headless` sub-setting:

| Value             | Behavior                                                              |
| ----------------- | --------------------------------------------------------------------- |
| `queue` (default) | Writes to `~/.gator/memory_notifications.log` for review on next open |
| `suppress`        | No notification at all                                                |

### 8f. Disable

```yaml
memory:
  background_review:
    enabled: false # skip automatic post-turn forks entirely
```

With `enabled: false`, automatic post-turn forks do not spawn. Manual `/refine` still works (if wired).

### Phase 3 review checklist (GLM)

- [ ] Background review forks after agent loop completion (finally block, ~line 1689)
- [ ] Review LLM call goes through `web/llm/gateway.py` (not direct)
- [ ] Review runs on cheaper model when `model` != `auto`
- [ ] Review replays compact digest when model differs from main
- [ ] Writes are always staged (never direct) — respects `write_approval`
- [ ] Workflow context: always stage, tag with `[workflow:{name}]`
- [ ] `💾 Memory updated` notification renders per `display.memory_notifications`
- [ ] Headless mode: notification queues to log file (or suppresses)
- [ ] `enabled: false` skips the fork entirely
- [ ] Fork usage persisted in `session_model_usage` with `task='background_review'`

---

## 9. Workflow Integration

This design is a companion to `docs/shell-automation-workflows-design.md`. Workflows consume the memory system. Seven concrete deltas from the base memory proposal, all folded into the phases above:

| #   | Delta                                                                  | Where in this doc | Why                                                                          |
| --- | ---------------------------------------------------------------------- | ----------------- | ---------------------------------------------------------------------------- |
| 1   | New **Workflow scope** (`workflow:{workflow_id}.md`)                   | §4                | Workflows need their own memory namespace, not a tab's                       |
| 2   | `context_id` for workflow runs = `workflow:{run_id}`                   | §4, §6f           | Workflows have no tab; gives them a session namespace in `ConversationStore` |
| 3   | Session-start loader gains a **workflow branch**                       | §4                | Different auto-injection rules: workflow memory + user, no project memory    |
| 4   | `write_approval` defaults to **stage** for workflow/headless context   | §7j, §8d          | Unattended runs can't prompt inline; stage for review on next open           |
| 5   | FTS5 index covers **workflow step outputs + run summaries**            | §6f               | `session_search` returns hybrid chat + workflow results                      |
| 6   | `messages_fts` schema gains `source`, `workflow_id`, `step_id` columns | §6b               | Distinguishes chat vs workflow hits, enables filtering                       |
| 7   | `display.memory_notifications` gains `headless: queue\|suppress`       | §8e               | No window to render inline notifications during headless runs                |

### What does NOT change for workflows

- **Workflow definitions are already procedural memory.** `workflow_meta.steps` (workflows design §7a) is the playbook. Don't duplicate it into the memory store.
- **Personas already work.** `workflow_meta.persona_id` means workflow `agent_prompt` steps run as a persona. Memory injection loads `user.md` regardless of persona.
- **HITL confirm gates are separate from memory approval.** Payment-guard pause + memory writes follow normal `write_approval` rule during the pause.
- **A+B sync mechanism is unchanged.** Workflows write through the same `memory_add` tool → atomic Markdown write + SQLite upsert + hash update.
- **Security scan is more important, not different.** Workflows ingest untrusted SaaS content — scan-on-write is the only barrier to prompt-injection persistence.
- **Bounded capacity limits are unchanged.** Workflows don't get a bigger memory budget.
- **Frozen snapshot injection is unchanged.** A workflow run gets its memory snapshot frozen at run start. Writes during the run persist to disk but don't re-inject mid-run. Matters for **resume-from-failure** (workflows design §7c): resumed workflow gets the original frozen snapshot, not accumulated writes from the failed attempt.

### The throughline

**Workflows are a new execution context, not a new memory model.** They reuse every layer (session, project, user, recall) with one addition (workflow scope) and one behavioral override (stage writes when unattended). Design the memory system context-aware, and workflows slot in without rework.

---

## 10. Community Best Practices Applied

Synthesized from Claude Code, Cursor, Cline, Aider, Continue, Roo Code communities, plus MemGPT/Reflexion/generative-agents research:

### Patterns applied

1. **Agents over-save junk** → explicit _don't save_ rules in tool guidance (trivial facts, re-discoverable facts, raw data dumps, session-specific ephemera, info already in AGENTS.md/CLAUDE.md). Capacity limits force selectivity.
2. **Users hate when agents save wrong assumptions** → `write_approval` gate (default off for personal, stage for headless/workflow). `/memory pending` / `/memory reject` / `/memory edit`.
3. **Memory must be scoped per-project** → `memory.<project>.md` namespace, loaded only when project active in tab.
4. **Codebase is already memory** → tool guidance: "if it's already in AGENTS.md/CLAUDE.md/the repo, don't save it." Gator's AGENTS.md is dense — respect it.
5. **Procedural memory > declarative memory for coding agents** → `promote_to_skill` path. Don't build memory as a silo separate from the existing skills system.
6. **Importance scoring, not just recency** → `session_search` ranking: `BM25 × recency_decay × same_project_boost`.
7. **Prompt-injection via memory is a real attack vector** → security scan before accept. Non-negotiable.
8. **Frozen snapshot preserves prefix cache** → memory injected once at session start, never mid-session. Follows existing persona/pinned-context pattern.

### Complaints designed against

- **"Memory grew unbounded and now every prompt is huge"** → hard capacity limits (3,575 chars total). No auto-compaction.
- **"I can't see what the agent remembers about me"** → `/memory list` command + Settings panel mirroring Personas UI.
- **"The agent 'remembers' something from a different project"** → project-scoped namespaces.
- **"Memory feels creepy / I didn't consent to this"** → off by default, `write_approval` gate, transparent UI, easy wipe (`/memory clear`).
- **"The agent saved a memory mid-task and it derailed the task"** → background review runs _after_ the turn, never mid-turn. Foreground saves only on explicit user request or clear learning moment.

---

## 11. Cross-Platform Considerations

### FTS5 availability

FTS5 is part of SQLite itself (not a separate package), available anywhere SQLite ≥ 3.9.0 (2015) is compiled with it.

| Platform | Python's `sqlite3`            | FTS5        | Notes                                                                   |
| -------- | ----------------------------- | ----------- | ----------------------------------------------------------------------- |
| Windows  | Bundled                       | Yes         | Already works — Gator runs here today                                   |
| macOS    | Links system SQLite (Sierra+) | Yes         | Default since 10.12                                                     |
| Linux    | Depends on distro             | Usually yes | Debian/Ubuntu/Fedora/Arch enable it; some minimal/embedded builds don't |

**Design-for-it**: verify FTS5 at startup (§6b). Fall back to `LIKE`-based search if unavailable. The search interface stays the same; only the query path changes.

**Bundling insurance**: if the fallback turns out to be common in practice, add `pysqlite3-binary` to `pyproject.toml` — drop-in that ships a recent SQLite (with FTS5) regardless of system library. One line in deps, `import pysqlite3 as sqlite3` override at top of module. Don't add preemptively — only if real users hit the gap.

### CJK tokenizer

The default `unicode61` tokenizer works cross-platform out of the box for Latin/Cyrillic/Arabic scripts. For Chinese/Japanese/Korean word-breaking, a CJK tokenizer extension is needed (Hermes ships one as a native C extension in `native/fts5_cjk/`). **Not a blocker for Phase 1** — add only if Gator has non-English users reporting poor CJK search quality.

### File permissions

`~/.gator/memory.md` and `user.md` contain user preferences and may contain project context. Apply `0o600` on write (same as `config.json` per the workflows design §1d) on Unix. Windows inherits from parent directory ACLs.

### Atomic writes cross-platform

Atomic file write (temp + rename) works on all platforms. On Windows, `os.replace()` handles the rename atomically even if the destination exists. Use `tempfile.NamedTemporaryFile(delete=False)` + `os.replace()` for portability.

---

## 12. What This Design Does NOT Adopt

| Option                          | Why not                                                                                                                                                                                         |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Honcho** (AGPL-3.0)           | License is an enterprise blocker for a distributed product. Self-hosting Honcho inside a proprietary product = talk to legal.                                                                   |
| **Mem0** (Apache-2.0)           | Safe license, but unnecessary for v1 — the custom Markdown + SQLite mirror covers the same "semantic fact store" use case without an external service. Fallback if Phase 2 proves insufficient. |
| **Zep / Graphiti**              | Requires Neo4j/FalkorDB/Neptune. Too much infra for a local-first desktop app. Gator's users shouldn't need to run a graph database.                                                            |
| **Cognee**                      | Embedded profile (SQLite + LanceDB + Kuzu) is a clean fit, but adds three new dependencies for capability Phase 2 already covers with stdlib. Revisit if KG reasoning becomes a real need.      |
| **Letta** (ex-MemGPT)           | It's a whole agent harness that wants to own the loop. Gator already has `agent_loop.py` — you'd be fighting it.                                                                                |
| **LangChain / LangGraph**       | Per `docs/shell-automation-workflows-design.md` §4: "AI Gator's agent loop is more specialized than LangChain/LangGraph; migration cost > value." Same applies here.                            |
| **Vector store / embeddings**   | Overkill for bounded memory (~3,575 chars). FTS5's BM25 ranking is sufficient for `session_search` at Gator's scale. Revisit if conversation volume makes FTS5 relevance insufficient.          |
| **External LLM for extraction** | Phase 2's `memory_add` is agent-driven (the chat model decides what to save). Phase 3's background review uses the gateway. No direct external LLM calls — honors CLAUDE.md.                    |

---

## 13. Build Order

### Vertical slice (proves end-to-end)

```
Phase 1: Persistent ConversationStore + FTS5 search (full)
Phase 2: memory skill (full, write_approval default off)
```

**Deliverable**: Chats persist across restart. Agent can `session_search` past conversations. Agent saves preferences via `memory_add` that survive restart and load into the next session's system prompt.

### Full build (after slice proves out)

```
Phase 3: Background review loop (behind flag, default off)
+ Project-scoped memory namespaces
+ write_approval gate + /memory pending UI
+ promote_to_skill path
+ Headless notification queueing
```

### Workflow integration (after workflows Phase 3 lands)

```
Workflow scope (workflow:<workflow_id>.md)
context_id = workflow:{run_id} for workflow runs
FTS5 indexing of workflow step outputs
Stage-on-write for workflow/headless context
```

---

## 14. Implementation Guide for Small Models

### General rules

1. **Follow existing patterns exactly.** Read `web/conversation_store.py`, `web/task_queue.py`, `web/turn_telemetry.py` before writing code. Match indentation, naming, error handling style.
2. **One file at a time.** Don't refactor unrelated code. Each change should be minimal and focused.
3. **Use `Read` tool before `Edit`.** Always read the file you're editing first.
4. **Test after each change.** Run `.\dev.ps1` and verify the change works before moving on.
5. **No comments unless asked.** Follow the existing convention.
6. **No new dependencies.** Uses stdlib `sqlite3` + existing `aiosqlite`. Do NOT add `mem0`, `letta`, `chromadb`, `qdrant`, `pinecone`, etc.
7. **Respect the skill contract.** `TOOL_DEFS`, `TOOL_STATUS`, `TOOL_HANDLERS` — see `docs/How_to_add_skill.md`.
8. **Respect the gateway rule.** All LLM calls go through `web/llm/gateway.py`. Phase 3's background review is no exception.
9. **No `Co-Authored-By` lines** in commits.

### Phase 1 implementation order

1. Read `web/conversation_store.py` (full file — it's the class being replaced)
2. Read `web/task_queue.py:30-52` (aiosqlite pattern reference)
3. Read `web/turn_telemetry.py:44-73` (aiosqlite pattern reference)
4. Read `web/shared.py:343-344` (singleton registration)
5. Read `web/routes/chat.py:1452-1456, 1689-1695` (call sites)
6. Create `~/.gator/sessions.db` schema (§6b) — add init function to `web/conversation_store.py`
7. Add FTS5 availability check at module load
8. Rewrite `ConversationStore` class with SQLite backing, same public API + new `search()`
9. Update `get_window()` to return `[summary, ...recent_turns]`
10. Update `compact()` to write to `session_summaries` table, NOT delete old turns
11. Add `search()` method with BM25 × recency_decay × same_project_boost ranking
12. Add LIKE fallback when FTS5 unavailable
13. Test: chat, restart, verify turns persist
14. Test: `session_search` returns ranked results
15. Add `session_search` tool to `web/skills/context/tools.py` (or new `web/skills/search/`)
16. Test: agent can call `session_search` and get results

### Phase 2 implementation order

1. Read `docs/How_to_add_skill.md` (skill contract)
2. Read `web/skills/browser/tools.py` (skill pattern reference)
3. Read `web/routes/config_routes.py:447-555` (personas — the analog feature)
4. Read `web/routes/chat.py:843-1006` (system-prompt assembly — injection point)
5. Create `web/skills/memory/__init__.py` (empty)
6. Create `web/skills/memory/state.py` (MemoryStore: read/write Markdown, SQLite mirror, hash reconciliation, security scan)
7. Create `web/skills/memory/tools.py` (TOOL_DEFS, TOOL_STATUS, TOOL_HANDLERS for `memory_add`, `memory_replace`, `memory_remove`)
8. Add memory injection to `web/routes/chat.py:843` (frozen snapshot at session start, per scope model §4)
9. Add `write_approval` config key to `web/config.py` PATCHABLE_CONFIG_KEYS
10. Add `/memory` commands to `web/routes/` (list, pending, approve, reject, clear, edit)
11. Add `memory.md` / `user.md` / `memory.<project>.md` file creation on first write
12. Test: agent saves a memory, restarts, memory loads into next session
13. Test: hand-edit `memory.md`, restart, verify SQLite reconciles
14. Test: `write_approval: true` stages writes to `/memory pending`
15. Test: security scan blocks injection patterns
16. Test: capacity limit errors when full

### Phase 3 implementation order

1. Read `web/routes/chat.py:1689-1695` (finally block — hook point)
2. Read `web/llm/gateway.py` (gateway routing for review LLM call)
3. Add `background_review` config keys to `web/config.py`
4. Create background review fork function (replays turn, calls `memory_add` with staging)
5. Add workflow-context detection (`context_id` starts with `workflow:` → always stage)
6. Add `💾 Memory updated` notification rendering per `display.memory_notifications`
7. Add headless notification queueing (`~/.gator/memory_notifications.log`)
8. Test: background review saves a memory after a turn (when enabled)
9. Test: workflow context stages writes, tags with `[workflow:{name}]`
10. Test: `enabled: false` skips the fork

### Common pitfalls for small models

1. **Don't delete old turns in `compact()`.** Summarize them, write the summary to `session_summaries`, but keep the original turns in `messages` for FTS5 search.
2. **Don't re-inject memory mid-session.** Frozen snapshot at session start. Tool responses show live state, but the system prompt doesn't change.
3. **Don't add project memory to the prompt if no project is active.** The scope model (§4) is the contamination prevention — follow it exactly.
4. **Don't write memory directly in workflow/headless context.** Always stage. Always tag.
5. **Don't call the LLM directly in Phase 3.** Gateway routing is non-negotiable.
6. **Don't add stable ID comments to Markdown in v1.** Hash-based reconciliation first. Add IDs only if users report metadata loss.
7. **Don't add `pysqlite3-binary` preemptively.** Only if real users hit the FTS5 gap on Linux.
8. **Don't auto-compact memory.** Hard limits + error-on-overflow + agent consolidates in-turn.
9. **Don't skip the security scan.** It's the only barrier to prompt-injection persistence, especially when workflows ingest untrusted SaaS content.

---

## 15. Review Checklist for GLM

After each phase is implemented, GLM should review:

### Security review (all phases)

- [ ] No new dependencies added without approval (especially no `mem0`/`letta`/`chromadb`/`qdrant`)
- [ ] All LLM calls (Phase 3 review) go through `web/llm/gateway.py`
- [ ] Memory entries security-scanned before accept (injection/exfiltration patterns)
- [ ] No secrets logged or exposed in error messages
- [ ] SQL queries use parameterized queries (aiosqlite)
- [ ] `memory.md` / `user.md` get `0o600` after write (Unix)
- [ ] FTS5 unavailable path works (LIKE fallback)
- [ ] No `eval()` or `exec()` on memory content

### Architecture review (all phases)

- [ ] Skill contract followed (`TOOL_DEFS`, `TOOL_STATUS`, `TOOL_HANDLERS`)
- [ ] `ConversationStore` public API unchanged (drop-in replacement)
- [ ] No circular imports introduced
- [ ] `shared.py` mutations are safe (no race conditions on memory writes)
- [ ] Singleton in `web/shared.py:343` points to new class
- [ ] Existing tests still pass (`uv run pytest -q`)
- [ ] No `Co-Authored-By` in commits
- [ ] No comments added unless asked

### Scope/isolation review (Phase 2)

- [ ] Session-start loader follows §4 scope model exactly
- [ ] Project memory loads ONLY when project active in tab
- [ ] Workflow memory loads ONLY for `workflow:{run_id}` context
- [ ] Fork-to-new-tab does NOT copy project memory
- [ ] `session_search` results are tool output, never auto-injected

### A+B reconciliation review (Phase 2)

- [ ] Hash check runs on session start
- [ ] Hand-edited Markdown reconciles to SQLite (content-hash matching)
- [ ] Deleted Markdown file = memory cleared (SQLite rows deleted)
- [ ] Atomic writes (temp + rename) on all platforms
- [ ] Markdown is always the recovery source (SQLite rebuildable)

### Workflow integration review (after workflows Phase 3)

- [ ] `context_id = workflow:{run_id}` for workflow runs
- [ ] Workflow step outputs indexed in `messages_fts` with `source='workflow_step'`
- [ ] `write_approval` defaults to stage in workflow/headless context
- [ ] Staged workflow writes tagged with `[workflow:{name}]`
- [ ] Headless notifications queue to log file (or suppress per config)
- [ ] Resume-from-failure gets original frozen snapshot, not accumulated writes

### Phase-specific review

See the review checklist at the end of each phase section above.

---

**End of document.**
