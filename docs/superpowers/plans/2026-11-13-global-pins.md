# Global Pins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user mark a pinned item as global from the pin orb popover so it shows in every tab, and demote it back to a normal pin on the current tab.

**Architecture:** Global pins live in one reserved bucket (`__global__`) in the existing `pinned_contexts.json`. `get_pins()` merges that bucket into every tab's list (tagged `scope: "global"`, deduped, global first), so every existing consumer picks it up. One new CSRF-protected route moves a pin between the tab bucket and the global bucket; the pin orb popover gets a per-card globe toggle and a "Global" / "This tab" grouping.

**Tech Stack:** Python / FastAPI (`web/skills/context/state.py`, `web/routes/onenote.py`), vanilla JS (`web/static/app.js`), CSS (`web/static/style.css`), pytest and `node --test`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-11-13-global-pins-design.md`. Branch: `feat/global-pins` (cut from `main`). Do not push.
- Un-globaling demotes to a normal pin on the **calling tab** (it never deletes the item). The x on a global pin deletes it from all tabs, after a confirm.
- Reserved bucket id is exactly `__global__`. It is distinct from `"default"`; do not reintroduce any `"default"`-bucket merge.
- New POST/PUT/PATCH/DELETE routes must use `dependencies=[Depends(verify_csrf)]` (from `security`). Do not add anything to `tests/csrf_route_baseline.txt`.
- Commit messages: do NOT add `Co-Authored-By` lines (project CLAUDE.md rule).
- The project is called **AI Gator** (never "POC"). Use `aigator-fake-api-key` as the only fake credential (none are needed here).
- No new top-level `const` in `web/static/app.js` (startup const-order rule). New code is function declarations and consts local to functions, which is safe.
- No caveat/limitation notes in docs; do the least that meets the spec.

**Editing note (CRLF):** `web/static/app.js`, `web/static/style.css`, `web/skills/context/state.py` and `web/routes/onenote.py` have CRLF line endings in the working tree (git normalizes on commit). If the Edit tool reports "string not found" for a multi-line `old_string`, apply the same replacement with:

```bash
python - <<'EOF'
import pathlib
p = pathlib.Path("PATH/TO/FILE")
s = p.read_text(encoding="utf-8", newline="")   # keeps CRLF and the BOM
old = """OLD TEXT""".replace("\n", "\r\n")
new = """NEW TEXT""".replace("\n", "\r\n")
assert s.count(old) == 1, s.count(old)
p.write_text(s.replace(old, new), encoding="utf-8", newline="")
EOF
```

After every edit session run `git diff --stat` and confirm only the intended lines changed (not a whole-file EOL rewrite).

Run Python tests from the repo root with `uv run pytest -q <path>`; JS tests with `node --test <path>`.

---

### Task 1: Global bucket in pin state

**Files:**
- Modify: `web/skills/context/state.py`
- Create: `tests/test_global_pins.py` (state tests here; route tests are added in Task 2)

**Interfaces:**
- Produces (used by Task 2):
  - `GLOBAL_CONTEXT_ID: str = "__global__"`
  - `get_pins(context_id: str = "default", include_global: bool = True) -> list[dict]` -- global entries first, each a copy with `"scope": "global"`; tab entries untagged; an item in both appears once (as global). `include_global=False` or `context_id == GLOBAL_CONTEXT_ID` returns only that bucket.
  - `set_pin_scope(source: str, item_id: str, scope: str, context_id: str = "default") -> dict` -- `scope` is `"global"` or `"tab"`; returns `{"moved": bool, "scope": scope, "source": source, "id": item_id}`.
  - `remove_pin(source: str, item_id: str, context_id: str = "default", scope: str = "tab") -> dict` -- `scope="global"` removes from the global bucket; returns `{"unpinned": bool, "source": ..., "id": ...}` as before.

- [ ] **Step 1: Write the failing state tests**

Create `tests/test_global_pins.py`:

```python
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest

from skills.context import state


@pytest.fixture(autouse=True)
def isolated_pins(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "pinned_contexts", {"default": {}})
    monkeypatch.setattr(state, "_PINS_FILE", tmp_path / "pinned_contexts.json")


def _pin(ctx="tabA", source="jira", item_id="KEY-1", label="Epic", **meta):
    state.set_pin(source, item_id, label, meta, ctx)


class TestGlobalState:
    def test_global_pin_shows_in_every_tab(self):
        _pin("tabA")
        assert state.set_pin_scope("jira", "KEY-1", "global", "tabA")["moved"] is True
        for tab in ("tabA", "tabB", "tabC"):
            pins = state.get_pins(tab)
            assert [p["id"] for p in pins] == ["KEY-1"]
            assert pins[0]["scope"] == "global"

    def test_global_pins_come_first_and_only_they_are_tagged(self):
        _pin("tabA", item_id="KEY-1")
        state.set_pin_scope("jira", "KEY-1", "global", "tabA")
        _pin("tabB", item_id="KEY-2", label="Local")
        pins = state.get_pins("tabB")
        assert [p["id"] for p in pins] == ["KEY-1", "KEY-2"]
        assert pins[0]["scope"] == "global"
        assert "scope" not in pins[1]

    def test_scope_tag_is_not_persisted(self):
        _pin("tabA")
        state.set_pin_scope("jira", "KEY-1", "global", "tabA")
        stored = state.pinned_contexts[state.GLOBAL_CONTEXT_ID]["jira::KEY-1"]
        assert "scope" not in stored
        assert "scope" not in state._PINS_FILE.read_text(encoding="utf-8")

    def test_item_in_tab_and_global_appears_once_as_global(self):
        _pin("tabA")
        state.set_pin_scope("jira", "KEY-1", "global", "tabA")
        _pin("tabB")
        pins = state.get_pins("tabB")
        assert len(pins) == 1
        assert pins[0]["scope"] == "global"

    def test_demote_lands_on_calling_tab_only(self):
        _pin("tabA")
        state.set_pin_scope("jira", "KEY-1", "global", "tabA")
        assert state.set_pin_scope("jira", "KEY-1", "tab", "tabB")["moved"] is True
        assert [p["id"] for p in state.get_pins("tabB")] == ["KEY-1"]
        assert "scope" not in state.get_pins("tabB")[0]
        assert state.get_pins("tabA") == []
        assert state.get_pins("tabC") == []

    def test_meta_survives_promote_and_demote(self):
        _pin("tabA", url="https://example.invalid/KEY-1")
        state.set_pin_scope("jira", "KEY-1", "global", "tabA")
        state.set_pin_scope("jira", "KEY-1", "tab", "tabB")
        pin = state.get_pins("tabB")[0]
        assert pin["meta"] == {"url": "https://example.invalid/KEY-1"}
        assert pin["label"] == "Epic"

    def test_unknown_pin_reports_not_moved(self):
        assert state.set_pin_scope("jira", "NOPE", "global", "tabA")["moved"] is False
        assert state.set_pin_scope("jira", "NOPE", "tab", "tabA")["moved"] is False

    def test_promote_is_idempotent(self):
        _pin("tabA")
        state.set_pin_scope("jira", "KEY-1", "global", "tabA")
        assert state.set_pin_scope("jira", "KEY-1", "global", "tabB")["moved"] is True
        assert list(state.pinned_contexts[state.GLOBAL_CONTEXT_ID]) == ["jira::KEY-1"]

    def test_include_global_false_returns_tab_pins_only(self):
        _pin("tabA", item_id="KEY-1")
        state.set_pin_scope("jira", "KEY-1", "global", "tabA")
        _pin("tabA", item_id="KEY-2", label="Local")
        assert [p["id"] for p in state.get_pins("tabA", include_global=False)] == ["KEY-2"]

    def test_remove_with_global_scope_deletes_everywhere(self):
        _pin("tabA")
        state.set_pin_scope("jira", "KEY-1", "global", "tabA")
        result = state.remove_pin("jira", "KEY-1", "tabB", scope="global")
        assert result["unpinned"] is True
        assert state.get_pins("tabA") == []
        assert state.get_pins("tabB") == []

    def test_remove_with_tab_scope_leaves_global_alone(self):
        _pin("tabA")
        state.set_pin_scope("jira", "KEY-1", "global", "tabA")
        result = state.remove_pin("jira", "KEY-1", "tabB")
        assert result["unpinned"] is False
        assert [p["id"] for p in state.get_pins("tabB")] == ["KEY-1"]

    def test_clearing_a_tab_leaves_global_pins(self):
        _pin("tabA")
        state.set_pin_scope("jira", "KEY-1", "global", "tabA")
        _pin("tabB", item_id="KEY-2", label="Local")
        state.clear_pins("tabB")
        assert [p["id"] for p in state.get_pins("tabB")] == ["KEY-1"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest -q tests/test_global_pins.py`
Expected: FAIL / errors -- `AttributeError: module 'skills.context.state' has no attribute 'GLOBAL_CONTEXT_ID'` (and `set_pin_scope`).

- [ ] **Step 3: Implement in `web/skills/context/state.py`**

3a. Add the constant right after the `_PINS_FILE = ...` line:

```python
_PINS_FILE = Path.home() / ".config" / "gator" / "pinned_contexts.json"

GLOBAL_CONTEXT_ID = "__global__"
```

3b. Replace `get_pins`:

old:
```python
def get_pins(context_id: str = "default") -> list[dict]:
    return list(pinned_contexts.get(context_id, {}).values())
```
new:
```python
def get_pins(context_id: str = "default", include_global: bool = True) -> list[dict]:
    tab_entries = pinned_contexts.get(context_id, {})
    global_entries = pinned_contexts.get(GLOBAL_CONTEXT_ID, {})
    if not include_global or context_id == GLOBAL_CONTEXT_ID or not global_entries:
        return list(tab_entries.values())
    tab_only = [e for k, e in tab_entries.items() if k not in global_entries]
    return [{**e, "scope": "global"} for e in global_entries.values()] + tab_only
```

3c. Replace `remove_pin` with `set_pin_scope` + the scoped `remove_pin`:

old:
```python
def remove_pin(source: str, item_id: str, context_id: str = "default") -> dict:
    key = f"{source}::{item_id}"
    removed = pinned_contexts.get(context_id, {}).pop(key, None)
    _save()
    return {"unpinned": bool(removed), "source": source, "id": item_id}
```
new:
```python
def set_pin_scope(
    source: str, item_id: str, scope: str, context_id: str = "default"
) -> dict:
    key = f"{source}::{item_id}"
    if scope == "global":
        src_id, dst_id = context_id, GLOBAL_CONTEXT_ID
    else:
        src_id, dst_id = GLOBAL_CONTEXT_ID, context_id
    entry = pinned_contexts.get(src_id, {}).pop(key, None)
    if entry is not None:
        pinned_contexts.setdefault(dst_id, {})[key] = entry
    moved = key in pinned_contexts.get(dst_id, {})
    if moved:
        _save()
    return {"moved": moved, "scope": scope, "source": source, "id": item_id}


def remove_pin(
    source: str, item_id: str, context_id: str = "default", scope: str = "tab"
) -> dict:
    key = f"{source}::{item_id}"
    bucket = GLOBAL_CONTEXT_ID if scope == "global" else context_id
    removed = pinned_contexts.get(bucket, {}).pop(key, None)
    _save()
    return {"unpinned": bool(removed), "source": source, "id": item_id}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q tests/test_global_pins.py`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add web/skills/context/state.py tests/test_global_pins.py
git commit -m "Add global pin bucket and scope moves to pin state"
```

---

### Task 2: Scope route, scoped unpin, clone excludes global

**Files:**
- Modify: `web/routes/onenote.py` (imports near line 8; models near `ContextPinRequest`; `/api/context/pin*` routes)
- Modify: `tests/test_global_pins.py` (append route tests)

**Interfaces:**
- Consumes (from Task 1): `set_pin_scope(source, item_id, scope, context_id)`, `remove_pin(source, item_id, context_id, scope)`, `get_pins(context_id, include_global)`.
- Produces (used by Task 3 frontend):
  - `POST /api/context/pin/scope` -- JSON body `{source, id, scope: "global"|"tab", context_id}`; CSRF required; returns `{"moved": bool, "scope": str, "source": str, "id": str}`; 422 on a bad `scope`.
  - `DELETE /api/context/pin/{source}/{item_id}?context_id=...&scope=global` -- `scope` is `"tab"` (default) or `"global"`; returns `{"unpinned": bool, ...}`.
  - `GET /api/context/pins?context_id=...` now includes global pins tagged `"scope": "global"` (no code change; it calls `get_pins`).
  - `POST /api/context/pins/clone` copies only the source tab's own pins.

- [ ] **Step 1: Write the failing route tests**

Append to `tests/test_global_pins.py` (add these imports at the top of the file with the others: `from fastapi.testclient import TestClient`, `from app import app`, `from security import get_csrf_token`):

```python
def _csrf():
    return {"X-CSRF-Token": get_csrf_token("testserver")}


def _client():
    return TestClient(app)


def _post_pin(client, ctx="tabA", item_id="KEY-1", label="Epic"):
    r = client.post(
        "/api/context/pin",
        json={"source": "jira", "id": item_id, "label": label, "meta": {}, "context_id": ctx},
    )
    assert r.status_code == 200, r.text


class TestGlobalRoutes:
    def test_scope_route_requires_csrf(self):
        client = _client()
        _post_pin(client)
        r = client.post(
            "/api/context/pin/scope",
            json={"source": "jira", "id": "KEY-1", "scope": "global", "context_id": "tabA"},
        )
        assert r.status_code == 403

    def test_scope_round_trip(self):
        client = _client()
        _post_pin(client)
        r = client.post(
            "/api/context/pin/scope",
            headers=_csrf(),
            json={"source": "jira", "id": "KEY-1", "scope": "global", "context_id": "tabA"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["moved"] is True
        seen_from_b = client.get("/api/context/pins", params={"context_id": "tabB"}).json()
        assert [p["id"] for p in seen_from_b] == ["KEY-1"]
        assert seen_from_b[0]["scope"] == "global"

        r = client.post(
            "/api/context/pin/scope",
            headers=_csrf(),
            json={"source": "jira", "id": "KEY-1", "scope": "tab", "context_id": "tabB"},
        )
        assert r.json()["moved"] is True
        b = client.get("/api/context/pins", params={"context_id": "tabB"}).json()
        assert [p["id"] for p in b] == ["KEY-1"]
        assert "scope" not in b[0]
        assert client.get("/api/context/pins", params={"context_id": "tabA"}).json() == []

    def test_scope_route_rejects_unknown_scope(self):
        r = _client().post(
            "/api/context/pin/scope",
            headers=_csrf(),
            json={"source": "jira", "id": "KEY-1", "scope": "everywhere", "context_id": "tabA"},
        )
        assert r.status_code == 422

    def test_unpin_with_global_scope_removes_from_all_tabs(self):
        client = _client()
        _post_pin(client)
        client.post(
            "/api/context/pin/scope",
            headers=_csrf(),
            json={"source": "jira", "id": "KEY-1", "scope": "global", "context_id": "tabA"},
        )
        r = client.delete(
            "/api/context/pin/jira/KEY-1",
            headers=_csrf(),
            params={"context_id": "tabB", "scope": "global"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["unpinned"] is True
        for tab in ("tabA", "tabB"):
            assert client.get("/api/context/pins", params={"context_id": tab}).json() == []

    def test_clone_copies_only_the_tabs_own_pins(self):
        client = _client()
        _post_pin(client, item_id="KEY-1")
        client.post(
            "/api/context/pin/scope",
            headers=_csrf(),
            json={"source": "jira", "id": "KEY-1", "scope": "global", "context_id": "tabA"},
        )
        _post_pin(client, item_id="KEY-2", label="Local")
        r = client.post(
            "/api/context/pins/clone",
            json={"from_context_id": "tabA", "to_context_id": "tabC"},
        )
        assert r.json() == {"ok": True, "cloned": 1}
        assert [p["id"] for p in state.get_pins("tabC", include_global=False)] == ["KEY-2"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest -q tests/test_global_pins.py -k GlobalRoutes`
Expected: FAIL -- the scope route returns 404/405 and clone returns `cloned: 2`.

- [ ] **Step 3: Implement in `web/routes/onenote.py`**

3a. Add the `Literal` import after the `urllib.parse` import line:

```python
from urllib.parse import quote as _url_quote
from typing import Literal
```

3b. Add the request model immediately before `class OneNoteUpdatePageRequest(BaseModel):`:

```python
class ContextPinScopeRequest(BaseModel):
    source: str
    id: str
    scope: Literal["global", "tab"]
    context_id: str = "default"


```

3c. Add the route immediately before `@router.get("/api/context/pins")`:

```python
@router.post("/api/context/pin/scope", dependencies=[Depends(verify_csrf)])
async def context_pin_scope(req: ContextPinScopeRequest):
    from skills.context.state import set_pin_scope

    return set_pin_scope(req.source, req.id, req.scope, req.context_id)


```

3d. Scope the unpin route. Replace:

```python
async def context_unpin(source: str, item_id: str, context_id: str = "default"):
    from skills.context.state import remove_pin

    result = remove_pin(source, item_id, context_id)
```
with:
```python
async def context_unpin(
    source: str,
    item_id: str,
    context_id: str = "default",
    scope: Literal["tab", "global"] = "tab",
):
    from skills.context.state import remove_pin

    result = remove_pin(source, item_id, context_id, scope)
```

3e. In `context_clone_pins`, replace `    pins = get_pins(source_ctx)` with:

```python
    pins = get_pins(source_ctx, include_global=False)
```

(Verify each anchor is unique first: `grep -c "pins = get_pins(source_ctx)" web/routes/onenote.py` must print `1`.)

- [ ] **Step 4: Run the tests to verify they pass, plus the CSRF inventory**

Run: `uv run pytest -q tests/test_global_pins.py tests/test_csrf_route_inventory.py tests/test_csrf_binding.py web/tests/test_context_pin_onedrive_upgrade.py`
Expected: all pass (the inventory confirms the new route is protected and the baseline file is untouched).

- [ ] **Step 5: Commit**

```bash
git add web/routes/onenote.py tests/test_global_pins.py
git commit -m "Add pin scope route, scoped unpin, and keep global pins out of tab clones"
```

---

### Task 3: Pin orb popover -- globe toggle and Global / This tab groups

**Files:**
- Modify: `web/static/app.js` (`_showPinPopover`, currently starting near line 5414)
- Modify: `web/static/style.css` (pin card rules, near `.pin-card-remove:hover`)
- Modify: `docs/superpowers/specs/2026-11-13-global-pins-design.md` (one line, see Step 7)
- Create: `tests/global_pins_group.test.js`

**Interfaces:**
- Consumes (from Task 2): `POST /api/context/pin/scope` (body `{source, id, scope, context_id}`, returns `{moved}`), `DELETE /api/context/pin/{source}/{id}?context_id=..&scope=global`, and pins from `GET /api/context/pins` carrying `scope: "global"` for global ones. The page's fetch wrapper adds the CSRF header automatically for same-origin mutating calls.
- Produces: `_groupPinsByScope(pins) -> { globals: Pin[], locals: Pin[] }` (top-level function in `app.js`, order-preserving).

- [ ] **Step 1: Write the failing JS test**

Create `tests/global_pins_group.test.js`:

```js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');
const m = source.match(/function _groupPinsByScope\([^)]*\)\s*\{[\s\S]*?\n\}/);
assert(m, '_groupPinsByScope not found in app.js');
const { _groupPinsByScope } = vm.runInNewContext(`${m[0]}\n({ _groupPinsByScope });`, {});
const plain = (v) => JSON.parse(JSON.stringify(v));

// splits by scope and keeps order
const pins = [{ id: '1', scope: 'global' }, { id: '2' }, { id: '3', scope: 'global' }, { id: '4' }];
const grouped = plain(_groupPinsByScope(pins));
assert.deepStrictEqual(
  grouped.globals.map((p) => p.id),
  ['1', '3'],
);
assert.deepStrictEqual(
  grouped.locals.map((p) => p.id),
  ['2', '4'],
);

// no pins / bad input
assert.deepStrictEqual(plain(_groupPinsByScope([])), { globals: [], locals: [] });
assert.deepStrictEqual(plain(_groupPinsByScope(null)), { globals: [], locals: [] });
```

- [ ] **Step 2: Run it to verify it fails**

Run: `node --test tests/global_pins_group.test.js`
Expected: FAIL with `_groupPinsByScope not found in app.js`.

- [ ] **Step 3: Add the helper to `app.js`**

Insert directly above `async function _showPinPopover() {`:

```js
function _groupPinsByScope(pins) {
  const list = Array.isArray(pins) ? pins : [];
  return {
    globals: list.filter((p) => p.scope === 'global'),
    locals: list.filter((p) => p.scope !== 'global'),
  };
}

```

Run: `node --test tests/global_pins_group.test.js` -- Expected: PASS.

- [ ] **Step 4: Turn the card loop into `addCard` and add the globe button + handlers**

All edits are inside `_showPinPopover`. Before each single-line anchor edit, confirm uniqueness with Grep (expect exactly 1 match in `web/static/app.js`).

4a. Convert the loop. Replace the line (4-space indent):

```js
    pins.forEach((p) => {
```
with:
```js
    const addCard = (p) => {
```

4b. Add the globe button to the card template. After the line

```js
        <button class="pin-card-btn pin-card-ask" title="Insert into chat">✦</button>
```
add:
```js
        <button class="pin-card-btn pin-card-scope${p.scope === 'global' ? ' is-global' : ''}" title="${p.scope === 'global' ? 'Make tab-only' : 'Make global'}" aria-pressed="${p.scope === 'global'}">🌐</button>
```

4c. Add the scope toggle handler directly above the line `      // × Unpin`:

```js
      // Globe: global pins show in every tab; turning it off keeps the pin on this tab only
      card.querySelector('.pin-card-scope').addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        btn.disabled = true;
        const toGlobal = p.scope !== 'global';
        let moved = false;
        try {
          const res = await fetch('/api/context/pin/scope', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              source: p.source,
              id: p.id,
              scope: toGlobal ? 'global' : 'tab',
              context_id: contextId,
            }),
          });
          moved = res.ok && !!(await res.json().catch(() => ({}))).moved;
        } catch {
          moved = false;
        }
        if (!moved) {
          btn.disabled = false;
          return;
        }
        _cachedPins = _cachedPins.map((pin) => {
          if (!(pin.source === p.source && String(pin.id) === String(p.id))) return pin;
          const next = { ...pin };
          if (toGlobal) next.scope = 'global';
          else delete next.scope;
          return next;
        });
        renderPins();
      });
```

4d. Delete scope and confirm. Replace the URL line in the x handler:

```js
          `/api/context/pin/${p.source}/${encodeURIComponent(p.id)}?context_id=${contextId}`,
```
with:
```js
          `/api/context/pin/${p.source}/${encodeURIComponent(p.id)}?context_id=${contextId}${p.scope === 'global' ? '&scope=global' : ''}`,
```

Then, directly after the line `        const removeBtn = card.querySelector('.pin-card-remove');` insert:

```js
        const confirmed = removeBtn.dataset.confirmed === '1';
        delete removeBtn.dataset.confirmed;
        if (p.scope === 'global' && !confirmed) {
          _showConfirmModal(
            'Remove global pin',
            `Remove "${escapeHtml(p.label)}" from all tabs?`,
            'Remove',
            () => {
              removeBtn.dataset.confirmed = '1';
              removeBtn.click();
            },
          );
          return;
        }
```

4e. Replace the post-removal DOM update. Old (inside the x handler, after the card fade styles):

```js
        setTimeout(() => {
          card.remove();
          // Update badge locally from the already-correct _cachedPins — no network fetch needed
          const orb = document.getElementById('pin-orb');
          const badge = document.getElementById('pin-orb-badge');
          const count = Array.isArray(_cachedPins) ? _cachedPins.length : 0;
          if (badge) {
            badge.textContent = count;
            badge.classList.toggle('hidden', count === 0);
          }
          if (orb) {
            orb.classList.toggle('has-pins', count > 0);
          }
          if (countEl)
            countEl.textContent = list.children.length
              ? `${list.children.length} item${list.children.length !== 1 ? 's' : ''}`
              : '';
          if (!list.children.length) {
            const empty = document.createElement('div');
            empty.className = 'pin-popover-empty';
            const icon = document.createElement('div');
            icon.style.cssText = 'font-size:1.4rem;margin-bottom:.4rem';
            icon.textContent = '🐊';
            empty.appendChild(icon);
            empty.appendChild(document.createTextNode('All clear! No items pinned.'));
            list.replaceChildren(empty);
          }
        }, 200);
```
New:
```js
        setTimeout(() => {
          syncBadge();
          renderPins();
        }, 200);
```

4f. Close out the loop and define `syncBadge` / `renderPins`. Replace:

```js
      list.appendChild(card);
    });
  } catch {
```
with:
```js
      list.appendChild(card);
    };

    // Badge from the already-correct _cachedPins -- no network fetch needed
    const syncBadge = () => {
      const orb = document.getElementById('pin-orb');
      const badge = document.getElementById('pin-orb-badge');
      const count = Array.isArray(_cachedPins) ? _cachedPins.length : 0;
      if (badge) {
        badge.textContent = count;
        badge.classList.toggle('hidden', count === 0);
      }
      if (orb) orb.classList.toggle('has-pins', count > 0);
    };

    // Rebuilds the list from the cache. The initial empty state returns earlier, so an
    // empty list here means the user just removed the last pin.
    const renderPins = () => {
      const current =
        _cachedPinsContextId === contextId && Array.isArray(_cachedPins) ? _cachedPins : [];
      list.replaceChildren();
      if (countEl)
        countEl.textContent = current.length
          ? `${current.length} item${current.length !== 1 ? 's' : ''}`
          : '';
      if (!current.length) {
        const empty = document.createElement('div');
        empty.className = 'pin-popover-empty';
        const icon = document.createElement('div');
        icon.style.cssText = 'font-size:1.4rem;margin-bottom:.4rem';
        icon.textContent = '🐊';
        empty.appendChild(icon);
        empty.appendChild(document.createTextNode('All clear! No items pinned.'));
        list.replaceChildren(empty);
        return;
      }
      const { globals, locals } = _groupPinsByScope(current);
      const addGroup = (title, items) => {
        if (globals.length && items.length) {
          const header = document.createElement('div');
          header.className = 'pin-group-title';
          header.textContent = title;
          list.appendChild(header);
        }
        items.forEach(addCard);
      };
      addGroup('Global', globals);
      addGroup('This tab', locals);
    };

    renderPins();
  } catch {
```

- [ ] **Step 5: Add the CSS**

In `web/static/style.css`, insert directly above the line `.pin-popover-empty {`:

```css
.pin-card-scope:hover {
  color: var(--accent);
  background: rgba(96, 165, 250, 0.12);
}
.pin-card-scope.is-global {
  color: var(--accent);
  background: rgba(74, 222, 128, 0.15);
}
.pin-group-title {
  font-size: 0.62rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-dim);
  padding: 0.35rem 0.6rem 0.2rem;
}
```

- [ ] **Step 6: Run the JS tests and syntax check**

Run: `node --test tests/global_pins_group.test.js tests/startup_const_order.test.js` -- Expected: PASS (the startup const-order test guards against top-level const mistakes).
Run: `node --check web/static/app.js` -- Expected: no output.
Run: `git diff --stat` -- Expected: `app.js` shows tens of changed lines, not the whole file.

- [ ] **Step 7: Amend the spec line to match the implementation**

In `docs/superpowers/specs/2026-11-13-global-pins-design.md`, replace

```
- List rendering moves into a function so the popover re-renders after a toggle without closing. After each toggle, call `_refreshPinOrb(true)`.
```
with
```
- List rendering moves into a function so the popover re-renders after a toggle without closing. A toggle updates the cached pin list locally (the badge count is unchanged), so no refetch or flicker.
```

- [ ] **Step 8: Commit**

```bash
git add web/static/app.js web/static/style.css tests/global_pins_group.test.js docs/superpowers/specs/2026-11-13-global-pins-design.md
git commit -m "Add global toggle and Global/This tab grouping to the pin orb popover"
```

---

### Task 4: Verify in the running app

**Files:** none (verification only; fix anything found in the files above and re-run the affected tests).

- [ ] **Step 1: Run the full relevant test set**

Run: `uv run pytest -q tests/test_global_pins.py tests/test_csrf_route_inventory.py tests/test_csrf_binding.py web/tests/test_context_pin_onedrive_upgrade.py`
Run: `node --test tests/global_pins_group.test.js tests/startup_const_order.test.js tests/skill_pin.test.js`
Expected: all pass.

- [ ] **Step 2: Start the app and exercise the feature**

Use the `run` skill to launch AI Gator (the backend serves the UI; a browser via Playwright is fine). Seed two pins on the active tab by reading the tab id (`_activeTabId` in the page console) and calling `POST /api/context/pin` with `{"source":"jira","id":"KEY-1","label":"Epic One","meta":{},"context_id":"<tabId>"}` and `KEY-2` / "Epic Two". Then check each of these:

1. Open the pin orb popover: two cards, no group headers.
2. Click the globe on "Epic One": a "Global" header appears with Epic One above a "This tab" header with Epic Two; the globe is filled; the count stays 2.
3. Open a second tab, then its pin orb: Epic One shows under Global; Epic Two is absent; the badge reads 1.
4. In the second tab click the globe on Epic One: it moves to "This tab" with no headers; switch to the first tab: Epic One is gone, Epic Two remains.
5. Make Epic Two global, then click its x: a "Remove global pin" confirm appears; Cancel keeps it; Remove deletes it and it is gone from every tab. Removing the last card shows "All clear! No items pinned."
6. Seed saved history (`tab-hist-<activeTabId>` in localStorage with a message), reload, and confirm no page errors in the console and the dock, settings button and window drag still work.

Expected: every check behaves as described; no console errors.

- [ ] **Step 3: Report**

Summarize the results. If a check failed, fix it, re-run the affected tests, and commit the fix as its own commit (for example "Fix <what> in global pin popover").
