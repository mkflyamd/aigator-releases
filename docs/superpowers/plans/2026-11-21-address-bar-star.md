# Address Bar Star (Favorite = Custom App) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stale app pill and "Save as app" button in the toolbar with a browser-style star: star the current page to make it a custom app, unstar to remove it (with an 8 second Undo).

**Architecture:** The shell (`shell/main.js`) computes the star state for the active pane from the page URL and the saved custom apps, and pushes it to the toolbar in `toolbar:state`. The toolbar renders the star and a small bubble (rename / Remove). Star actions go toolbar -> main -> Gator renderer, which owns the config REST calls, the dock, and the Undo toast. Custom/generic panes get the same toolbar listeners the built-in panes already have, which also fixes the stale pill.

**Tech Stack:** Electron (`WebContentsView`, IPC), plain JS toolbar page, `node --test` for shell logic, FastAPI + pytest for the rename route.

## Global Constraints

- The product is called "AI Gator", never a POC.
- Commits carry no `Co-Authored-By` line.
- Any new POST/PUT/PATCH/DELETE route uses `dependencies=[Depends(verify_csrf)]` from `web/security.py`; `tests/csrf_route_baseline.txt` is never edited.
- Only fake credential in tests/docs: `aigator-fake-api-key`.
- Unstar = Remove: deletes the app's config entry, its pane, and its `persist:custom-<id>` session, after an 8 s Undo window. No "hide but keep" state.
- Star is hidden for built-in apps (Teams, Outlook, Slack, Jira, GitHub, Google g-* panes); shown only for user-added custom apps' panes.
- Bubble: name field, Remove (left, destructive style, never autofocused), Done (right, primary). Enter = Done, Esc = close with no change, click outside = Done. Consequence line: "Removing deletes this app's pins, settings and saved sign-in."
- Toasts: "Added to Gator apps" with Edit and Undo; "Removed <name> from Gator apps" with Undo. `role="status"`, 8 s, pause on hover/focus, Undo keyboard-reachable.
- Design truth is `web/static/style.css` and `docs/styleguide.md`; toolbar uses its own CSS variables in `shell/toolbar.html`.
- Shell edits: `shell/main.js` has mojibake; use ASCII anchors. Check `git ls-files --eol` after editing (keep LF).

## File Structure

- Create `shell/toolbar-star.js`: pure helpers (URL matching, star state, default name). Tested.
- Create `tests/toolbar-star.test.js`: node tests for the helpers.
- Modify `shell/main.js`: attach toolbar listeners to generic panes; push `star`; expandable toolbar height; star IPC; teardown IPC.
- Modify `shell/toolbar-preload.js`: no change needed (generic `send/on`).
- Modify `shell/preload.js`: expose `onCustomAppStar`, `customAppSetHidden`, `customAppTeardown`.
- Modify `shell/toolbar.html`: remove pill and CTA, add star + bubble.
- Modify `web/routes/mcp_routes.py`: `PATCH /api/config/custom-apps/{app_id}` (rename).
- Create `tests/test_custom_app_rename.py`.
- Create `web/static/custom-app-star.js`: renderer side (add, rename, remove-with-undo, undo toast). Loaded from `web/static/index.html` next to `web-pins.js`.
- Modify `web/static/style.css`: undo toast styles.

---

### Task 1: Star helpers (pure logic)

**Files:**
- Create: `shell/toolbar-star.js`
- Test: `tests/toolbar-star.test.js`

**Interfaces:**
- Produces:
  - `originKey(url: string): string | ''` - `origin` of an http(s) URL, lower-cased; `''` otherwise.
  - `findStarredApp(url, apps: {id, url}[], hiddenIds: Set<string>): string | null` - id of the app whose origin equals the URL's origin and not hidden.
  - `starState(url, apps, hiddenIds): { state: 'empty' | 'filled', appId: string | null }`
  - `defaultAppName(title: string, url: string): string` - trimmed title, else hostname without `www.`, capped at 40 chars.

- [ ] **Step 1: Write the failing tests**

