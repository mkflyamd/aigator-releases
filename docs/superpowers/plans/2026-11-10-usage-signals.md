# Usage Signals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reliability, cost, adoption and depth signals to the daily usage row that `web/usage_report.py` writes to the Gator Usage SharePoint list.

**Architecture:** A new `_signals_by_day(since_day)` reads existing tables in `tasks.db` read-only and returns ten numeric fields plus a `Details` JSON string per UTC day. `report_pending` merges them into the row fields next to `Messages` and `ToolRuns`. Active-day rules, the `email|date` key, the state file and `_send()` do not change.

**Tech Stack:** Python 3, sqlite3 (read-only), pytest with pytest-asyncio (async tests are plain `async def`).

## Global Constraints

- Counts only. Never message text, file names, tool arguments, or `usage_log.prompt_preview`.
- `Details` names only built-in tools and built-in skills. User-added MCP servers are counted under `mcp`, user-made skills under `custom`, never by name.
- A missing table or column gives zeros, as `tool_call_log` does for `ToolRuns` today.
- These signals do not change which days are active (a day is active only with at least one chat message or tool run).
- Fake credentials in tests: `aigator-fake-api-key` only. Existing tests use `aigator-fake-site` and `aigator-fake-list`.
- Commit messages carry no `Co-Authored-By` line. Commit only when the user says to.
- Run tests from the repo root: `python -m pytest tests/test_usage_report.py tests/test_identity.py -q`.
- SharePoint columns already exist (created 2026-11-10): `InputTokens`, `OutputTokens`, `Conversations`, `BackgroundTasks`, `ToolErrors`, `McpToolRuns`, `LlmErrors`, `Failovers`, `Drafts`, `AvgTurnMs` (Number, no decimals) and `Details` (multi-line plain text).

## File Structure

- Modify `web/usage_report.py`: add the signal queries and merge them into the row.
- Modify `tests/test_usage_report.py`: extend the `env` fixture schema, add signal tests, update the payload-columns test.
- Modify `docs/superpowers/specs/2026-11-09-usage-report-design.md`: two wording corrections.
- Modify `web/static/index.html`: already edited (About wording), only needs committing.

---

### Task 1: Spec corrections and the About wording commit

**Files:**
- Modify: `docs/superpowers/specs/2026-11-09-usage-report-design.md`
- Commit also: `web/static/index.html` (already edited)

- [ ] **Step 1: Correct the `ToolErrors` definition**

In the spec's table, replace
`| \`ToolErrors\` | \`tool_call_log\` rows whose \`outcome\` is not success |`
with
`| \`ToolErrors\` | \`tool_call_log\` rows whose \`outcome\` is \`error\` (cancelled and rejected are user actions, not errors) |`

- [ ] **Step 2: Correct the `skills` wording**

In the `Details` row of the same table, replace `` `skills` (runs per built-in skill) `` with `` `skills` (turns with each built-in skill active, from `turn_log.active_skills`) ``.

- [ ] **Step 3: Commit the About wording and the spec**

```bash
git add web/static/index.html
git commit -m "feat: About note says usage and issues may be collected"
git add docs/superpowers/specs/2026-11-09-usage-report-design.md docs/superpowers/plans/2026-11-10-usage-signals.md
git commit -m "docs: usage report adds reliability, cost, adoption and depth signals"
```

Run `git status` afterwards. Expected: clean.

---

### Task 2: Numeric signals

**Files:**
- Modify: `tests/test_usage_report.py` (fixture at lines 50-63, payload test at lines 227-233, new tests appended)
- Modify: `web/usage_report.py` (imports, new constants and functions, `report_pending` lines 128-147)

**Interfaces:**
- Produces: `usage_report._signals_by_day(since_day: str) -> dict[str, dict]` where each value has the ten numeric keys plus `"Details"` (a JSON string; blank `{"errors":{},"models":{},"skills":{},"tools":{}}` until Task 3).
- Produces: `usage_report._blank_signals() -> dict` (same shape, all zeros).
- Produces: `usage_report._builtin_skills() -> set[str]` (used by Task 3 and monkeypatched in tests).

