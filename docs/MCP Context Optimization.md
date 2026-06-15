# MCP Context Optimization

This document describes how AI Gator keeps MCP (Model Context Protocol) connections from poisoning the LLM context window. It covers the problem space, what's shipped today (Phase 2.5), and the full architecture planned for Phase 5.

## The problem

MCP servers return arbitrary JSON. A single call to Atlassian's `searchConfluencePages` can return 500 KB – 1 MB of page bodies; Jira's `getIssues` with full descriptions and comments routinely returns hundreds of KB; even "list resources" calls can dump multi-megabyte arrays.

Three failure modes flow from this:

1. **Tool schemas bloat the system prompt before any call.** 100+ MCP tools × verbose JSON schemas ≈ 100 K+ tokens of overhead. Even on a 1 M-token model that's 10% of the window gone before the user types anything.
2. **Tool responses bloat history after calls.** One oversized response gets appended to `msgs` and is re-sent on every subsequent turn. A single bad call kills the entire conversation.
3. **Parallel dispatch multiplies the damage.** The model frequently calls multiple MCP tools in parallel. Two 500 KB responses arriving in one turn = instant context overflow.

The May 2026 Atlassian incident: a user asked Gator to test two MCP servers (`mcp-mcp` and `mcp-cloud-atlassian`); the model called both in parallel; both returned large payloads; the turn hit **1,005,632 tokens > 1,000,000 maximum**; every subsequent message in the same chat re-sent the bloated history and failed with the same 400.

## Design philosophy

We treat the LLM's context window as a finite, shared resource. MCP tools — being third-party and unknowable — get the most aggressive governance of any tool class in the system. We layer defenses so no single failure mode can corrupt a conversation:

| Layer | Job | Failure mode it stops |
|---|---|---|
| 1. Tool schema compression | Keep prompt small | Schema bloat in system prompt |
| 2. Response virtualization | Keep individual responses bounded | Single-call megabyte dumps |
| 3. Conversation hygiene | Keep history small over time | Accumulation across turns |
| 4. Call-time guardrails | Stop bad calls before they happen | Unbounded queries, parallel storms |

Phase 2.5 (shipped) covers Layer 4 + half of Layer 2 + part of Layer 3 (recovery only). Phase 5 (planned) covers Layers 1, 2 (full), and 3 (full).

---

## Phase 2.5 (shipped May 2026)

### 1. Default-limit injection — `web/mcp/manager.py`

At registration time, scan each MCP tool's `input_schema` for limit-like parameters: `limit`, `maxResults`, `max_results`, `pageSize`, `page_size`, `count`, `top`, `size`, `first`. If found, store the parameter name on the handler closure.

At call time, if the model omitted the param, inject `_DEFAULT_LIMIT_VALUE` (currently 15). Logged so the model's intent is visible:

```
[mcp] injected maxResults=15 on searchJiraIssues (model omitted)
```

This is the cheapest, highest-impact change: a model asking for "all open Jira tickets" no longer dumps 1000 issues.

### 2. MCP response capping — `web/context_utils.py`

`compress_tool_result` already runs on every tool result before it enters `msgs`. We added an MCP-specific branch: any tool whose namespaced name starts with `mcp-` is capped at `MCP_RESPONSE_MAX_CHARS` (30 K chars ≈ 7.5 K tokens).

When a cap fires, the result is replaced with a structured stub:

```json
{
  "result_truncated": "...first 30K chars...",
  "_truncation_note": "[MCP response truncated to 30000 chars from 847291 chars. Re-run with a narrower query (add filters, lower limit/maxResults) or call the tool with a more specific identifier.]",
  "_original_size_bytes": 847291
}
```

The note is written *to* the model so it learns to recover. Unlike the per-turn compression that only fires above 40 K accumulated, MCP capping fires per-response — a single 1 MB response can never reach `msgs`.

### 3. System prompt guidance — `web/routes/chat.py`

When any active skill ID starts with `mcp-`, we append a guidance block to the system prompt teaching the model how to use MCP tools well: narrow queries first, serial over parallel, pick one server when there are duplicates, lookup-then-fetch, recover from truncation by re-querying narrower. This is soft enforcement — the server-side limit injection and response cap are the hard guarantees.

### 4. Auto-prune-and-retry on overflow — `web/agent_loop.py`

If the provider raises an error containing a context-overflow marker (`prompt is too long`, `context_length_exceeded`, etc.), we don't surrender. Instead:

1. Walk `msgs` and find the largest tool result (by character count). Supports both Anthropic-format (content blocks with `type: tool_result`) and OpenAI-format (`role: tool` with string content).
2. Replace its content with a stub:
   > "[Tool result evicted to recover from context overflow (was N chars). Re-call this tool with a narrower query if you still need the data — add filters or lower limit/maxResults.]"
3. Retry the LLM call exactly once. If it fails again, surface the error.

A user-facing status message announces the recovery: `⚠️ Context overflow — pruned a 47KB tool result and retrying...`

Wired into both the single-agent loop and the three-agent (planner/executor/verifier) loop's executor.