```js
const test = require('node:test');
const assert = require('node:assert');
const star = require('../shell/toolbar-star');

const apps = [
  { id: 'custom-power-bi', url: 'https://app.powerbi.com/home' },
  { id: 'custom-cnn', url: 'https://www.cnn.com/' },
];

test('originKey lower-cases and rejects non-http', () => {
  assert.strictEqual(star.originKey('HTTPS://App.PowerBI.com/x?y=1'), 'https://app.powerbi.com');
  assert.strictEqual(star.originKey('about:blank'), '');
  assert.strictEqual(star.originKey('not a url'), '');
});

test('findStarredApp matches by origin, ignoring path', () => {
  assert.strictEqual(star.findStarredApp('https://app.powerbi.com/groups/1/reports/2', apps, new Set()), 'custom-power-bi');
  assert.strictEqual(star.findStarredApp('https://edition.cnn.com/', apps, new Set()), null);
});

test('findStarredApp skips apps pending deletion', () => {
  assert.strictEqual(star.findStarredApp('https://www.cnn.com/world', apps, new Set(['custom-cnn'])), null);
});

test('starState reports filled with the app id, else empty', () => {
  assert.deepStrictEqual(star.starState('https://www.cnn.com/a', apps, new Set()), { state: 'filled', appId: 'custom-cnn' });
  assert.deepStrictEqual(star.starState('https://example.com/', apps, new Set()), { state: 'empty', appId: null });
});

test('defaultAppName prefers the title, falls back to the host, caps length', () => {
  assert.strictEqual(star.defaultAppName('  Sales Dashboard ', 'https://x.com'), 'Sales Dashboard');
  assert.strictEqual(star.defaultAppName('', 'https://www.example.com/a'), 'example.com');
  assert.strictEqual(star.defaultAppName('a'.repeat(60), 'https://x.com').length, 40);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd shell && node --test ../tests/toolbar-star.test.js`
Expected: FAIL, cannot find module `../shell/toolbar-star`.

- [ ] **Step 3: Implement**

```js
'use strict';

function originKey(url) {
  try {
    const u = new URL(url);
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return '';
    return u.origin.toLowerCase();
  } catch {
    return '';
  }
}

function findStarredApp(url, apps, hiddenIds) {
  const key = originKey(url);
  if (!key) return null;
  for (const app of apps) {
    if (hiddenIds && hiddenIds.has(app.id)) continue;
    if (originKey(app.url) === key) return app.id;
  }
  return null;
}

function starState(url, apps, hiddenIds) {
  const appId = findStarredApp(url, apps, hiddenIds);
  return appId ? { state: 'filled', appId } : { state: 'empty', appId: null };
}

function defaultAppName(title, url) {
  const t = String(title || '').trim();
  let name = t;
  if (!name) {
    try {
      name = new URL(url).hostname.replace(/^www\./i, '');
    } catch {
      name = 'Web app';
    }
  }
  return name.slice(0, 40);
}

module.exports = { originKey, findStarredApp, starState, defaultAppName };
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd shell && node --test ../tests/toolbar-star.test.js`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add shell/toolbar-star.js tests/toolbar-star.test.js
git commit -m "feat(toolbar): add pure helpers that decide the address bar star state"
```

---

### Task 2: Shell wiring (listeners, star state, expandable toolbar, IPC)

**Files:**
- Modify: `shell/main.js` (`_toolbarAppForUrl` ~652, `_toolbarPushState` ~690, `createGenericPane` ~4410, `layout()` ~4272-4294, `toolbar:save-custom-app` ~5073, poller ~5089)
- Modify: `shell/preload.js` (after `createCustomApp`, line 92)

**Interfaces:**
- Consumes: `starState`, `defaultAppName` from `shell/toolbar-star.js`.
- Produces (main -> toolbar): `toolbar:state` gains `star: { state: 'hidden' | 'empty' | 'filled', appId: string | null, name: string }`; `app` and `isCustomApp`-pill use removed from the UI (field may stay).
- Produces (toolbar -> main): `toolbar:set-expanded(heightPx: number)` (0 = collapse), `toolbar:star-add`, `toolbar:star-rename(appId, name)`, `toolbar:star-remove(appId)`.
- Produces (main -> Gator renderer): `custom-app:star-event` payloads `{ kind: 'add', url, title, fromAppId } | { kind: 'rename', appId, name } | { kind: 'remove', appId }`.
- Produces (renderer -> main): `custom-app:set-hidden(appId, hidden: boolean)`, `custom-app:teardown(appId)`.

- [ ] **Step 1: Attach listeners to generic panes**

In `createGenericPane`, after `view.setBounds(...)` and before `_genericPanes[id] = ...`, add `_attachToolbarListeners(view, id);`.

- [ ] **Step 2: Compute and push the star**

Add near the top of the toolbar section in `main.js`:

```js
const toolbarStar = require('./toolbar-star');
const _hiddenCustomApps = new Set();