- [ ] **Step 1: Extend the test fixture schema**

In `tests/test_usage_report.py`, replace the five lines that create the two tables in the `env` fixture with the full schema, and pin the built-in skill set:

```python
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE usage_log (id INTEGER PRIMARY KEY, source TEXT, "
        "input_tokens INTEGER, output_tokens INTEGER, created_at TEXT)"
    )
    con.execute(
        "CREATE TABLE tool_call_log (id INTEGER PRIMARY KEY, created_at TEXT, tool_name TEXT, "
        "is_mcp INTEGER DEFAULT 0, outcome TEXT DEFAULT 'success', error_code TEXT)"
    )
    con.execute(
        "CREATE TABLE turn_log (id INTEGER PRIMARY KEY, context_id TEXT, provider TEXT, model TEXT, "
        "llm_error TEXT, failover_used INTEGER DEFAULT 0, duration_ms INTEGER, active_skills TEXT, created_at TEXT)"
    )
    con.execute("CREATE TABLE tasks (task_id INTEGER PRIMARY KEY, created_at TEXT)")
    con.execute("CREATE TABLE task_drafts (draft_id INTEGER PRIMARY KEY, created_at TEXT)")
    con.commit()
    con.close()
```

and after the `_app_version` monkeypatch add:

```python
    monkeypatch.setattr(usage_report, "_builtin_skills", lambda: {"teams", "email"})
```

Add this helper under `_add`:

```python
def _sql(db, sql, rows):
    con = sqlite3.connect(db)
    con.executemany(sql, rows)
    con.commit()
    con.close()
```

- [ ] **Step 2: Update the payload-columns test and add the numeric-signal tests**

Replace `test_payload_has_only_the_expected_columns` with:

```python
async def test_payload_has_only_the_expected_columns(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-08", 1)
    await usage_report.report_pending(CFG, today=TODAY)
    assert set(graph.posts[0][1]["fields"]) == {
        "Title", "Email", "ReportDate", "OS", "AppVersion", "InstallId", "Messages", "ToolRuns",
        "InputTokens", "OutputTokens", "Conversations", "BackgroundTasks", "ToolErrors",
        "McpToolRuns", "LlmErrors", "Failovers", "Drafts", "AvgTurnMs", "Details",
    }
```

Append:

```python
D8 = "2026-11-08T10:00:00.000000+00:00"


async def test_token_sums_include_every_source(env):
    db, graph = env
    _sql(db, "INSERT INTO usage_log (source, input_tokens, output_tokens, created_at) VALUES (?, ?, ?, ?)", [
        ("chat", 100, 10, D8),
        ("background", 50, 5, D8),
        ("chat", 7, 1, "2026-11-09T10:00:00.000000+00:00"),
    ])
    await usage_report.report_pending(CFG, today=TODAY)
    f = graph.posts[0][1]["fields"]
    assert (f["InputTokens"], f["OutputTokens"]) == (150, 15)


async def test_turn_signals(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-08", 1)
    _sql(db, "INSERT INTO turn_log (context_id, provider, model, llm_error, failover_used, duration_ms, "
             "active_skills, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
        ("c1", "P", "m1", None, 0, 100, "[]", D8),
        ("c1", "P", "m1", "boom", 1, 200, "[]", D8),
        ("c2", "P", "m2", "", 0, 300, "[]", D8),
    ])
    await usage_report.report_pending(CFG, today=TODAY)
    f = graph.posts[0][1]["fields"]
    assert f["Conversations"] == 2
    assert f["LlmErrors"] == 1
    assert f["Failovers"] == 1
    assert f["AvgTurnMs"] == 200


async def test_background_tasks_and_drafts_count_for_their_day(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-08", 1)
    _sql(db, "INSERT INTO tasks (task_id, created_at) VALUES (?, ?)", [
        (1, D8), (2, D8), (3, "2026-11-07T10:00:00.000000+00:00"),
    ])
    _sql(db, "INSERT INTO task_drafts (draft_id, created_at) VALUES (?, ?)", [(1, D8)])
    await usage_report.report_pending(CFG, today=TODAY)
    f = graph.posts[0][1]["fields"]
    assert (f["BackgroundTasks"], f["Drafts"]) == (2, 1)


async def test_tool_errors_count_only_error_outcome_and_mcp_runs_are_counted(env):
    db, graph = env
    _sql(db, "INSERT INTO tool_call_log (created_at, tool_name, is_mcp, outcome, error_code) VALUES (?, ?, ?, ?, ?)", [
        (D8, "read_file", 0, "success", None),
        (D8, "read_file", 0, "error", "tool_error"),
        (D8, "run_python", 0, "cancelled", None),
        (D8, "srv_tool", 1, "success", None),
        (D8, "srv_tool", 1, "error", "mcp_error"),
    ])
    await usage_report.report_pending(CFG, today=TODAY)
    f = graph.posts[0][1]["fields"]
    assert (f["ToolRuns"], f["ToolErrors"], f["McpToolRuns"]) == (5, 2, 2)


async def test_signal_only_day_is_not_active(env):
    db, graph = env
    _sql(db, "INSERT INTO turn_log (context_id, provider, model, created_at) VALUES (?, ?, ?, ?)", [("c1", "P", "m1", D8)])
    _sql(db, "INSERT INTO tasks (task_id, created_at) VALUES (?, ?)", [(1, D8)])
    _sql(db, "INSERT INTO task_drafts (draft_id, created_at) VALUES (?, ?)", [(1, D8)])
    assert await usage_report.report_pending(CFG, today=TODAY) == 0
    assert graph.posts == []


async def test_missing_signal_tables_give_zeros(env):
    db, graph = env
    con = sqlite3.connect(db)
    for table in ("turn_log", "tasks", "task_drafts"):
        con.execute(f"DROP TABLE {table}")
    con.commit()
    con.close()
    _add(db, "usage_log", "2026-11-08", 2)
    assert await usage_report.report_pending(CFG, today=TODAY) == 1
    f = graph.posts[0][1]["fields"]
    assert f["Messages"] == 2
    for name in ("Conversations", "BackgroundTasks", "LlmErrors", "Failovers", "Drafts", "AvgTurnMs"):
        assert f[name] == 0


async def test_legacy_tool_table_without_new_columns_gives_zeros(env):
    db, graph = env
    con = sqlite3.connect(db)
    con.execute("DROP TABLE tool_call_log")
    con.execute("CREATE TABLE tool_call_log (id INTEGER PRIMARY KEY, created_at TEXT, tool_name TEXT)")
    con.commit()
    con.close()
    _add(db, "tool_call_log", "2026-11-08", 3)
    assert await usage_report.report_pending(CFG, today=TODAY) == 1
    f = graph.posts[0][1]["fields"]
    assert (f["ToolRuns"], f["ToolErrors"], f["McpToolRuns"]) == (3, 0, 0)
```

- [ ] **Step 3: Run the tests and see the new ones fail**

Run: `python -m pytest tests/test_usage_report.py -q`
Expected: the old tests still pass; the new tests and the payload test fail with `KeyError` on the new field names.

- [ ] **Step 4: Implement the numeric signals**

In `web/usage_report.py`, add `from pathlib import Path` to the imports (after `import uuid`). Add after `_SENT_KEYS_KEPT = 60`:

```python
_SIGNAL_FIELDS = (
    "InputTokens", "OutputTokens", "Conversations", "BackgroundTasks", "ToolErrors",
    "McpToolRuns", "LlmErrors", "Failovers", "Drafts", "AvgTurnMs",
)
_SCALAR_SIGNALS = (
    ("InputTokens", "COALESCE(SUM(input_tokens), 0)", "usage_log", ""),
    ("OutputTokens", "COALESCE(SUM(output_tokens), 0)", "usage_log", ""),
    ("Conversations", "COUNT(DISTINCT context_id)", "turn_log", ""),
    ("BackgroundTasks", "COUNT(*)", "tasks", ""),
    ("ToolErrors", "COUNT(*)", "tool_call_log", "AND outcome = 'error'"),
    ("McpToolRuns", "COUNT(*)", "tool_call_log", "AND is_mcp = 1"),
    ("LlmErrors", "COUNT(*)", "turn_log", "AND llm_error IS NOT NULL AND llm_error != ''"),
    ("Failovers", "COUNT(*)", "turn_log", "AND failover_used != 0"),
    ("Drafts", "COUNT(*)", "task_drafts", ""),
    ("AvgTurnMs", "CAST(ROUND(AVG(duration_ms)) AS INTEGER)", "turn_log", "AND duration_ms IS NOT NULL"),
)
```

Add after `_counts_by_day` (before `_share_id`):

```python
def _query(con: sqlite3.Connection, sql: str, params: tuple) -> list:
    try:
        return con.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []


def _builtin_skills() -> set[str]:
    root = Path(__file__).parent / "skills"
    return {p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")}


def _blank_details() -> dict:
    return {"models": {}, "skills": {}, "tools": {}, "errors": {}}


def _details_json(details: dict) -> str:
    return json.dumps(details, separators=(",", ":"), sort_keys=True)


def _blank_signals() -> dict:
    return {**{name: 0 for name in _SIGNAL_FIELDS}, "Details": _details_json(_blank_details())}


def _signals_by_day(since_day: str) -> dict[str, dict]:
    """Return {day: signal fields} for UTC days on or after *since_day*. Missing tables or columns give zeros."""
    scalars: dict[str, dict] = {}
    con = sqlite3.connect(f"file:{TASKS_DB}?mode=ro", uri=True)
    try:
        for field, expr, table, cond in _SCALAR_SIGNALS:
            sql = f"SELECT substr(created_at, 1, 10), {expr} FROM {table} WHERE created_at >= ? {cond} GROUP BY 1"
            for day, value in _query(con, sql, (since_day,)):
                scalars.setdefault(day, _blank_signals())[field] = value or 0
    finally:
        con.close()
    return scalars
```

In `report_pending`, replace the `days = ...` line and the `fields` dict construction:

```python
        since = (today - timedelta(days=MAX_AGE_DAYS)).isoformat()
        days = await asyncio.to_thread(_counts_by_day, since)
        signals = await asyncio.to_thread(_signals_by_day, since)
```

and after the `fields = {...}` dict add:

```python
            fields.update(signals.get(day) or _blank_signals())
```

- [ ] **Step 5: Run the tests and see them pass**

Run: `python -m pytest tests/test_usage_report.py tests/test_identity.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add web/usage_report.py tests/test_usage_report.py
git commit -m "feat: daily usage row adds token, conversation, task, draft, error, failover and turn-time counts"
```

---

### Task 3: Details breakdowns

**Files:**
- Modify: `tests/test_usage_report.py` (append tests)
- Modify: `web/usage_report.py` (`_signals_by_day`, one constant, `import re`)

**Interfaces:**
- Consumes: `_signals_by_day`, `_blank_details`, `_details_json`, `_builtin_skills`, `_blank_signals`, `_query` from Task 2.
- Produces: `Details` JSON string with keys `models`, `skills`, `tools`, `errors`, each a `{name: count}` object.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_usage_report.py`:

```python
def _details(graph):
    return json.loads(graph.posts[0][1]["fields"]["Details"])


