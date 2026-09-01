# AI Gator: Shell Automation + Workflows — Design Document

**Status**: Ready for review
**Date**: August 2026
**Implementation model**: DeepSeek V4 / Qwen 30B (primary), GLM (reviewer)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Decisions Log](#2-decisions-log)
3. [Current Architecture](#3-current-architecture)
4. [Framework Analysis](#4-framework-analysis)
5. [Phase 1: Security Hardening](#5-phase-1-security-hardening)
6. [Phase 2: Shell Control API + shell skill](#6-phase-2-shell-control-api--shell-skill)
7. [Phase 3: Workflow Runner + Data Model + REST API](#7-phase-3-workflow-runner--data-model--rest-api)
8. [Phase 4: Workflow Editor UI](#8-phase-4-workflow-editor-ui)
9. [Phase 5: Headless Mode + Tray](#9-phase-5-headless-mode--tray)
10. [Phase 6: HITL Streaming + Payment Guard](#10-phase-6-hitl-streaming--payment-guard)
11. [Edge Cases](#11-edge-cases)
12. [Build Order](#12-build-order)
13. [Implementation Guide for Small Models](#13-implementation-guide-for-small-models)
14. [Review Checklist for GLM](#14-review-checklist-for-glm)

---

## 1. Overview

### Goal

Enable the AI Gator agent to interact with the Electron shell UI — driving SaaS app panes (OneNote, Teams, Slack, Jira, etc.) via CDP (Chrome DevTools Protocol). Add a workflow system (n8n-style) with scheduling, headless mode, and human-in-the-loop.

### What the agent gains

- **Shell automation**: click, fill, snapshot, navigate, evaluate JS in any pane — using the user's already-authenticated sessions (persistent partitions)
- **Cross-app workflows**: multi-step, branching workflows that span multiple panes (e.g., "Read email in Outlook -> create Jira ticket -> post summary in Teams")
- **Scheduling**: workflows fire on cron/interval/one-shot triggers
- **Headless**: runs in background with tray icon, no visible window

### Why CDP over vision-based approaches

The OneNote demo (adding a page + typing text) was done via chrome-devtools-mcp using a11y-tree snapshots with uid refs. This is 10-100x cheaper than screenshot+vision approaches (Anthropic Computer Use, Skyvern, MultiOn) because:

- No vision model in the hot path
- Deterministic element targeting (uid refs, not coordinates)
- Structured data (a11y tree is JSON, not pixels)
- Works on hidden/headless panes (no rendering needed)

---

## 2. Decisions Log

| #   | Decision        | Choice                                        | Rationale                                                                                  |
| --- | --------------- | --------------------------------------------- | ------------------------------------------------------------------------------------------ |
| 1   | CDP Transport   | HTTP server in shell (port GATOR_PORT+1000)   | Simplest, debuggable, works headed+headless, no renderer coupling                          |
| 2   | Workflow Model  | Separate tables (n8n-style)                   | Reusable workflows, multiple schedules per workflow, per-step execution logs               |
| 3   | Headless        | Tray icon, all platforms                      | Proven setVisible(false) pattern already in use, cross-platform Tray API                   |
| 4   | Editor UX       | Hybrid (form + JSON toggle)                   | Form for common use, JSON for power users/templates                                        |
| 5   | JS Execution    | Full JS (shell_evaluate)                      | Matches chrome-devtools-mcp/Playwright convention, trusted agent                           |
| 6   | Dock navigation | Single dock, two tabs (Workflows + Schedules) | Mirrors n8n separation of definitions vs triggers                                          |
| 7   | Build scope     | Vertical slice first                          | Prove end-to-end before full build                                                         |
| 8   | Framework       | No framework (custom stack)                   | AI Gator's agent loop is more specialized than LangChain/LangGraph; migration cost > value |

---

## 3. Current Architecture

### Components

| Component          | Location                                                         | Role                                                                                                   |
| ------------------ | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Electron shell     | `shell/main.js` (4785 lines)                                     | BrowserWindow with tiled WebContentsViews for each SaaS app                                            |
| FastAPI backend    | `web/app.py`                                                     | REST API, agent loop, task queue, scheduler                                                            |
| Agent loop         | `web/agent_loop.py` (1280 lines)                                 | Three-agent (planner->executor->verifier) with doom-loop detection, overflow pruning, failover consent |
| LLM providers      | `web/llm/base.py`, `anthropic_provider.py`, `openai_provider.py` | Custom `LLMProvider` ABC with `stream_turn()`                                                          |
| LLM gateway        | `web/llm/gateway.py`                                             | All LLM calls go through gateway (non-negotiable per CLAUDE.md)                                        |
| Scheduler          | `web/scheduler.py` (508 lines)                                   | APScheduler + SQLite (`~/.gator/scheduler.db`)                                                         |
| Task queue         | `web/task_queue.py` (275 lines)                                  | Single-worker, FIFO, 1-at-a-time execution                                                             |
| Browser automation | `web/browser_agent.py` (1660 lines)                              | browser_use + CDP for external sites (not shell panes)                                                 |
| Skill system       | `web/skills/*/tools.py`                                          | Drop folder with `TOOL_DEFS`/`TOOL_HANDLERS`, loader picks up on restart                               |

### Key existing patterns to reuse

| Pattern               | Location                                                     | What it does                                                                            |
| --------------------- | ------------------------------------------------------------ | --------------------------------------------------------------------------------------- |
| Confirm-gate          | `browser_agent.py:527-537`, `agent_loop.py:365-380`          | `_pending_confirms` dict + `asyncio.Event` + REST endpoints                             |
| Cursor-based SSE      | `browser_agent.py:_step_updates`, `tasks.py:131-156`         | Thread-locked list, non-destructive cursor reads, 1.5s poll                             |
| Payment guard         | `browser_agent.py:1400`                                      | Detect destructive buttons before click                                                 |
| Pause/resume/cancel   | `browser_agent.py:_paused`/`_cancel_flag`                    | Boolean flags + REST endpoints                                                          |
| Scheduled-job editor  | `web/static/agents-pane.js` (1452 lines)                     | Inline view-swap, `_field()`, `_mkPresets()`, read->edit swap                           |
| View registry         | `shell/main.js:543` (`viewForApp`), `:3852` (`APP_HOME_URL`) | Maps app names to WebContentsView instances                                             |
| Headless pattern      | `shell/main.js:3732-3747` (`setVisible`)                     | N-1 views already run hidden with `setBackgroundThrottling(false)`                      |
| Persistent partitions | `shell/main.js:127-165`                                      | `persist:slack`, `persist:teams`, etc. — authenticated sessions persist across restarts |

### Key gaps found

| Gap                                | Detail                                                             |
| ---------------------------------- | ------------------------------------------------------------------ |
| No `webContents.debugger` usage    | CDP is greenfield in the shell                                     |
| No workflow entity                 | The word "workflow" in `agents-pane.js:573` is just a visual label |
| No persona/model per scheduled job | `_bg_run_fn` (`app.py:456`) ignores personas                       |
| Single-worker queue                | No concurrency (1 task at a time)                                  |
| No retry/dead-letter               | Failed jobs stay failed                                            |
| `opencode_agent` skill gutted      | No `tools.py`; `instance_manager.py` removed                       |
| No CSP on Gator SPA                | `web/static/index.html` has no Content-Security-Policy             |
| Watchdog binds `0.0.0.0`           | `web/watchdog.py:245,404` — LAN-exposed                            |
| No Electron sandbox                | `app.enableSandbox()` never called                                 |
| `config.json` not chmod'd          | Unlike M365/Slack token files                                      |

---

## 4. Framework Analysis

### AI Gator's current stack: no framework

AI Gator uses a **custom stack** — no LangChain, no LangGraph, no CrewAI:

- LLM provider: custom `LLMProvider` ABC (`web/llm/base.py`)
- Agent loop: custom 1280-line three-agent orchestration (`web/agent_loop.py`)
- Tools: custom skill system (`web/skills/*/tools.py`)
- Memory: custom SQLite conversation store (`web/conversation_store.py`)
- Streaming: custom SSE via `provider.stream_turn()` -> `StreamEvent` dicts
- HITL: custom `_pending_confirms` dict + `asyncio.Event` + REST endpoints

The custom agent loop has features no framework offers out of the box: three-agent orchestration (planner->executor->verifier), context-overflow prune-and-retry (5 levels), doom-loop detection (3-strike rule), failover consent gates, circuit breaker for tool errors, turn telemetry.

### Frameworks evaluated

| Framework                  | Verdict              | Rationale                                                                           |
| -------------------------- | -------------------- | ----------------------------------------------------------------------------------- |
| **LangChain**              | Don't adopt          | 4-6 week migration, lose specialized features, integrations already built           |
| **LangGraph**              | Don't adopt (v1)     | Workflow runner is ~200 lines; revisit if adding cycles/subgraphs/time-travel       |
| **CrewAI**                 | Don't adopt          | Redundant with existing three-agent loop                                            |
| **AutoGen**                | Don't adopt          | Redundant with existing three-agent loop                                            |
| **OpenAI Swarm**           | Don't adopt          | Less sophisticated than existing loop                                               |
| **DeepSeek Harness**       | Don't adopt          | Different language (TypeScript/Node), different ecosystem                           |
| **Orca**                   | Borrow concepts      | Design Mode (visual element picker for workflow editor), mobile monitoring (future) |
| **browser_use**            | Keep (already using) | For external-site automation, not shell panes                                       |
| **Anthropic Computer Use** | Don't adopt          | CDP + a11y tree is 10-100x more efficient                                           |

### Decision: no framework change

The plan stands as-is with custom implementation. The custom runner keeps AI Gator decoupled and is ~200 lines. Revisit LangGraph if we add cycles, subgraphs, or time travel in the future.

---

## 5. Phase 1: Security Hardening

**Goal**: Establish security baseline before adding new attack surfaces.

**Implementer**: DeepSeek V4 / Qwen 30B
**Reviewer**: GLM

### 1a. Enable Electron renderer sandbox

**File**: `shell/main.js`

**Changes**:

1. After `app.whenReady()` (around line 45), add: `app.enableSandbox()`
2. At line 1056, change `sandbox: false` -> `sandbox: true` (toolbar view)
3. Verify `toolbar-preload.js` still works (it only uses `contextBridge` + `ipcRenderer`, which are sandbox-safe)

**Test**: Launch the shell. Verify all panes load. Verify toolbar back/forward/reload works. Verify Gator SPA loads.

**Risk**: If `toolbar-preload.js` uses any non-sandbox-safe API, it will fail. It only uses `contextBridge` and `ipcRenderer` (both sandbox-safe), so this should work. If it fails, the fallback is to keep `sandbox: false` on the toolbar only (it loads `file://` content, low risk).

### 1b. Add CSP to the Gator SPA

**File**: `shell/main.js`

**Changes**: After the gatorView is created (around line 963), add a `webRequest.onHeadersReceived` handler on `session.defaultSession`:

```javascript
session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
  if (details.url.startsWith(GATOR_URL)) {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [
          "default-src 'self'; " +
            "script-src 'self'; " +
            "style-src 'self' 'unsafe-inline'; " +
            "img-src 'self' data: blob:; " +
            "connect-src 'self' http://127.0.0.1:*; " +
            "font-src 'self' data:; " +
            "frame-ancestors 'none'",
        ],
      },
    });
  } else {
    callback({ responseHeaders: details.responseHeaders });
  }
});
```

**Important**: Do NOT apply CSP to external app panes (Slack/Teams/etc.) — they set their own CSP. Only apply to responses from `{GATOR_URL}`.

**Test**: Launch shell. Open DevTools on gatorView. Check console for CSP violations. Verify chat works, skills load, agent runs.

### 1c. Fix watchdog loopback binding

**File**: `web/watchdog.py`

**Changes**:

1. Line 245: change `--host 0.0.0.0` -> `--host 127.0.0.1`
2. Line 404: change `ThreadingHTTPServer(('', 8001), ...)` -> `ThreadingHTTPServer(('127.0.0.1', 8001), ...)`

**Test**: Verify packaged app starts/stops backend correctly. Verify `http://localhost:8001/quit` works. Verify external machines cannot reach port 8001.

### 1d. Protect config.json at rest

**File**: `web/config.py`

**Changes**: In `save_config` function (around line 188-191), after writing the JSON file, add:

```python
os.chmod(path, 0o600)
```

**Test**: Save config. Check file permissions on `~/.gator/config.json` (should be `-rw-------` on Unix, owner-restricted on Windows).

### 1e. Code signing (parallel track)

**File**: `shell/package.json`, `.github/workflows/release-desktop.yml`

**Changes**:

- Add `cscLink` / `cscKeyPassword` to electron-builder `win` config (reference secrets)
- Add `hardenedRuntime: true`, `notarize: { teamId: "..." }` to `mac` config
- Wire secrets into GitHub Actions workflow

**Note**: This is a CI/CD effort requiring certificate acquisition. Can run in parallel with Phases 2-6. Does not block implementation.

### Phase 1 review checklist (GLM)

- [ ] `app.enableSandbox()` called after `app.whenReady()`
- [ ] `sandbox: true` on toolbar view
- [ ] `toolbar-preload.js` still functional
- [ ] CSP only applied to `{GATOR_URL}` responses, not external panes
- [ ] CSP allows `connect-src http://127.0.0.1:*` (for shell control API)
- [ ] Watchdog binds `127.0.0.1` (both uvicorn spawn and control server)
- [ ] `config.json` gets `0o600` after save
- [ ] No CSP violations in gatorView console
- [ ] All panes still load and function

---

## 6. Phase 2: Shell Control API + shell skill

**Goal**: Agent can drive any pane via 10 tools. OneNote demo reproducible via agent prompt.

**Implementer**: DeepSeek V4 / Qwen 30B
**Reviewer**: GLM

### 6a. Shell Control API (HTTP server in shell/main.js)

**Location**: Add to `shell/main.js`, after the window/views are created.

**Port**: `{GATOR_PORT + 1000}` (e.g., 9003 for dev on :8003). Derive from `GATOR_PORT` env or the port the backend reports.

**Implementation** (reference — adapt to existing code style):

```javascript
const http = require('http');

let _shellControlServer = null;
let _activeCDPTarget = null;
const _cdpAttached = new Set();

function startShellControlAPI(port) {
  _shellControlServer = http.createServer(async (req, res) => {
    res.setHeader('Content-Type', 'application/json');
    let body = '';
    for await (const chunk of req) body += chunk;
    const params = body ? JSON.parse(body) : {};
    try {
      let result;
      switch (req.url) {
        case '/health':
          result = { ok: true, pid: process.pid, headless: HEADLESS };
          break;
        case '/targets':
          result = listTargets();
          break;
        case '/select-target':
          result = await selectTarget(params.name);
          break;
        case '/snapshot':
          result = await cdpSnapshot(params.target);
          break;
        case '/click':
          result = await cdpClick(params.target, params.uid);
          break;
        case '/fill':
          result = await cdpFill(params.target, params.uid, params.value);
          break;
        case '/navigate':
          result = await cdpNavigate(params.target, params.url);
          break;
        case '/evaluate':
          result = await cdpEvaluate(params.target, params.script);
          break;
        case '/screenshot':
          result = await cdpScreenshot(params.target);
          break;
        case '/wait-for':
          result = await cdpWaitFor(params.target, params.text, params.timeout);
          break;
        case '/press-key':
          result = await cdpPressKey(params.target, params.key);
          break;
        default:
          res.statusCode = 404;
          result = { error: 'Not found' };
      }
      res.end(JSON.stringify(result));
    } catch (e) {
      res.statusCode = 500;
      res.end(JSON.stringify({ error: e.message }));
    }
  });
  _shellControlServer.listen(port, '127.0.0.1');
}
```

Key functions:

- `listTargets()` — enumerates all hardcoded views + `_genericPanes`, returns `[{name, webContentsId, url, partition, loaded}]`
- `getView(name)` — uses existing `viewForApp()` (main.js:543)
- `ensureCDPAttached(view)` — lazy `webContents.debugger.attach('1.3')` per view
- `selectTarget(name)` — attaches CDP, sets `_activeCDPTarget`
- `cdpSnapshot(target)` — `Accessibility.getFullAXTree` (traverses iframes automatically)
- `cdpClick(target, uid)` — resolve uid -> `DOM.resolveNode` -> `DOM.getBoxModel` -> `Input.dispatchMouseEvent`
- `cdpFill(target, uid, value)` — click to focus, then `Input.insertText`
- `cdpNavigate(target, url)` — `webContents.loadURL(url)` (returns promise)
- `cdpEvaluate(target, script)` — `Runtime.evaluate` with `returnByValue: true, awaitPromise: true`
- `cdpScreenshot(target)` — `Page.captureScreenshot` format=png
- `cdpWaitFor(target, text, timeout)` — poll `Runtime.evaluate` every 200ms
- `cdpPressKey(target, key)` — `Input.dispatchKeyEvent` keyDown + keyUp

**Binding**: `127.0.0.1` only. No external access.

**Cleanup**: On `before-quit`, detach all debuggers and close the server.

### 6b. Shell registration with backend

**New endpoints** (in `web/routes/health.py` or new `web/routes/shell.py`):

- `POST /api/shell/register` — body: `{port, pid, headless}`, stores in `shared.shell_info`
- `GET /api/shell/status` — returns registered shell info or null
- `DELETE /api/shell/register` — clears `shared.shell_info`

**Shell-side**: After `waitForBackend` completes, POST to `{GATOR_URL}/api/shell/register`.

**Health check**: Backend polls `http://127.0.0.1:{port}/health` every 30s. If unhealthy, clears `shared.shell_info`.

### 6c. shell skill

**New directory**: `web/skills/shell/`

```
web/skills/shell/
  __init__.py     (empty)
  tools.py        (TOOL_DEFS, TOOL_STATUS, TOOL_HANDLERS)
```

10 tools, each maps to a Shell Control API endpoint:

| Tool                  | Endpoint              | Returns                    | HITL?           |
| --------------------- | --------------------- | -------------------------- | --------------- |
| `shell_list_targets`  | `GET /targets`        | `[{name, url, partition}]` | No              |
| `shell_select_target` | `POST /select-target` | `{ok, webContentsId}`      | No              |
| `shell_snapshot`      | `POST /snapshot`      | `{tree: [a11y nodes]}`     | No              |
| `shell_click`         | `POST /click`         | `{ok}`                     | Payment-guard\* |
| `shell_fill`          | `POST /fill`          | `{ok}`                     | No              |
| `shell_navigate`      | `POST /navigate`      | `{ok, url}`                | No              |
| `shell_evaluate`      | `POST /evaluate`      | `{result}`                 | No (full JS)    |
| `shell_screenshot`    | `POST /screenshot`    | `{base64}`                 | No              |
| `shell_wait_for`      | `POST /wait-for`      | `{ok, matched}`            | No              |
| `shell_press_key`     | `POST /press-key`     | `{ok}`                     | No              |

\*Payment-guard: before clicking buttons matching `Send|Delete|Submit|Pay|Purchase|Remove|Confirm|Post`, pause for HITL confirmation.

Each tool handler:

1. Check `shared.shell_info` — if null, return clear error
2. POST to `http://127.0.0.1:{port}/{endpoint}` via `httpx`
3. Return result to agent

Follow the pattern in `web/skills/browser/tools.py`.

### 6d. Verification

The OneNote demo should be reproducible via this agent prompt:

> "Go to OneNote, add a page called 'Gator Test', and type 'Gator Type Text' in the body"

The agent should:

1. Call `shell_list_targets` -> sees "onenote"
2. Call `shell_select_target` with `{"name": "onenote"}`
3. Call `shell_snapshot` -> gets a11y tree with "Add page" button
4. Call `shell_click` with the button's uid
5. Call `shell_snapshot` -> finds the title input
6. Call `shell_click` on the title input
7. Call `shell_fill` with "Gator Test"
8. Call `shell_press_key` with "Enter"
9. Call `shell_fill` (or `shell_press_key` for each char) with "Gator Type Text"

### Phase 2 review checklist (GLM)

- [ ] HTTP server binds `127.0.0.1` only
- [ ] Port derived from `GATOR_PORT + 1000`
- [ ] `listTargets()` enumerates all hardcoded views + `_genericPanes`
- [ ] CDP attach is lazy (only on first command to a target)
- [ ] CDP detach on app quit
- [ ] `shell_snapshot` returns a11y tree with uid refs
- [ ] `shell_click` resolves uid -> bounding box -> mouse events
- [ ] `shell_evaluate` runs full JS with `returnByValue: true`
- [ ] `shell_wait_for` polls at 200ms, respects timeout
- [ ] `shell` skill follows `TOOL_DEFS`/`TOOL_HANDLERS` contract
- [ ] `_call_shell` checks `shared.shell_info` and returns clear error if null
- [ ] Registration POST fires after `waitForBackend` completes
- [ ] Health check runs every 30s, deregisters if unhealthy
- [ ] OneNote demo reproducible via agent prompt

---

## 7. Phase 3: Workflow Runner + Data Model + REST API

**Goal**: Workflows executable via API. 2-step workflow test proves end-to-end.

**Implementer**: DeepSeek V4 / Qwen 30B
**Reviewer**: GLM

### 7a. Data model

**Database**: `~/.gator/scheduler.db` (existing SQLite DB)

**4 new tables** (add to `web/scheduler.py` init, after existing `job_meta`/`job_history` DDL):

```sql
CREATE TABLE IF NOT EXISTS workflow_meta (
  workflow_id   TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  description   TEXT,
  steps         TEXT NOT NULL,
  persona_id    TEXT,
  model         TEXT,
  headless      INTEGER DEFAULT 0,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schedule_meta (
  schedule_id   TEXT PRIMARY KEY,
  workflow_id   TEXT NOT NULL,
  name          TEXT,
  trigger_type  TEXT NOT NULL,
  trigger_args  TEXT NOT NULL,
  enabled       INTEGER DEFAULT 1,
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_runs (
  run_id        TEXT PRIMARY KEY,
  workflow_id   TEXT NOT NULL,
  schedule_id   TEXT,
  status        TEXT NOT NULL,
  started_at    TEXT NOT NULL,
  completed_at  TEXT,
  context       TEXT,
  error         TEXT
);

CREATE TABLE IF NOT EXISTS workflow_step_runs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id        TEXT NOT NULL,
  step_id       TEXT NOT NULL,
  status        TEXT NOT NULL,
  started_at    TEXT,
  completed_at  TEXT,
  output        TEXT,
  error         TEXT,
  retries       INTEGER DEFAULT 0
);
```

Use `CREATE TABLE IF NOT EXISTS` for idempotent creation.

### 7b. Step definition format

```json
{
  "steps": [
    {
      "id": "step_1",
      "name": "Human-readable name",
      "type": "shell_action | agent_prompt | condition | delay",
      "params": {},
      "depends_on": ["step_0"],
      "outputs": { "var_name": "type" }
    }
  ]
}
```

**Step types**:

| Type           | Params                                                         | Example                                                                      |
| -------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `shell_action` | `target`, `action`, `description`, plus action-specific params | `{"target": "onenote", "action": "click", "description": "Click Add page"}`  |
| `agent_prompt` | `prompt`, `tools` (optional)                                   | `{"prompt": "Read latest email and summarize", "tools": ["shell_snapshot"]}` |
| `condition`    | `if`, `then`, `else`                                           | `{"if": "${check.exists} == true", "then": "notify", "else": "create"}`      |
| `delay`        | `seconds`                                                      | `{"seconds": 2}`                                                             |

**Data flow**: `${step_id.output_var}` references resolved from `context` dict before execution.

### 7c. Workflow runner

**New file**: `web/workflow_runner.py`

DAG walker that executes steps in dependency order:

```python
async def execute_workflow(workflow_id: str, schedule_id: str | None = None) -> str:
    # 1. Load workflow_meta
    # 2. Create workflow_runs row (status='running')
    # 3. Topological sort steps by depends_on
    # 4. For each step in order:
    #    a. Create workflow_step_runs row (status='running')
    #    b. Resolve ${step_id.output_var} refs in params from context
    #    c. Execute by type:
    #       - shell_action: call shell skill tool
    #       - agent_prompt: run agent loop (with shell tools + persona + model)
    #       - condition: evaluate expression, set next step
    #       - delay: asyncio.sleep
    #    d. Store output in context[step_id] = output
    #    e. Update workflow_step_runs (status='done', output=...)
    #    f. Stream step update via SSE
    # 5. On failure: set workflow_runs.status='failed', record error, stop
    # 6. On success: set workflow_runs.status='done'
    # 7. On HITL pause: set status='paused', wait for resume
```

Key functions:

- `_topological_sort(steps)` — DFS sort by `depends_on`, raises on cycles
- `_resolve_refs(params, context)` — regex replace `${step_id.output_var}` from context dict
- `_exec_shell_action(params)` — maps action to shell tool handler, calls via `TOOL_HANDLERS`
- `_exec_agent_prompt(params, workflow)` — runs agent loop with persona/model from workflow
- `_exec_condition(params, context)` — evaluates `==` and `!=` expressions, returns `{branch, result}`
- `get_step_updates(run_id, cursor)` — non-destructive cursor read for SSE (thread-safe via `asyncio.Lock`)
- `_push_step_update(run_id, update)` — append to `_step_updates[run_id]`

Key behaviors:

- **Resume from failure**: `workflow_step_runs` tracks completed steps. Re-running skips done steps.
- **Retry**: per-step `retries` counter. Configurable max retries (default 0).
- **Data flow**: `${step_id.output_var}` resolved from context before execution.
- **Condition branching**: `condition` step sets `then` or `else` as next step. Steps not on taken branch marked `skipped`.
- **Persona/model**: `agent_prompt` steps use workflow's `persona_id` and `model` (falls back to global default).

### 7d. Scheduler integration

**File**: `web/scheduler.py`

Add `_execute_schedule(schedule_id)`:

- Load `schedule_meta`
- If enabled, call `workflow_runner.execute_workflow(schedule.workflow_id, schedule_id)`

Register with APScheduler: when a `schedule_meta` row is created/updated, add/modify APScheduler job with `func=_execute_schedule, args=[schedule_id]`.

### 7e. REST API

**New file**: `web/routes/workflows.py`

```
GET    /api/workflows                    — list all workflows
GET    /api/workflows/{id}               — get workflow + steps
POST   /api/workflows                    — create workflow
PATCH  /api/workflows/{id}               — update (name, description, steps, persona_id, model, headless)
DELETE /api/workflows/{id}               — delete workflow
POST   /api/workflows/{id}/run           — manual run (returns run_id)
GET    /api/workflows/{id}/runs          — execution history
GET    /api/workflows/{id}/runs/{run_id} — single run with per-step status
POST   /api/workflows/{id}/runs/{run_id}/resume — resume from paused/failed
GET    /api/workflows/{id}/export        — export as JSON
POST   /api/workflows/import             — import from JSON
```

**New file**: `web/routes/schedules.py`

```
GET    /api/schedules                    — list all schedules
GET    /api/schedules/{id}               — get schedule
POST   /api/schedules                    — create (references workflow_id)
PATCH  /api/schedules/{id}               — update (name, trigger, enabled)
DELETE /api/schedules/{id}               — delete schedule
POST   /api/schedules/{id}/pause         — pause
POST   /api/schedules/{id}/resume        — resume
POST   /api/schedules/{id}/run-now       — immediate trigger
GET    /api/schedules/{id}/history       — execution history
```

Mirror the shape of existing `web/routes/scheduler.py`.

### 7f. Migration (deferred to full build)

On startup, if `job_meta` has rows with no corresponding `workflow_meta`:

1. For each `job_meta` row, create a `workflow_meta` with one `agent_prompt` step
2. Create a `schedule_meta` referencing the new workflow
3. Leave `job_meta` intact (backward compat)
4. Log migration count

### Phase 3 review checklist (GLM)

- [ ] 4 tables created with `CREATE TABLE IF NOT EXISTS`
- [ ] `_topological_sort` handles `depends_on` and detects cycles
- [ ] `_resolve_refs` replaces `${step_id.output_var}` patterns
- [ ] `shell_action` step calls the correct shell tool handler
- [ ] `agent_prompt` step runs the agent loop with persona/model from workflow
- [ ] `condition` step evaluates `==` and `!=` expressions
- [ ] `delay` step uses `asyncio.sleep`
- [ ] `workflow_runs` and `workflow_step_runs` rows created/updated correctly
- [ ] `get_step_updates` is a non-destructive cursor read (thread-safe)
- [ ] REST API mirrors `scheduler.py` patterns
- [ ] Scheduler fires `execute_workflow` on trigger

---

## 8. Phase 4: Workflow Editor UI

**Goal**: User can create, edit, schedule, and run workflows via UI.

**Implementer**: DeepSeek V4 / Qwen 30B
**Reviewer**: GLM

### 8a. Single dock, two tabs

Rename the "Agents" dock to show two tabs: **Workflows** and **Schedules**. Mirrors n8n's separation of definitions vs triggers.

### 8b. New file: `web/static/workflows-pane.js`

Mirror `agents-pane.js` patterns:

- Inline view-swap (list -> detail -> new form)
- `_field(label, el)` helper for form rows
- `_mkPresets(input, presets)` for quick-fill chips
- Inline read->edit swap for prompts
- `_showConfirmModal` for deletes
- `ap-card-btn` classes

**Form view** (default):

- Vertical step list, drag-to-reorder
- Each step: type icon, name, params (inline edit), delete button
- Type selector: shell_action, agent_prompt, condition, delay
- Dynamic fields per type
- "Add step" button

**JSON toggle**:

- "Edit JSON" button in header
- Swaps to `<textarea>` with full workflow JSON
- "Apply" validates and returns to form view
- Validation: required fields, valid step types, `depends_on` refs exist, no cycles

**Schedule editor**: reuse trigger fields from `agents-pane.js` (cron/interval/date, timezone, start/end)

**Persona selector**: dropdown listing personas from config

**Model selector**: dropdown listing models from active LLM profile

**Headless toggle**: visual / headless

**Run History**: per-run status, per-step status, resume button, error details

### 8c. Design Mode (borrowed from Orca)

When building a `shell_action` step, the user can click "Pick element" — this:

1. Calls `shell_snapshot` on the selected target
2. Overlays clickable highlights on the pane (via `shell_evaluate` injecting CSS)
3. User clicks an element -> its uid auto-populates the step's params
4. Removes the overlay

This bridges the gap between the form editor and visual workflow building.

### Phase 4 review checklist (GLM)

- [ ] Two tabs (Workflows + Schedules) in single dock
- [ ] Form view: step cards, drag-to-reorder, type selector, dynamic fields
- [ ] JSON toggle: textarea, validate on apply, error messages
- [ ] JSON validation: required fields, valid types, `depends_on` refs, no cycles
- [ ] Schedule editor reuses `agents-pane.js` trigger fields
- [ ] Persona + model selectors populated from config
- [ ] Headless toggle present
- [ ] Run history shows per-step status
- [ ] Design Mode: "Pick element" calls `shell_snapshot`, overlays highlights, auto-populates uid
- [ ] Follows existing CSS patterns (`ap-card-btn`, `ap-*` classes)

---

## 9. Phase 5: Headless Mode + Tray

**Goal**: `electron . --headless` runs with no visible window, tray icon, workflows run in background.

**Implementer**: DeepSeek V4 / Qwen 30B
**Reviewer**: GLM

### 9a. --headless flag

**File**: `shell/main.js`

```javascript
const HEADLESS = process.argv.includes('--headless');

// In createWindow():
const win = new BrowserWindow({
  show: !HEADLESS,
  // ...existing options
});
```

All views created with `setVisible(false)` in headless mode. `setBackgroundThrottling(false)` already set on all external views.

### 9b. Tray icon (cross-platform)

```javascript
const { Tray, Menu, nativeImage } = require('electron');
let tray = null;

function createTray() {
  const icon = nativeImage.createFromPath(
    require('path').join(__dirname, '..', 'tray', 'aigator_icon.png'),
  );
  tray = new Tray(icon);
  tray.setToolTip('AI Gator');

  const showWindow = () => {
    win.show();
    if (process.platform === 'darwin') app.dock.show();
    if (activeExternalApp) viewForApp(activeExternalApp)?.setVisible(true);
  };
  const hideWindow = () => {
    win.hide();
    if (process.platform === 'darwin') app.dock.hide();
  };

  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: 'Show', click: showWindow },
      { label: 'Hide', click: hideWindow },
      { type: 'separator' },
      { label: 'Quit', click: () => app.quit() },
    ]),
  );
  tray.on('click', () => {
    win.isVisible() ? hideWindow() : showWindow();
  });
}

if (HEADLESS) createTray();
```

### 9c. Per-workflow headless toggle

The `headless` column on `workflow_meta`:

- `headless=1`: window stays hidden during execution
- `headless=0` (visual): window shows, active pane brought to front

### 9d. Platform notes

| Platform | Behavior                                              | Notes                                   |
| -------- | ----------------------------------------------------- | --------------------------------------- |
| Windows  | System tray icon. Click toggles window.               | Works out of the box                    |
| macOS    | Menu bar icon. `app.dock.hide()` / `app.dock.show()`. | Must call dock.hide to remove from Dock |
| Linux    | System tray. Requires `libappindicator3-1`.           | Add to electron-builder `linux.depends` |

### Phase 5 review checklist (GLM)

- [ ] `--headless` flag parsed correctly
- [ ] `show: false` when headless
- [ ] Tray icon created on all platforms
- [ ] `app.dock.hide()` called on macOS
- [ ] Tray click toggles window visibility
- [ ] Views remain functional when hidden (`setVisible(false)` + `setBackgroundThrottling(false)`)
- [ ] Per-workflow headless toggle respected during execution
- [ ] Shell Control API works identically headed/headless

---

## 10. Phase 6: HITL Streaming + Payment Guard

**Goal**: Real-time workflow streaming, confirm gates, destructive-action protection.

**Implementer**: DeepSeek V4 / Qwen 30B
**Reviewer**: GLM

### 10a. SSE streaming

**New endpoint**: `GET /api/workflows/{id}/runs/{run_id}/stream`

Mirrors `/api/browser/stream` (`web/routes/tasks.py:131-156`):

```python
async def _gen():
    yield 'data: {"type": "connected"}\n\n'
    cursor = 0
    while True:
        updates, cursor = await workflow_runner.get_step_updates(run_id, cursor)
        for update in updates:
            yield f'data: {json.dumps({"type": "step", **update})}\n\n'
        status = await workflow_runner.get_run_status(run_id)
        yield f'data: {json.dumps({"type": "status", "status": status})}\n\n'
        if status in ('done', 'failed'):
            yield 'data: {"type": "done"}\n\n'
            break
        await asyncio.sleep(1.5)
```

Step updates include: step_id, step_name, type, status, output (truncated), screenshot (if shell_action).

### 10b. Confirm gate

Reuse the confirm-gate pattern from `browser_agent.py:527-537`:

```python
_pending_workflow_confirms: dict[str, tuple[asyncio.Event, list]] = {}

async def request_workflow_confirm(run_id, step_id, action):
    confirm_id = f"{run_id}:{step_id}"
    event = asyncio.Event()
    result = []
    _pending_workflow_confirms[confirm_id] = (event, result)
    await _push_step_update(run_id, {"type": "confirm", "confirm_id": confirm_id, "action": action})
    await event.wait()
    return result[0]

def resolve_workflow_confirm(confirm_id, allowed):
    event, result = _pending_workflow_confirms.pop(confirm_id)
    result.append(allowed)
    event.set()
```

**Endpoints**:

- `POST /api/workflows/runs/{run_id}/confirm/{step_id}` — approve
- `POST /api/workflows/runs/{run_id}/confirm/{step_id}/cancel` — deny

### 10c. Payment guard on shell_click

Before clicking buttons matching destructive patterns (`Send|Delete|Submit|Pay|Purchase|Remove|Confirm|Post`), the `shell_click` tool handler:

1. Takes a snapshot of the target element
2. Checks if button text/aria-label matches destructive patterns
3. If match -> calls `request_workflow_confirm(run_id, step_id, f"Click '{button_text}' on {target}?")`
4. Waits for user approval via SSE + endpoint
5. If approved -> proceeds with click
6. If denied -> step fails with "User denied action"

Reuses the pattern from `browser_agent.py:1400` (`_install_payment_guard`).

### 10d. Pause/resume/cancel

```
POST /api/workflows/runs/{run_id}/pause    — pause after current step
POST /api/workflows/runs/{run_id}/resume   — resume
POST /api/workflows/runs/{run_id}/cancel   — cancel immediately
```

Reuses the flag pattern from `browser_agent.py` (`_paused`, `_cancel_flag` globals + REST endpoints).

### Phase 6 review checklist (GLM)

- [ ] SSE endpoint mirrors `/api/browser/stream` pattern
- [ ] Step updates include step_id, name, type, status, output
- [ ] Confirm gate uses `asyncio.Event` pattern (matches `browser_agent.py:527-537`)
- [ ] Confirm/approve/cancel endpoints work
- [ ] Payment guard checks button text before destructive clicks
- [ ] Pause/resume/cancel flags respected in workflow runner loop
- [ ] SSE `done` event sent when workflow completes/fails

---

## 11. Edge Cases

| #   | Edge case                       | Handling                                                                                                                                       | Phase |
| --- | ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ----- |
| 1   | Pane not loaded yet             | `shell_wait_for` polls `document.readyState` with timeout. `webContents.loadURL()` returns promise.                                            | 2     |
| 2   | Auth expired                    | `shell_snapshot` detects login page patterns (reuse `AUTH_RE` from `navigation-policy.js:47`). Pause workflow, notify user.                    | 2, 6  |
| 3   | Cross-origin iframes            | CDP `Accessibility.getFullAXTree` traverses automatically. `Runtime.evaluate` enumerates execution contexts per frame. Proven in OneNote demo. | 2     |
| 4   | Bot detection                   | Reuse heuristics from `browser_agent.py:246-275`. Pause workflow, show CAPTCHA if headed.                                                      | 6     |
| 5   | Navigation policy bypass        | CDP `Page.navigate` bypasses `will-navigate`. Add URL allowlist in Shell Control API — `https://` only, block `file://`, `javascript:`.        | 2     |
| 6   | Concurrent workflows            | Single-worker queue (existing `task_queue.py`). Documented limitation. Future: worker pool.                                                    | 3     |
| 7   | Shell not running               | `shell` skill checks registration. If null, return clear error. Scheduled workflows fail with error in `workflow_runs`.                        | 2     |
| 8   | Element not found / DOM changed | `shell_click` re-snapshots if uid is stale. Retry 3x with 500ms backoff.                                                                       | 2     |
| 9   | Large a11y trees                | Truncate `shell_snapshot` to 500 elements. Add `{filter: "buttons"}` param for targeted snapshots.                                             | 2     |
| 10  | Multiple shell instances        | Last registration wins. Health-check every 30s, deregister if unhealthy.                                                                       | 2     |
| 11  | SSO popup windows               | `navigation-policy.js` handles auth popups. In headless, popups need surfacing or auto-handling.                                               | 5     |
| 12  | Payment/destructive actions     | Payment-guard on `shell_click`. HITL confirm before destructive buttons.                                                                       | 6     |

---

## 12. Build Order

### Vertical slice (proves end-to-end)

```
Phase 1: Security Hardening (full)
Phase 2: Shell Control API + shell skill (full)
Phase 3a-e: Workflow runner + data model + REST API (minimal, no migration)
Phase 6a-b: Basic SSE + confirm gate (minimal)
```

**Deliverable**: A 2-step workflow (navigate OneNote -> click "Add page") executable via API with real-time SSE streaming.

### Full build (after slice proves out)

```
Phase 3f: Migration from job_meta
Phase 4: Workflow editor UI (single dock, two tabs)
Phase 5: Headless + tray
Phase 6c-e: Payment guard, pause/resume/cancel
```

---

## 13. Implementation Guide for Small Models

This section provides guidance for DeepSeek V4 / Qwen 30B implementing each phase.

### General rules

1. **Follow existing patterns exactly.** Read the referenced files before writing code. Match indentation, naming, error handling style.
2. **One file at a time.** Don't refactor unrelated code. Each change should be minimal and focused.
3. **Use `Read` tool before `Edit`.** Always read the file you're editing first to understand context.
4. **Test after each change.** Run the dev server (`.\dev.ps1`) and verify the change works before moving on.
5. **No comments unless asked.** Follow the existing convention — the codebase has minimal comments.
6. **No new dependencies.** The stack is `uv` + FastAPI + Electron. Use what's already installed. `httpx` is already available for HTTP calls.
7. **Respect the skill contract.** `TOOL_DEFS`, `TOOL_STATUS`, `TOOL_HANDLERS` — see `docs/How_to_add_skill.md`.
8. **Respect the gateway rule.** All LLM calls go through `web/llm/gateway.py`. Never construct gateway headers/URLs inline.
9. **No `Co-Authored-By` lines** in commits.

### Phase 1 implementation order

1. Read `shell/main.js` lines 40-55 (app ready) and 1051-1060 (toolbar view)
2. Add `app.enableSandbox()` after `app.whenReady()`
3. Change `sandbox: false` -> `sandbox: true` at line 1056
4. Test: launch shell, verify toolbar works
5. Read `shell/main.js` lines 945-970 (gatorView creation)
6. Add `session.defaultSession.webRequest.onHeadersReceived` CSP injection
7. Test: verify no CSP violations in console
8. Read `web/watchdog.py` lines 240-260 and 400-410
9. Change `0.0.0.0` -> `127.0.0.1` (two places)
10. Test: verify packaged app starts/stops correctly
11. Read `web/config.py` lines 185-195 (save_config)
12. Add `os.chmod(path, 0o600)` after file write
13. Test: save config, verify permissions

### Phase 2 implementation order

1. Read `shell/main.js` lines 543-555 (`viewForApp`) and 3852-3880 (`APP_HOME_URL`)
2. Read `shell/main.js` lines 726-740 (view variable declarations)
3. Add `startShellControlAPI(port)` function (reference in section 6a)
4. Call `startShellControlAPI(GATOR_PORT + 1000)` after `waitForBackend` completes
5. Add cleanup on `before-quit` (detach debuggers, close server)
6. Read `web/skills/browser/tools.py` (skill pattern reference)
7. Create `web/skills/shell/__init__.py` (empty)
8. Create `web/skills/shell/tools.py` (reference in section 6c)
9. Add `shell_info` to `web/shared.py`
10. Add `/api/shell/register`, `/api/shell/status`, `DELETE /api/shell/register` endpoints
11. Add health-check timer (30s poll)
12. Test: launch shell, verify `GET http://localhost:9003/health` responds
13. Test: verify `GET http://localhost:9003/targets` lists all panes
14. Test: OneNote demo via agent prompt

### Phase 3 implementation order

1. Read `web/scheduler.py` lines 41-69 (existing table DDL)
2. Add 4 new `CREATE TABLE IF NOT EXISTS` statements
3. Create `web/workflow_runner.py` (reference in section 7c)
4. Add `_execute_schedule` to `web/scheduler.py`
5. Wire APScheduler to call `_execute_schedule` for schedule_meta jobs
6. Create `web/routes/workflows.py` (mirror `web/routes/scheduler.py`)
7. Create `web/routes/schedules.py` (mirror `web/routes/scheduler.py`)
8. Register routers in `web/app.py`
9. Test: create workflow via API, run it, verify SSE stream

### Common pitfalls for small models

1. **CDP attach is per-webContents, not per-app.** Each view has its own `webContents.debugger`. Don't try to attach once globally.
2. **`Accessibility.getFullAXTree` returns nodes, not a tree.** The response is `{ nodes: [...] }`. Each node has `nodeId`, `role`, `name`, `childIds`. This is the `uid` the agent uses for clicking.
3. **`viewForApp()` returns a `WebContentsView`, not a `webContents`.** Access via `view.webContents`.
4. **The shell and backend are separate processes.** The shell's HTTP server is the only bridge. Don't try to import Python modules into the shell.
5. **`_genericPanes` may be empty.** Custom panes are created on demand. Handle empty case.
6. **Don't modify `navigation-policy.js`.** CDP `Page.navigate` bypasses it anyway. Add URL allowlist in the Shell Control API instead.
7. **`shared.shell_info` is a dict, not a module-level variable in `shared.py`.** Add it as `shell_info: dict | None = None` to the `shared` module.
8. **The agent loop is in `web/agent_loop.py`, not the shell.** Workflow `agent_prompt` steps call into the backend's agent loop, not the shell.

---

## 14. Review Checklist for GLM

After each phase is implemented, GLM should review:

### Security review (all phases)

- [ ] No new dependencies added without approval
- [ ] HTTP server binds `127.0.0.1` only
- [ ] No secrets logged or exposed in error messages
- [ ] No `eval()` or `exec()` on untrusted input (except `shell_evaluate` which is by design)
- [ ] SQL queries use parameterized queries (aiosqlite)
- [ ] No `os.system()` or `subprocess.call(shell=True)` added
- [ ] File paths validated (no path traversal)
- [ ] `config.json` still gets `0o600` after save

### Architecture review (all phases)

- [ ] Skill contract followed (`TOOL_DEFS`, `TOOL_STATUS`, `TOOL_HANDLERS`)
- [ ] All LLM calls go through `web/llm/gateway.py`
- [ ] No circular imports introduced
- [ ] `shared.py` mutations are safe (no race conditions)
- [ ] Existing tests still pass (`uv run pytest -q`)
- [ ] No `Co-Authored-By` in commits
- [ ] No comments added unless asked

### Phase-specific review

See the review checklist at the end of each phase section above.

### Integration review (after all phases)

- [ ] OneNote demo reproducible via agent prompt (no manual intervention)
- [ ] 2-step workflow executable via API with SSE streaming
- [ ] Workflow editor creates/edits/runs workflows
- [ ] Headless mode works with tray icon
- [ ] Payment guard blocks destructive clicks
- [ ] Confirm gate pauses workflow and resumes on approval

---

**End of document.**