function _starFor(app, url) {
  if (!_customAppIds.has(app)) return { state: 'hidden', appId: null, name: '' };
  const apps = [..._customAppIds].map((id) => ({ id, url: _genericPanes[id] ? _genericPanes[id].url : '' }));
  const s = toolbarStar.starState(url, apps, _hiddenCustomApps);
  const name = s.appId && _genericPanes[s.appId] ? _genericPanes[s.appId].name : '';
  return { state: s.state, appId: s.appId, name };
}
```

In `_toolbarPushState` add `star: _starFor(app, url),` to `state`. In the 500 ms poller send `{ nav, url: wc.getURL() || '', star: _starFor(activeExternalApp, wc.getURL() || '') }`.

- [ ] **Step 3: Expandable toolbar height**

Add `let _toolbarExpandedH = 0;` next to `TOOLBAR_H`. In `layout()` replace the two `toolbarView.setBounds({ ..., height: TOOLBAR_H })` calls with `height: TOOLBAR_H + _toolbarExpandedH` (pane bounds stay at `TOOLBAR_H`, so the toolbar overlays the pane while open). Add:

```js
ipcMain.on('toolbar:set-expanded', (e, h) => {
  if (!_isMainToolbar(e)) return;
  _toolbarExpandedH = Math.max(0, Math.min(Number(h) || 0, 400));
  layout();
});
```

Reset `_toolbarExpandedH = 0` when `activeExternalApp` changes (in `layout()` when `!showToolbar`).

- [ ] **Step 4: Star IPC**

Replace `toolbar:save-custom-app` with:

```js
ipcMain.on('toolbar:star-add', (e) => {
  if (!_isMainToolbar(e) || !activeExternalApp) return;
  const v = viewForApp(activeExternalApp);
  if (!v || v.webContents.isDestroyed()) return;
  _sendToGator('custom-app:star-event', {
    kind: 'add',
    url: v.webContents.getURL(),
    title: v.webContents.getTitle(),
    fromAppId: activeExternalApp,
  });
});
ipcMain.on('toolbar:star-rename', (e, appId, name) => {
  if (!_isMainToolbar(e) || !_customAppIds.has(appId) || typeof name !== 'string') return;
  _sendToGator('custom-app:star-event', { kind: 'rename', appId, name: name.trim().slice(0, 40) });
});
ipcMain.on('toolbar:star-remove', (e, appId) => {
  if (!_isMainToolbar(e) || !_customAppIds.has(appId)) return;
  _sendToGator('custom-app:star-event', { kind: 'remove', appId });
});
ipcMain.handle('custom-app:set-hidden', (_e, appId, hidden) => {
  if (typeof appId !== 'string' || !_customAppIds.has(appId)) return false;
  if (hidden) _hiddenCustomApps.add(appId);
  else _hiddenCustomApps.delete(appId);
  layout();
  return true;
});
ipcMain.handle('custom-app:teardown', async (_e, appId) => {
  if (typeof appId !== 'string' || !_customAppIds.has(appId)) return false;
  const pane = _genericPanes[appId];
  if (activeExternalApp === appId) activeExternalApp = null;
  _customAppIds.delete(appId);
  _hiddenCustomApps.delete(appId);
  delete _genericPanes[appId];
  delete APP_HOME_URL[appId];
  if (pane && pane.view) {
    try { win.contentView.removeChildView(pane.view); } catch {}
    try { pane.view.webContents.close(); } catch {}
  }
  if (pane && pane.partition) {
    try { await session.fromPartition(pane.partition).clearStorageData(); } catch {}
  }
  layout();
  return true;
});
```

`layout()` hides panes whose id is in `_hiddenCustomApps` (add to the visibility loop: `setVisible(activeExternalApp === paneId && !_hiddenCustomApps.has(paneId))`), and if the active app is hidden, `activeExternalApp = null` before computing `activeView`.

- [ ] **Step 5: Preload**

In `shell/preload.js` after `createCustomApp`:

```js
  customAppSetHidden: (id, hidden) => ipcRenderer.invoke('custom-app:set-hidden', id, hidden),
  customAppTeardown: (id) => ipcRenderer.invoke('custom-app:teardown', id),
  onCustomAppStar: (callback) => {
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on('custom-app:star-event', listener);
    return () => ipcRenderer.removeListener('custom-app:star-event', listener);
  },