async def test_details_break_down_models_and_skills(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-08", 1)
    _sql(db, "INSERT INTO turn_log (context_id, provider, model, active_skills, created_at) VALUES (?, ?, ?, ?, ?)", [
        ("c1", "P", "m1", json.dumps(["teams", "email"]), D8),
        ("c1", "P", "m1", json.dumps(["teams", "my-private-skill"]), D8),
        ("c2", "P", "m2", "[]", D8),
        ("c3", "", "", "[]", D8),
    ])
    await usage_report.report_pending(CFG, today=TODAY)
    d = _details(graph)
    assert d["models"] == {"P/m1": 2, "P/m2": 1}
    assert d["skills"] == {"teams": 2, "email": 1, "custom": 1}


async def test_details_break_down_tools_and_errors(env):
    db, graph = env
    _sql(db, "INSERT INTO tool_call_log (created_at, tool_name, is_mcp, outcome, error_code) VALUES (?, ?, ?, ?, ?)", [
        (D8, "read_file", 0, "success", None),
        (D8, "read_file", 0, "error", "tool_error"),
        (D8, "run_python", 0, "cancelled", None),
        (D8, "srv_tool", 1, "success", None),
        (D8, "srv_tool", 1, "error", "mcp_error"),
        (D8, "<tool>", 0, "error", "<tool>"),
    ])
    await usage_report.report_pending(CFG, today=TODAY)
    d = _details(graph)
    assert d["tools"] == {"read_file": 2, "run_python": 1, "mcp": 2}
    assert d["errors"] == {"tool_error": 1, "mcp_error": 1}


async def test_details_never_name_user_added_skills_or_mcp_tools(env):
    db, graph = env
    _sql(db, "INSERT INTO tool_call_log (created_at, tool_name, is_mcp) VALUES (?, ?, ?)", [(D8, "private_srv_tool", 1)])
    _sql(db, "INSERT INTO turn_log (context_id, provider, model, active_skills, created_at) VALUES (?, ?, ?, ?, ?)", [
        ("c1", "P", "m1", json.dumps(["my-private-skill"]), D8),
    ])
    await usage_report.report_pending(CFG, today=TODAY)
    text = graph.posts[0][1]["fields"]["Details"]
    assert "private" not in text


async def test_details_list_only_the_top_ten_tools(env):
    db, graph = env
    rows = [(D8, f"t{i:02d}", 0) for i in range(12) for _ in range(12 - i)]
    _sql(db, "INSERT INTO tool_call_log (created_at, tool_name, is_mcp) VALUES (?, ?, ?)", rows)
    await usage_report.report_pending(CFG, today=TODAY)
    tools = _details(graph)["tools"]
    assert len(tools) == 10
    assert "t00" in tools and "t10" not in tools and "t11" not in tools


async def test_details_are_empty_objects_when_there_is_nothing_to_break_down(env):
    db, graph = env
    _add(db, "usage_log", "2026-11-08", 1)
    await usage_report.report_pending(CFG, today=TODAY)
    assert graph.posts[0][1]["fields"]["Details"] == '{"errors":{},"models":{},"skills":{},"tools":{}}'
```

- [ ] **Step 2: Run them and see them fail**

Run: `python -m pytest tests/test_usage_report.py -q -k details`
Expected: the four breakdown tests fail (empty dicts returned); the empty-objects test passes.

- [ ] **Step 3: Implement the breakdowns**

In `web/usage_report.py` add `import re` to the imports and, after `_SENT_KEYS_KEPT`, add:

```python
_MAX_TOP_TOOLS = 10
_PLAIN_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
```

Replace the whole `_signals_by_day` function with:

```python
def _signals_by_day(since_day: str) -> dict[str, dict]:
    """Return {day: signal fields} for UTC days on or after *since_day*. Missing tables or columns give zeros."""
    builtin = _builtin_skills()
    scalars: dict[str, dict] = {}
    details: dict[str, dict] = {}

    def detail(day: str) -> dict:
        return details.setdefault(day, _blank_details())

    con = sqlite3.connect(f"file:{TASKS_DB}?mode=ro", uri=True)
    try:
        for field, expr, table, cond in _SCALAR_SIGNALS:
            sql = f"SELECT substr(created_at, 1, 10), {expr} FROM {table} WHERE created_at >= ? {cond} GROUP BY 1"
            for day, value in _query(con, sql, (since_day,)):
                scalars.setdefault(day, _blank_signals())[field] = value or 0

        for day, provider, model, n in _query(
            con,
            "SELECT substr(created_at, 1, 10), provider, model, COUNT(*) FROM turn_log "
            "WHERE created_at >= ? GROUP BY 1, 2, 3",
            (since_day,),
        ):
            if provider or model:
                detail(day)["models"][f"{provider}/{model}"] = n

        for day, raw in _query(
            con,
            "SELECT substr(created_at, 1, 10), active_skills FROM turn_log "
            "WHERE created_at >= ? AND active_skills IS NOT NULL",
            (since_day,),
        ):
            try:
                names = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(names, list):
                continue
            skills = detail(day)["skills"]
            for name in names:
                key = name if isinstance(name, str) and name in builtin else "custom"
                skills[key] = skills.get(key, 0) + 1

        for day, name, n in _query(
            con,
            "SELECT substr(created_at, 1, 10), tool_name, COUNT(*) FROM tool_call_log "
            "WHERE created_at >= ? AND is_mcp = 0 GROUP BY 1, 2 ORDER BY 3 DESC",
            (since_day,),
        ):
            tools = detail(day)["tools"]
            if _PLAIN_NAME.match(name or "") and len(tools) < _MAX_TOP_TOOLS:
                tools[name] = n

        for day, code, n in _query(
            con,
            "SELECT substr(created_at, 1, 10), error_code, COUNT(*) FROM tool_call_log "
            "WHERE created_at >= ? AND outcome = 'error' AND error_code IS NOT NULL GROUP BY 1, 2",
            (since_day,),
        ):
            if _PLAIN_NAME.match(code):
                detail(day)["errors"][code] = n
    finally:
        con.close()

    for day, sig in scalars.items():
        if sig["McpToolRuns"]:
            detail(day)["tools"]["mcp"] = sig["McpToolRuns"]

    result: dict[str, dict] = {}
    for day in scalars.keys() | details.keys():
        sig = dict(scalars.get(day) or _blank_signals())
        sig["Details"] = _details_json(details.get(day) or _blank_details())
        result[day] = sig
    return result
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `python -m pytest tests/test_usage_report.py tests/test_identity.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add web/usage_report.py tests/test_usage_report.py
git commit -m "feat: daily usage row carries model, skill, tool and error breakdowns without user-added names"
```

---

### Task 4: Check against the real database and the list

**Files:** none changed.

- [ ] **Step 1: Run the whole signal query against the real `tasks.db`**

```bash
cd web && python -c "
import usage_report, json
r = usage_report._signals_by_day('2026-11-03')
for day in sorted(r):
    s = r[day]
    print(day, {k: s[k] for k in usage_report._SIGNAL_FIELDS})
    print('  ', s['Details'][:300])
"
```

Expected: one entry per recent day with plausible numbers (tokens in the thousands or millions, `Conversations` at least 1 on days with chat). Check that `Details` holds only known model names, built-in skill names, `mcp`, and error codes such as `tool_error`, and no user-added names.

- [ ] **Step 2: Full test run**

Run: `python -m pytest tests/test_usage_report.py tests/test_identity.py -q`
Expected: all pass.

- [ ] **Step 3: Hand off to the user**

The user clears the old rows in the Gator Usage list, then restarts Gator (the `sent` list in `~/.gator/usage_report.json` is already empty). After startup the seven days reappear with the new columns filled. Read the items back through Graph and compare `Messages`, `ToolRuns` and the new fields with Step 1's output.