**Why retry only once:** if pruning the largest result isn't enough to fit, the conversation has other structural problems (huge system prompt, too many tool schemas) that pruning can't solve. Better to fail clearly than to keep evicting until the chat is rubble.

---

## Phase 5 (planned)

The Phase 2.5 work is necessary but not sufficient. It contains the blast radius of bad MCP behavior but doesn't address the underlying architecture: large data still gets cut off, the model can't drill into it, and tool schemas remain unbudgeted.

### Layer 1: Tool schema compression

**Two-tier schemas.** Each MCP tool currently exposes its full JSON Schema in the system prompt. We'll split into:

- **Tier 1 (in prompt):** `name` + 1-line purpose + parameter names only (no schemas).
- **Tier 2 (on demand):** Full schema fetched via a built-in `get_tool_schema(name)` meta-tool when the model decides to call something.

Cuts MCP overhead 5–10×. Cursor uses this pattern.

**Per-skill tool budget.** Hard cap at N tools (default 20) per MCP skill. Beyond N, expose only an `mcp_search_tools(query)` discovery tool. Model finds the tool it needs instead of seeing all of them.

### Layer 2: Response handles + virtualized retrieval

The proper architectural answer to the response-size problem — borrowed from how Claude Code handles large file reads.

When an MCP tool returns more than a threshold (e.g. 8 KB), we store the full response server-side, keyed by a result ID, and return to the model:

```json
{
  "result_id": "rs_abc123",
  "summary": "47 Confluence pages matched 'authentication'",
  "size_bytes": 412847,
  "preview": "first ~2KB of canonical JSON...",
  "schema_hint": {"type": "array", "item_keys": ["id", "title", "lastModified", "body"]}
}
```

Three new built-in tools operate on result handles:

- `result_read(id, offset=0, limit=None)` — page through bytes
- `result_grep(id, pattern, max_matches=20)` — find specific items
- `result_extract(id, jsonpath)` — pull specific fields ("give me just the titles")

The model learns to drill into a handle instead of swallowing the blob. Old result IDs evict after K turns or N bytes total cache size.

**This replaces the Phase 2.5 hard cap.** Once handles exist, capping at 30 K becomes obsolete — the model can always reach the full data via `result_read`.

### Layer 3: Conversation hygiene

**Sliding-window summarization.** When `msgs` size exceeds (e.g.) 60% of model context, summarize the oldest K turns into a single recap message. Standard pattern in Aider, Cline.

**Stale-tool-result eviction.** Tool results older than K turns get auto-replaced with their summary; the body is dropped. The model rarely re-reads old tool output.

**Better overflow recovery.** With handles in place, the Phase 2.5 prune-and-retry becomes "evict to handle" rather than "evict to stub" — no data is actually lost.

### Layer 4 follow-ups

**Hard parallel cap.** Currently soft (system prompt nudge). Enforce: refuse to dispatch >2 MCP tool calls in parallel within a single skill; queue the rest into the next iteration.

**Schema-aware default limits.** Today we inject `_DEFAULT_LIMIT_VALUE = 15` universally. Smarter: if the tool description contains "search" use 10; "list" use 25; "get" use 1. Or read `default` from the schema if present.

---

## Operational notes

### Tuning knobs

| Constant | File | Default | Notes |
|---|---|---|---|
| `MCP_RESPONSE_MAX_CHARS` | `context_utils.py` | 30000 | Per-response cap (≈7.5K tokens) |
| `_DEFAULT_LIMIT_VALUE` | `mcp/manager.py` | 15 | Injected when model omits limit param |
| `_LIMIT_PARAM_NAMES` | `mcp/manager.py` | (tuple) | Add new MCP server param conventions here |
| `_OVERFLOW_MARKERS` | `agent_loop.py` | (tuple) | Add provider-specific error strings here |
| `COMPRESSION_THRESHOLD_CHARS` | `context_utils.py` | 40000 | Per-turn compression trigger (non-MCP) |

### Diagnosing context blowups

1. Grep the server log for `[overflow]`: lists every prune event with the recovered byte count and msg index.
2. Grep for `[mcp] injected`: shows which tool calls got default limits applied — useful for confirming guardrails fire.
3. Grep for `[tokens]`: per-turn input/output counts; spike here means the previous turn left bloat in history.
4. If a single MCP call legitimately needs more than `MCP_RESPONSE_MAX_CHARS`, raise the cap rather than special-casing the tool — once Phase 5 handles ship, this knob becomes irrelevant.

### Regression tests to add

- Mock MCP server returning 1 MB; verify response is capped at 30 K with truncation note.
- Mock MCP tool with `maxResults` in schema; call without the param; verify `maxResults=15` is injected.
- Two-turn conversation where turn 1 yields a 200 K tool result and turn 2 overflows; verify prune-and-retry produces a successful turn 2 with the stub in place of the original result.
- Verify Slack/Teams/Outlook (non-MCP) tools are unaffected by all of the above.

---

## References

- Anthropic Claude tool use docs: https://docs.anthropic.com/claude/docs/tool-use
- MCP spec: https://modelcontextprotocol.io/specification
- Cursor's two-tier schema pattern: discussed in their public docs on tool selection
- Claude Code's file read offset/limit pattern: same idea applied to MCP responses in Phase 5