```

- [ ] **Step 6: Verify and commit**

Run: `cd shell && node --check main.js && node --check preload.js && node --test ../tests/toolbar-star.test.js`
Expected: no syntax errors, tests pass.

```bash
git add shell/main.js shell/preload.js
git commit -m "feat(shell): push star state to the toolbar and wire custom panes into toolbar events"
```

---

### Task 3: Toolbar UI (remove pill, add star and bubble)

**Files:**
- Modify: `shell/toolbar.html` (markup 568-618, CSS `.tb-app` 250-266 and `.tb-app-cta` 234-246, JS: `render*` functions and the `toolbar:state` handler)

**Interfaces:**
- Consumes: `toolbar:state.star`, `toolbar:set-expanded`, `toolbar:star-add|rename|remove`.

- [ ] **Step 1: Remove the pill and CTA**

Delete `#tb-app`, `#tb-app-cta` markup, their CSS, the `elApp*` constants, `renderApp()` and the click handler that sent `toolbar:save-custom-app`.

- [ ] **Step 2: Add the star button**

Inside `#tb-url`, immediately before `#tb-overflow`:

```html
<button class="tb-star" id="tb-star" type="button" aria-label="Add to Gator apps" aria-pressed="false" hidden>
  <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path class="tb-star-path" d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.8 6.8 19.6l1-5.8-4.3-4.1 5.9-.9z"/></svg>
</button>
```

CSS (uses toolbar variables; empty = outline `--text-sub`, hover = `--text`, filled = `--accent` fill, focus ring = 1px `--accent` outline):

```css
.tb-star { width: 20px; height: 20px; flex-shrink: 0; background: none; border: none; border-radius: 4px; cursor: pointer; display: flex; align-items: center; justify-content: center; color: var(--text-sub); transition: var(--transition); }
.tb-star[hidden] { display: none; }
.tb-star:hover { color: var(--text); background: var(--surface2, rgba(255,255,255,0.06)); }
.tb-star:focus-visible { outline: 1px solid var(--accent); outline-offset: 1px; }
.tb-star .tb-star-path { fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linejoin: round; }
.tb-star.is-filled { color: var(--accent); }
.tb-star.is-filled .tb-star-path { fill: currentColor; }
```

- [ ] **Step 3: Star state and click**

In the `toolbar:state` handler: `star = s.star || {state:'hidden'}`; set `elStar.hidden = star.state === 'hidden'`, toggle `is-filled`, `aria-pressed`, label ("Add to Gator apps" / "Edit Gator app"). Close the bubble when `star.appId` changes. Click: empty -> `ipcRenderer.send('toolbar:star-add')`; filled -> `openBubble()`.

- [ ] **Step 4: Bubble**

Markup after `#tb-menu`:

```html
<div class="tb-bubble" id="tb-bubble" role="dialog" aria-label="Gator app" hidden>
  <label class="tb-bubble-label" for="tb-bubble-name">Name</label>
  <input class="tb-bubble-name" id="tb-bubble-name" type="text" maxlength="40" spellcheck="false" />
  <div class="tb-bubble-note">Removing deletes this app's pins, settings and saved sign-in.</div>
  <div class="tb-bubble-actions">
    <button type="button" class="tb-bubble-remove" id="tb-bubble-remove">Remove</button>
    <button type="button" class="tb-bubble-done" id="tb-bubble-done">Done</button>
  </div>
</div>
```

JS: `openBubble()` sets the name input to `star.name`, shows the bubble, sends `toolbar:set-expanded` with 150, focuses the name input (select all), never Remove. `closeBubble()` hides, sends `toolbar:set-expanded` 0. Done: if name changed and non-empty, send `toolbar:star-rename`; close. Remove: send `toolbar:star-remove`; close. Enter in the name field = Done; Esc anywhere in the bubble = close without change; `document` click outside the bubble and star = Done. Position `top: calc(var(--tb-h) + 4px); right: 8px; width: 260px`; style with `--surface`, `--border2`, 8px radius, same shadow as `.tb-menu`; Remove uses a danger color (`#ef4444`, text button), Done is the accent primary button.

- [ ] **Step 5: Verify and commit**

Run the Electron shell, open a custom app: star is empty on a non-saved page, filled on a saved app's own origin, hidden on Teams; bubble opens, is not clipped, Esc closes it.

```bash
git add shell/toolbar.html
git commit -m "feat(toolbar): replace the app pill and Save-as button with a favorite star and edit bubble"
```

---

### Task 4: Renderer flows, rename route, undo toast

**Files:**
- Modify: `web/routes/mcp_routes.py` (after `remove_custom_app`, ~874)
- Create: `tests/test_custom_app_rename.py`
- Create: `web/static/custom-app-star.js`
- Modify: `web/static/index.html` (script tag next to `web-pins.js`), `web/static/style.css`

**Interfaces:**
- Consumes: `gatorShell.onCustomAppStar`, `customAppSetHidden`, `customAppTeardown`, `createCustomApp`, `showCustomApp`; app.js globals `_registerCustomAppSkill`, `SKILL_REGISTRY`, `SKILL_MAP`, `renderDock`, `_loadCustomApps`.

- [ ] **Step 1: Failing route test**

```python
def test_rename_custom_app(client, tmp_config):
    created = client.post("/api/config/custom-apps", json={"name": "Old", "url": "https://example.com"}).json()["app"]
    res = client.patch(f"/api/config/custom-apps/{created['id']}", json={"name": "New"})
    assert res.status_code == 200
    assert res.json()["app"]["name"] == "New"
    apps = client.get("/api/config/custom-apps").json()["apps"]
    assert [a["name"] for a in apps] == ["New"]


def test_rename_unknown_app_404(client, tmp_config):
    assert client.patch("/api/config/custom-apps/custom-nope", json={"name": "X"}).status_code == 404
```

Use the same `client` / config fixtures the existing custom-app route tests use (grep `custom-apps` in `tests/` to copy the fixture names); CSRF headers as those tests do for DELETE.

- [ ] **Step 2: Implement**

```python
class CustomAppRename(BaseModel):
    name: str


@router.patch("/api/config/custom-apps/{app_id}", dependencies=[Depends(verify_csrf)])
def rename_custom_app(app_id: str, req: CustomAppRename):
    from config import update_config
    name = req.name.strip()[:40]
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    holder: dict[str, dict] = {}
    def _mutate(cfg: dict):
        apps = list(cfg.get("custom_apps", []))
        for a in apps:
            if a.get("id") == app_id:
                a["name"] = name
                holder["app"] = a
        cfg["custom_apps"] = apps
        return cfg
    update_config(_mutate)
    if "app" not in holder:
        raise HTTPException(status_code=404, detail="Custom app not found")
    return {"ok": True, "app": holder["app"]}
```

Run: `PYTHONPATH=/tmp/mcp1 pytest tests/test_custom_app_rename.py tests/test_csrf_route_inventory.py -q` - Expected: pass.

- [ ] **Step 3: Renderer module `custom-app-star.js`**

Handles `custom-app:star-event`:
- `add`: POST `/api/config/custom-apps` `{name: title-or-host, url}`; on success `gatorShell.createCustomApp(app)`, `_registerCustomAppSkill(app)`, `_loadCustomApps()`, `gatorShell.showCustomApp(app.id)`, navigate the source pane back is NOT done (left as is), show toast "Added to Gator apps" with **Edit** (re-sends focus to the bubble by showing the app and posting nothing; simply opens the app) and **Undo** (runs the remove flow immediately without a second toast).
- `rename`: PATCH, update `SKILL_MAP[id].label`, `renderDock()`, `_loadCustomApps()`.
- `remove`: `customAppSetHidden(id, true)`; hide dock item (remove from `SKILL_REGISTRY`/`SKILL_MAP`, `renderDock()`, keep the entry to restore); show toast "Removed <name> from Gator apps" with **Undo**; timer 8 s (paused on hover/focus). Undo: `customAppSetHidden(id, false)`, re-push the entry, `renderDock()`. Expiry or `beforeunload`: `fetch DELETE /api/config/custom-apps/<id>` then `customAppTeardown(id)`; `_loadCustomApps()`. After the hide, `showCustomApp`-less: the shell lands on Gator chat because the active pane was hidden.
- Toast DOM: `div.ca-toast[role=status]` fixed bottom-center in the Gator window with message and `button` actions; styles in `style.css` using existing tokens (`--surface`, `--border`, `--text`, `--accent`).

- [ ] **Step 4: Tests and commit**

Run: `cd shell && node --test ../tests/toolbar-star.test.js ../tests/web-pin*.test.js ../tests/web-pins-renderer.test.js` and `PYTHONPATH=/tmp/mcp1 pytest tests/test_custom_app_rename.py tests/test_csrf_route_inventory.py -q`.

```bash
git add web/routes/mcp_routes.py tests/test_custom_app_rename.py web/static/custom-app-star.js web/static/index.html web/static/style.css
git commit -m "feat(custom-apps): star adds an app, unstar removes it with an 8 second undo, bubble renames"
```

---

### Task 5: Manual verification and design review

- [ ] Run the shell; verify: star empty/hover/filled/focus in dark and light; bubble not clipped; star on a custom app saves and the toast appears; Undo within 8 s restores dock item, pane, sign-in; expiry removes the app after a restart; pill and CTA gone; stale pill case (custom app -> other site) now shows the right star state.
- [ ] Capture dark and light renders of star states, bubble and both toasts for Design Head.
