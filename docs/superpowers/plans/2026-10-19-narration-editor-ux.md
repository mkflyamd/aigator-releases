# Narration Editor UX and Delivery Widget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the chat and widgets from losing scroll position and caret when a widget re-measures, add a per-segment "Pause after" control with pacing tips, show merge progress and errors inside the narration editor, and replace the delivery widget's Download button with "Open final folder" / "Open project folder" plus a summary line.

**Architecture:** The scroll fix is generic and lives in the widget wrapper (`gatorWidgetResize` in `web/static/app.js`), so every widget benefits. "Pause after" is a number input in the Phase 3 editor template that emits `pause_after`; `tts_pipeline.py` sanitises it and writes an atomic progress file that a new read-only `GET /api/demo-projects/{id}/progress` route serves to the editor. Widgets make no backend call of their own: the editor and delivery widget post three named actions (`gator:demo-summary`, `gator:demo-progress`, `gator:demo-open-folder`) that a parent-side handler in `app.js` serves from the new `GET /api/demo-projects/{id}/summary` and `/progress` routes and the existing `POST /api/open-file` (extended with a `reveal` flag, so no new mutating route). The widget sandbox, CSP handling and CSRF handling are unchanged.

**Tech Stack:** Vanilla JS (widgets are sandboxed `html:widget` iframes), FastAPI, pytest, Node `assert` + `vm` for widget/JS tests (no jsdom).

**Spec:** `docs/superpowers/specs/2026-10-19-narration-editor-ux-design.md`

## Global Constraints

- Prerequisite: SP3 (demo project state) and SP2 (approval transaction) are merged. This plan consumes `web/demo_projects.py` (`get_project`, `create_project`, `update_project`), `web/routes/demo_projects.py` (`router`, `_get`), the editor's `_PROJECT_ID` / `id="btn-approve"`, and the pinned `gator:send-message` form. Locate every `SKILL.md` and `app.js` edit point by function name or `grep`, never by line number; both files are changed by SP2/SP3.
- Commit messages: conventional (`feat:`, `fix:`). **Never add a `Co-Authored-By` line.**
- The product is "AI Gator" — never "POC".
- The only fake credential in tests, examples and docs is `aigator-fake-api-key`.
- Every new POST/PUT/PATCH/DELETE route needs `dependencies=[Depends(verify_csrf)]` from `web/security.py`. This plan adds only GET routes and extends an existing POST body; `tests/csrf_route_baseline.txt` must not change.
- Email, Teams and Slack messages never auto-send (nothing in this plan touches them).
- Widget sandbox rules (a follow-up PR will drop `allow-same-origin` and put an allow-list on the parent bridge): do not change the iframe `sandbox` attribute or `gatorWidgetCspHtml()`; widget code never reads `window.top`, `window.parent` (other than `parent.postMessage`), the parent DOM or `__CSRF_TOKEN__`; widgets make no `fetch(window._GATOR + …)` calls — every widget-to-backend call is one named `gator:*` postMessage action with fixed parameters, handled in the parent (Task 8a). `<video src>` URLs are resource loads, not calls.
- Do the least that meets the acceptance criteria: no `[pause:…]` syntax in the UI, no capability probe, no new settings.
- JS tests run with `node tests/<name>.test.js`. Functions extracted from source by regex must be multi-line with the closing `}` at column 0 (the regex is `function NAME\([^)]*\)\s*\{[\s\S]*?\n\}`). Compare values that cross the `vm` realm boundary through `JSON.parse(JSON.stringify(x))`.
- Python tests run with `python -m pytest <path> -v` (`pytest.ini`: `pythonpath = web .`, `--import-mode=importlib`).

---

## File Structure

| File                                                     | Change                           | Responsibility                                                                                                                                                                  |
| -------------------------------------------------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `web/static/app.js`                                      | modify                           | `gatorWidgetScrollSnapshot` / `gatorWidgetScrollRestore`, wrapped measure in `gatorWidgetResize`; `gatorWidgetShouldReveal` / `gatorWidgetRevealOnce`; `_gatorWidgetRevealHold` |
| `web/skills/gator-demo-recorder/scripts/tts_pipeline.py` | modify                           | `_pause_after` sanitiser, `write_progress`, `--progress-file` / `--approval-id`                                                                                                 |
| `web/routes/utils.py`                                    | modify                           | `reveal` flag on `POST /api/open-file`                                                                                                                                          |
| `web/demo_project_delivery.py`                           | create                           | `project_summary`, `read_progress`                                                                                                                                              |
| `web/routes/demo_projects.py`                            | modify                           | `GET /api/demo-projects/{id}/summary` and `/progress`                                                                                                                           |
| `web/static/app.js` (Task 8a)                            | modify                           | `gatorDemoBridge` and three parent-handled actions: `gator:demo-summary`, `gator:demo-progress`, `gator:demo-open-folder`                                                       |
| `web/skills/gator-demo-recorder/SKILL.md`                | modify                           | Phase 3 editor (Pause after, tooltip, project-scoped video, merge progress), Phase 4 flags, Phase 5 delivery widget                                                             |
| `tests/widget_resize_scroll.test.js`                     | create                           | Task 1                                                                                                                                                                          |
| `tests/widget_reveal_once.test.js`                       | create                           | Task 2                                                                                                                                                                          |
| `tests/test_tts_pipeline_pacing.py`                      | create                           | Task 3                                                                                                                                                                          |
| `tests/test_tts_pipeline_progress.py`                    | create                           | Task 4                                                                                                                                                                          |
| `tests/test_open_file_reveal.py`                         | create                           | Task 5                                                                                                                                                                          |
| `tests/demo_project_state/test_delivery.py`              | create                           | Task 6                                                                                                                                                                          |
| `tests/narration_editor_widget.test.js`                  | create (Task 7), extend (Task 8) | editor widget logic and template checks                                                                                                                                         |
| `tests/demo_widget_bridge.test.js`                       | create                           | Task 8a                                                                                                                                                                         |
| `tests/demo_ready_widget.test.js`                        | create                           | Task 9                                                                                                                                                                          |

---

### Task 1: Preserve scroll when a widget re-measures

Root cause: `gatorWidgetResize` collapses the iframe to `height = '0'` to measure it. The browser clamps the chat's `scrollTop` (and the widget's own inner scroll) to the shorter document, and nothing restores them, so every re-measure (including each textarea keystroke that changes height) jumps the view. The fix wraps the measure in a snapshot/restore of every scrolled ancestor and the inner window scroll.

**Files:**

- Modify: `web/static/app.js` (`gatorWidgetResize`, under the `/* ── Widget System` comment)
- Test: `tests/widget_resize_scroll.test.js`

**Interfaces:**

- Consumes: existing `gatorWidgetResize(iframe)`.
- Produces: `gatorWidgetScrollSnapshot(iframe) -> { saved: [{el, top}], inner: {win, x, y} | null }`, `gatorWidgetScrollRestore(snap) -> void`. `gatorWidgetResize(iframe)` keeps its signature.

- [ ] **Step 1: Write the failing test**

Create `tests/widget_resize_scroll.test.js`:

```js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function extract(name) {
  const m = src.match(new RegExp('function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}'));
  if (!m) throw new Error(name + ' not found in app.js');
  return m[0];
}

const code = [
  extract('gatorWidgetScrollSnapshot'),
  extract('gatorWidgetScrollRestore'),
  extract('gatorWidgetResize'),
].join('\n');

// Build a fake iframe whose height setter clamps every ancestor scroller the
// way a browser does: max scrollTop = other + iframeHeight - view.
function makeWorld({ scrollers, contentH, innerY }) {
  const timers = [];
  let heightStr = '';
  let win;
  const style = {};
  Object.defineProperty(style, 'height', {
    get() {
      return heightStr;
    },
    set(v) {
      heightStr = v;
      const px = parseFloat(v) || 0;
      for (const s of scrollers) {
        const max = Math.max(0, s.other + px - s.view);
        if (s.scrollTop > max) s.scrollTop = max;
      }
      if (px === 0 && win) win.scrollY = 0;
    },
  });
  const doc = {
    body: { scrollHeight: contentH, offsetHeight: contentH },
    documentElement: { scrollHeight: contentH },
    head: { appendChild() {} },
    getElementById() {
      return null;
    },
    createElement() {
      return {};
    },
  };
  win = {
    scrollX: 0,
    scrollY: innerY || 0,
    scrollTo(x, y) {
      this.scrollX = x;
      this.scrollY = y;
    },
    document: doc,
    ResizeObserver: class {
      observe() {}
    },
  };
  // scrollers[0] is the iframe's parent, the last one is the outermost.
  for (let i = 0; i < scrollers.length; i++) {
    scrollers[i].parentElement = scrollers[i + 1] || null;
  }
  const iframe = {
    style,
    parentElement: scrollers[0] || null,
    contentDocument: doc,
    contentWindow: win,
  };
  const ctx = {
    setTimeout: (fn) => {
      timers.push(fn);
      return timers.length;
    },
  };
  const api = vm.runInNewContext(
    code + '\n;({ gatorWidgetResize, gatorWidgetScrollSnapshot, gatorWidgetScrollRestore })',
    ctx,
  );
  return { iframe, win, timers, api };
}

function scroller(top, other, view) {
  return { scrollTop: top, other, view, parentElement: null };
}

// 1. The outer chat scroller keeps its position through a re-measure.
{
  const msgs = scroller(2000, 2000, 600);
  const { iframe, timers, api } = makeWorld({ scrollers: [msgs], contentH: 1200 });
  api.gatorWidgetResize(iframe);
  assert.strictEqual(msgs.scrollTop, 2000, 'chat scrollTop restored after resize');
  assert.strictEqual(iframe.style.height, '1202px');
  timers.forEach((fn) => fn());
  assert.strictEqual(msgs.scrollTop, 2000, 'chat scrollTop restored after delayed measures');
  assert.strictEqual(iframe.style.height, '1202px');
}

// 2. Every scrolled ancestor is restored, not only the outermost.
{
  const wrap = scroller(300, 200, 100);
  const msgs = scroller(2000, 2000, 600);
  const { iframe, api } = makeWorld({ scrollers: [wrap, msgs], contentH: 1200 });
  api.gatorWidgetResize(iframe);
  assert.strictEqual(wrap.scrollTop, 300);
  assert.strictEqual(msgs.scrollTop, 2000);
}

// 3. The widget's own inner scroll survives the 3000px cap path.
{
  const msgs = scroller(0, 2000, 600);
  const { iframe, win, api } = makeWorld({ scrollers: [msgs], contentH: 5000, innerY: 400 });
  api.gatorWidgetResize(iframe);
  assert.strictEqual(win.scrollY, 400, 'inner scrollY restored');
  assert.strictEqual(iframe.style.height, '3000px');
}

// 4. An unscrolled widget stays unscrolled.
{
  const msgs = scroller(0, 2000, 600);
  const { iframe, win, api } = makeWorld({ scrollers: [msgs], contentH: 900 });
  api.gatorWidgetResize(iframe);
  assert.strictEqual(msgs.scrollTop, 0);
  assert.strictEqual(win.scrollY, 0);
}

// 5. Restore never undoes growth: a position already past the snapshot is kept.
{
  const el = { scrollTop: 300 };
  const { api } = makeWorld({ scrollers: [], contentH: 100 });
  api.gatorWidgetScrollRestore({ saved: [{ el, top: 100 }], inner: null });
  assert.strictEqual(el.scrollTop, 300);
}

console.log('widget_resize_scroll: PASS');
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node tests/widget_resize_scroll.test.js`
Expected: FAIL with `Error: gatorWidgetScrollSnapshot not found in app.js`

- [ ] **Step 3: Implement the snapshot/restore and wrap the measure**

In `web/static/app.js`, add these two functions immediately above `function gatorWidgetResize(iframe) {`:

```js
function gatorWidgetScrollSnapshot(iframe) {
  const saved = [];
  for (let el = iframe.parentElement; el; el = el.parentElement) {
    if (el.scrollTop > 0) saved.push({ el, top: el.scrollTop });
  }
  let win = null;
  try {
    win = iframe.contentWindow;
  } catch (_) {}
  const inner = win && win.scrollY > 0 ? { win, x: win.scrollX, y: win.scrollY } : null;
  return { saved, inner };
}

function gatorWidgetScrollRestore(snap) {
  for (const s of snap.saved) if (s.el.scrollTop < s.top) s.el.scrollTop = s.top;
  if (snap.inner && snap.inner.win.scrollY < snap.inner.y)
    snap.inner.win.scrollTo(snap.inner.x, snap.inner.y);
}
```

Then edit `gatorWidgetResize` itself. Replace

```js
function gatorWidgetResize(iframe) {
  const measure = () => {
```

with

```js
function gatorWidgetResize(iframe) {
  const applyHeight = () => {
```

and replace

```js
    } catch (_) {}
  };
  measure();
  setTimeout(measure, 50);
  setTimeout(measure, 300);
```

with

```js
    } catch (_) {}
  };
  const measure = () => {
    const snap = gatorWidgetScrollSnapshot(iframe);
    try { applyHeight(); } finally { gatorWidgetScrollRestore(snap); }
  };
  measure();
  setTimeout(measure, 50);
  setTimeout(measure, 300);
```

The `ResizeObserver` block below keeps calling `measure`, which is now the wrapped version.

- [ ] **Step 4: Run the test to verify it passes**

Run: `node tests/widget_resize_scroll.test.js`
Expected: `widget_resize_scroll: PASS`

- [ ] **Step 5: Commit**

```bash
git add tests/widget_resize_scroll.test.js web/static/app.js
git commit -m "fix: preserve chat and widget scroll when widgets re-measure"
```

---

### Task 2: Reveal a tall replacement widget once, and keep the post-stream pin off it

Problem: when the agent streams a replacement editor (e.g. after "Edit narration"), the per-event autoscroll and the post-stream `_pinScrollToBottom` drag the view past the top of the tall widget. The fix reveals the widget's top once, marks the user as "not following" for the rest of the stream, and uses a hold flag so the post-stream pin (which runs after `_userScrolledUp` is reset at stream close) also stays off. The next send clears the hold.

**Files:**

- Modify: `web/static/app.js` (`let _userScrolledUp`, the capture `load` listener near the top of the file, `doSend`, the post-stream pin, and the Widget System section)
- Test: `tests/widget_reveal_once.test.js`

**Interfaces:**

- Consumes: `gatorWidgetResize(iframe)` (Task 1), existing globals `_chatTaskIds` (Set of streaming tab ids), `_activeTabId`, `_userScrolledUp`, `_pinScrollToBottom`.
- Produces: `let _gatorWidgetRevealHold`, `gatorWidgetShouldReveal(streaming, following, widgetH, viewportH) -> boolean`, `gatorWidgetRevealOnce(iframe) -> void`.

- [ ] **Step 1: Write the failing test**

Create `tests/widget_reveal_once.test.js`:

```js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function extract(name) {
  const m = src.match(new RegExp('function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}'));
  if (!m) throw new Error(name + ' not found in app.js');
  return m[0];
}

const code = [
  'let _userScrolledUp = false;',
  'let _gatorWidgetRevealHold = false;',
  extract('gatorWidgetShouldReveal'),
  extract('gatorWidgetRevealOnce'),
  '({ gatorWidgetShouldReveal, gatorWidgetRevealOnce,',
  '   state: () => ({ up: _userScrolledUp, hold: _gatorWidgetRevealHold }),',
  '   setUp: (v) => { _userScrolledUp = v; } })',
].join('\n');

function world({ streaming, wrapH, viewportH }) {
  const wrap = {
    offsetHeight: wrapH,
    getBoundingClientRect: () => ({ top: 700 }),
  };
  const msgs = {
    clientHeight: viewportH,
    scrollTop: 1000,
    getBoundingClientRect: () => ({ top: 100 }),
    contains: (el) => el === wrap,
  };
  const iframe = { closest: (sel) => (sel === '.gator-widget-wrap' ? wrap : null) };
  const ctx = {
    _chatTaskIds: new Set(streaming ? ['t1'] : []),
    _activeTabId: 't1',
    document: { getElementById: (id) => (id === 'messages' ? msgs : null) },
  };
  const api = vm.runInNewContext(code, ctx);
  return { api, msgs, iframe };
}

// Truth table for the pure decision.
const T = (...a) =>
  vm.runInNewContext(
    extract('gatorWidgetShouldReveal') + ';gatorWidgetShouldReveal(' + a.join(',') + ')',
  );
assert.strictEqual(T(true, true, 900, 500), true);
assert.strictEqual(T(false, true, 900, 500), false, 'not streaming');
assert.strictEqual(T(true, false, 900, 500), false, 'user scrolled up');
assert.strictEqual(T(true, true, 400, 500), false, 'widget fits the viewport');
assert.strictEqual(T(true, true, 500, 500), false, 'equal height does not need a reveal');

// Reveal scrolls the widget top into view and sets both flags.
{
  const { api, msgs, iframe } = world({ streaming: true, wrapH: 900, viewportH: 500 });
  api.gatorWidgetRevealOnce(iframe);
  assert.strictEqual(msgs.scrollTop, 1600);
  assert.deepStrictEqual(JSON.parse(JSON.stringify(api.state())), { up: true, hold: true });
}

// No reveal: short widget, not streaming, or the user already scrolled up.
{
  const short = world({ streaming: true, wrapH: 300, viewportH: 500 });
  short.api.gatorWidgetRevealOnce(short.iframe);
  assert.strictEqual(short.msgs.scrollTop, 1000);
  assert.deepStrictEqual(JSON.parse(JSON.stringify(short.api.state())), { up: false, hold: false });

  const idle = world({ streaming: false, wrapH: 900, viewportH: 500 });
  idle.api.gatorWidgetRevealOnce(idle.iframe);
  assert.strictEqual(idle.msgs.scrollTop, 1000);

  const away = world({ streaming: true, wrapH: 900, viewportH: 500 });
  away.api.setUp(true);
  away.api.gatorWidgetRevealOnce(away.iframe);
  assert.strictEqual(away.msgs.scrollTop, 1000);
  assert.strictEqual(away.api.state().hold, false);
}

// Source wiring.
assert.ok(/let _gatorWidgetRevealHold = false;/.test(src), 'hold flag declared');
assert.ok(
  /if \(_activeTabId === requestTabId && !_userScrolledUp && !_gatorWidgetRevealHold\) _pinScrollToBottom\(messages\);/.test(
    src,
  ),
  'post-stream pin respects the hold',
);
assert.ok(
  /const doSend = async \(overridePayload\) => \{\s*_userScrolledUp = false;\s*_gatorWidgetRevealHold = false;/.test(
    src,
  ),
  'doSend clears the hold',
);
assert.ok(
  /gatorWidgetResize\(el\);\s*gatorWidgetRevealOnce\(el\);/.test(src),
  'load listener reveals once',
);

console.log('widget_reveal_once: PASS');
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node tests/widget_reveal_once.test.js`
Expected: FAIL with `Error: gatorWidgetShouldReveal not found in app.js`

- [ ] **Step 3: Implement**

In `web/static/app.js`:

1. Directly below the line `let _userScrolledUp = false;` add:

```js
let _gatorWidgetRevealHold = false;
```

2. Add these two functions directly below `gatorWidgetScrollRestore` (from Task 1):

```js
function gatorWidgetShouldReveal(streaming, following, widgetH, viewportH) {
  return !!streaming && !!following && widgetH > viewportH;
}

function gatorWidgetRevealOnce(iframe) {
  try {
    const wrap = iframe.closest ? iframe.closest('.gator-widget-wrap') : null;
    const msgs = document.getElementById('messages');
    if (!wrap || !msgs || !msgs.contains(wrap)) return;
    if (
      !gatorWidgetShouldReveal(
        _chatTaskIds.has(_activeTabId),
        !_userScrolledUp,
        wrap.offsetHeight,
        msgs.clientHeight,
      )
    )
      return;
    _userScrolledUp = true;
    _gatorWidgetRevealHold = true;
    msgs.scrollTop =
      wrap.getBoundingClientRect().top - msgs.getBoundingClientRect().top + msgs.scrollTop;
  } catch (_) {}
}
```

3. In the capture `load` listener near the top of the file (grep `gator-widget-frame')) gatorWidgetResize(el);`), replace

```js
if (el && el.classList && el.classList.contains('gator-widget-frame')) gatorWidgetResize(el);
```

with

```js
if (el && el.classList && el.classList.contains('gator-widget-frame')) {
  gatorWidgetResize(el);
  gatorWidgetRevealOnce(el);
}
```

4. In `doSend` (grep `const doSend = async (overridePayload) => {`; there are three `_userScrolledUp = false;` sites, edit only the one directly under that line) replace

```js
  const doSend = async (overridePayload) => {
    _userScrolledUp = false;
```

with

```js
  const doSend = async (overridePayload) => {
    _userScrolledUp = false;
    _gatorWidgetRevealHold = false;
```

5. At the post-stream pin (grep `!_userScrolledUp) _pinScrollToBottom(messages);`), replace

```js
if (_activeTabId === requestTabId && !_userScrolledUp) _pinScrollToBottom(messages);
```

with

```js
if (_activeTabId === requestTabId && !_userScrolledUp && !_gatorWidgetRevealHold)
  _pinScrollToBottom(messages);
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node tests/widget_reveal_once.test.js && node tests/widget_resize_scroll.test.js`
Expected: `widget_reveal_once: PASS` then `widget_resize_scroll: PASS`

- [ ] **Step 5: Commit**

```bash
git add tests/widget_reveal_once.test.js web/static/app.js
git commit -m "fix: reveal tall replacement widgets once and keep the post-stream pin off them"
```

---

### Task 3: Sanitise `pause_after` in the TTS pipeline

The editor will send `pause_after` as a number, but narration files can come from anywhere. The pipeline must tolerate strings, junk, negatives, NaN and absurd values.

**Files:**

- Modify: `web/skills/gator-demo-recorder/scripts/tts_pipeline.py`
- Test: `tests/test_tts_pipeline_pacing.py`

**Interfaces:**

- Consumes: existing `build_synced_audio(narration, out_dir, lemonade_url, model, voice)`.
- Produces: `PAUSE_MAX = 10.0`, `_pause_after(seg: dict) -> float` (finite, `0.0 <= v <= PAUSE_MAX`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_tts_pipeline_pacing.py`:

```python
import importlib.util
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "web" / "skills" / "gator-demo-recorder" / "scripts" / "tts_pipeline.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("tts_pipeline_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def recorded(monkeypatch, tmp_path):
    pipe = _load()
    silences = []

    def fake_tts(text, out_path, *a, **k):
        Path(out_path).write_bytes(b"x")
        return 1

    monkeypatch.setattr(pipe, "get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(pipe, "generate_tts", fake_tts)
    monkeypatch.setattr(pipe, "get_duration", lambda *a, **k: 2.0)
    monkeypatch.setattr(pipe, "create_silence", lambda dur, out, ff: silences.append(round(dur, 2)))
    monkeypatch.setattr(pipe.subprocess, "run", lambda *a, **k: None)

    def run(narration):
        silences.clear()
        pipe.build_synced_audio(narration, tmp_path / "work", "http://x", "kokoro-v1", "af_heart")
        return list(silences)

    return pipe, run


def test_pause_is_inserted_and_absorbs_gap(recorded):
    _, run = recorded
    # seg0 ends at 2.0, pause 1.5 -> 3.5, next start_at 3 is already past: no extra silence.
    assert run([{"start_at": 0, "text": "a", "pause_after": 1.5}, {"start_at": 3, "text": "b"}]) == [1.5]


def test_later_start_at_still_adds_remaining_gap(recorded):
    _, run = recorded
    # seg0 ends at 2.0, pause 0.5 -> 2.5, next start_at 6 -> 3.5s pre-silence.
    assert run([{"start_at": 0, "text": "a", "pause_after": 0.5}, {"start_at": 6, "text": "b"}]) == [0.5, 3.5]


def test_numeric_string_is_accepted(recorded):
    _, run = recorded
    assert run([{"start_at": 0, "text": "a", "pause_after": "1.5"}]) == [1.5]


@pytest.mark.parametrize("bad", ["abc", None, -2, float("nan"), float("-inf")])
def test_invalid_values_mean_no_pause(recorded, bad):
    _, run = recorded
    assert run([{"start_at": 0, "text": "a", "pause_after": bad}]) == []


def test_missing_key_means_no_pause(recorded):
    _, run = recorded
    assert run([{"start_at": 0, "text": "a"}]) == []


def test_huge_value_is_capped(recorded):
    _, run = recorded
    assert run([{"start_at": 0, "text": "a", "pause_after": 99}]) == [10.0]


def test_pause_after_unit():
    pipe = _load()
    assert pipe._pause_after({"pause_after": 1.26}) == 1.26
    assert pipe._pause_after({"pause_after": "2"}) == 2.0
    assert pipe._pause_after({"pause_after": 10.5}) == 10.0
    assert pipe._pause_after({}) == 0.0
    assert pipe._pause_after({"pause_after": float("inf")}) == 0.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_tts_pipeline_pacing.py -v`
Expected: FAIL — `test_numeric_string_is_accepted` raises `TypeError` (`'>' not supported between 'str' and 'int'`), `test_huge_value_is_capped` fails (`[99]`), `test_pause_after_unit` fails with `AttributeError: ... has no attribute '_pause_after'`.

- [ ] **Step 3: Implement**

In `tts_pipeline.py`, add `import math` after `import json`, and add below the imports (above `def get_ffmpeg_path`):

```python
PAUSE_MAX = 10.0


def _pause_after(seg):
    try:
        v = float(seg.get("pause_after", 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(v) or v <= 0:
        return 0.0
    return min(v, PAUSE_MAX)
```

In `build_synced_audio`, replace

```python
            "duration": dur, "pause_after": seg.get("pause_after", 0),
```

with

```python
            "duration": dur, "pause_after": _pause_after(seg),
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_tts_pipeline_pacing.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_tts_pipeline_pacing.py web/skills/gator-demo-recorder/scripts/tts_pipeline.py
git commit -m "fix: sanitise pause_after in the TTS pipeline"
```

---

### Task 4: Report TTS and merge progress to a progress file

The editor needs to show "Generating speech 2 of 5", "Merging audio and video", "Done", or the failure text. The pipeline writes one small JSON file atomically; the widget polls it (Tasks 6 and 8).

**Files:**

- Modify: `web/skills/gator-demo-recorder/scripts/tts_pipeline.py`
- Test: `tests/test_tts_pipeline_progress.py`

**Interfaces:**

- Consumes: `build_synced_audio`, `merge_audio_video`, `main()` from the current file (Task 3 already added `_pause_after`).
- Produces:
  - `write_progress(path, approval_id, state, stage, step=0, total=0, message="", error=None) -> None` (no-op when `path` is falsy; atomic via temp file + `os.replace`). JSON keys: `approval_id, state, stage, step, total, message, error, updated_at` (`updated_at` is `time.time()` seconds).
  - `build_synced_audio(..., on_segment=None)`; `on_segment(step, total)` is called before each segment's TTS.
  - CLI flags `--progress-file PATH` and `--approval-id ID` (both default `None`).
  - States: `running` (stage `tts` or `merge`), `done` (stage `done`), `failed` (stage = where it failed).

- [ ] **Step 1: Write the failing test**

Create `tests/test_tts_pipeline_progress.py`:

```python
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "web" / "skills" / "gator-demo-recorder" / "scripts" / "tts_pipeline.py"
)
APPROVAL = "appr_1_abcd1234"


def _load():
    spec = importlib.util.spec_from_file_location("tts_pipeline_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def pipe(monkeypatch, tmp_path):
    mod = _load()

    def fake_tts(text, out_path, *a, **k):
        Path(out_path).write_bytes(b"x")
        return 1

    monkeypatch.setattr(mod, "get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(mod, "generate_tts", fake_tts)
    monkeypatch.setattr(mod, "get_duration", lambda *a, **k: 2.0)
    monkeypatch.setattr(mod, "create_silence", lambda *a, **k: None)
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(mod, "merge_audio_video", lambda *a, **k: None)
    (tmp_path / "timeline.json").write_text("[]", encoding="utf-8")
    (tmp_path / "narration.json").write_text(
        json.dumps([{"start_at": 0, "text": "a"}, {"start_at": 3, "text": "b"}]), encoding="utf-8"
    )
    (tmp_path / "rec.mp4").write_bytes(b"x")
    return mod


def _argv(tmp_path, progress):
    argv = [
        "tts_pipeline.py",
        "--video", str(tmp_path / "rec.mp4"),
        "--timeline", str(tmp_path / "timeline.json"),
        "--narration", str(tmp_path / "narration.json"),
        "--output", str(tmp_path / "final.mp4"),
        "--work-dir", str(tmp_path / "work"),
    ]
    if progress:
        argv += ["--progress-file", str(progress), "--approval-id", APPROVAL]
    return argv


def _spy(pipe, monkeypatch):
    records = []
    real = pipe.write_progress

    def spy(path, *a, **k):
        real(path, *a, **k)
        if path:
            records.append(json.loads(Path(path).read_text(encoding="utf-8")))

    monkeypatch.setattr(pipe, "write_progress", spy)
    return records


def test_successful_run_reports_each_stage(pipe, monkeypatch, tmp_path):
    progress = tmp_path / "work" / "logs" / "merge_progress.json"
    records = _spy(pipe, monkeypatch)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, progress))
    pipe.main()
    assert [(r["state"], r["stage"]) for r in records] == [
        ("running", "tts"), ("running", "tts"), ("running", "merge"), ("done", "done"),
    ]
    assert records[0]["message"] == "Generating speech 1 of 2"
    assert (records[0]["step"], records[0]["total"]) == (1, 2)
    assert records[2]["message"] == "Merging audio and video"
    assert all(r["approval_id"] == APPROVAL for r in records)
    assert all(isinstance(r["updated_at"], float) for r in records)


def test_merge_failure_is_recorded_and_reraised(pipe, monkeypatch, tmp_path):
    progress = tmp_path / "work" / "logs" / "merge_progress.json"
    records = _spy(pipe, monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("ffmpeg exploded")

    monkeypatch.setattr(pipe, "merge_audio_video", boom)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, progress))
    with pytest.raises(RuntimeError, match="ffmpeg exploded"):
        pipe.main()
    last = records[-1]
    assert (last["state"], last["stage"]) == ("failed", "merge")
    assert last["error"] == "ffmpeg exploded"
    assert last["message"] == "Generation failed"


def test_tts_failure_reports_tts_stage(pipe, monkeypatch, tmp_path):
    progress = tmp_path / "work" / "logs" / "merge_progress.json"
    records = _spy(pipe, monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("lemonade down")

    monkeypatch.setattr(pipe, "generate_tts", boom)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, progress))
    with pytest.raises(RuntimeError, match="lemonade down"):
        pipe.main()
    assert (records[-1]["state"], records[-1]["stage"]) == ("failed", "tts")


def test_no_progress_file_writes_nothing(pipe, monkeypatch, tmp_path):
    records = _spy(pipe, monkeypatch)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, None))
    pipe.main()
    assert records == []
    assert not list(tmp_path.rglob("merge_progress.json*"))


def test_write_progress_is_atomic_and_none_is_noop(pipe, tmp_path):
    target = tmp_path / "logs" / "p.json"
    pipe.write_progress(target, APPROVAL, "running", "tts", 1, 3, "Generating speech 1 of 3")
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["approval_id"] == APPROVAL and data["step"] == 1 and data["total"] == 3
    assert data["error"] is None
    assert not (tmp_path / "logs" / "p.json.tmp").exists()
    pipe.write_progress(None, APPROVAL, "running", "tts")
    assert sorted(p.name for p in (tmp_path / "logs").iterdir()) == ["p.json"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_tts_pipeline_progress.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'write_progress'` (the `_spy` fixture path) and `unrecognized arguments: --progress-file`.

- [ ] **Step 3: Implement**

In `tts_pipeline.py`:

1. Add `import time` below `import sys` (keep imports alphabetical-ish as in the file; position is not important).

2. Add this function directly above `def build_synced_audio`:

```python
def write_progress(path, approval_id, state, stage, step=0, total=0, message="", error=None):
    if not path:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps({
        "approval_id": approval_id, "state": state, "stage": stage,
        "step": step, "total": total, "message": message, "error": error,
        "updated_at": time.time(),
    }), encoding="utf-8")
    os.replace(tmp, p)
```

3. Change the `build_synced_audio` signature and loop. Replace

```python
def build_synced_audio(narration, out_dir, lemonade_url, model, voice):
```

with

```python
def build_synced_audio(narration, out_dir, lemonade_url, model, voice, on_segment=None):
```

and replace

```python
        seg_model = model
        print(f"  [TTS {i+1}/{len(narration)}] @{start_at:.1f}s: {seg['text'][:60]}...")
```

with

```python
        seg_model = model
        if on_segment:
            on_segment(i + 1, len(narration))
        print(f"  [TTS {i+1}/{len(narration)}] @{start_at:.1f}s: {seg['text'][:60]}...")
```

4. Replace the whole `main()` with:

```python
def main():
    parser = argparse.ArgumentParser(description="TTS pipeline for Gator demo")
    parser.add_argument("--video", required=True)
    parser.add_argument("--timeline", required=True)
    parser.add_argument("--narration", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--lemonade-url", default="http://localhost:13305")
    parser.add_argument("--model", default="kokoro-v1")
    parser.add_argument("--voice", default="af_heart")
    parser.add_argument("--work-dir", default=None)
    parser.add_argument("--progress-file", default=None)
    parser.add_argument("--approval-id", default=None)
    args = parser.parse_args()

    def progress(state, stage, step=0, total=0, message="", error=None):
        write_progress(args.progress_file, args.approval_id, state, stage, step, total, message, error)

    stage = "tts"
    try:
        work_dir = Path(args.work_dir or Path(args.video).parent / "tts_work")
        work_dir.mkdir(parents=True, exist_ok=True)

        with open(args.timeline) as f:
            timeline = json.load(f)
        with open(args.narration) as f:
            narration = json.load(f)
        total = len(narration)

        print("=" * 60)
        print("  TTS PIPELINE — Synced Narration")
        print("=" * 60)

        def on_segment(step, count):
            progress("running", "tts", step, count, f"Generating speech {step} of {count}")

        print(f"\n[1/3] Generating TTS segments ({total})...")
        audio = build_synced_audio(
            narration, work_dir, args.lemonade_url, args.model, args.voice, on_segment=on_segment
        )

        stage = "merge"
        progress("running", "merge", total, total, "Merging audio and video")
        print(f"\n[2/3] Merging audio with video...")
        merge_audio_video(args.video, audio, args.output)

        progress("done", "done", total, total, "Done")
        print(f"\n[3/3] Done! Final: {args.output}")
    except Exception as exc:
        progress("failed", stage, message="Generation failed", error=str(exc))
        raise
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tts_pipeline_progress.py tests/test_tts_pipeline_pacing.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_tts_pipeline_progress.py web/skills/gator-demo-recorder/scripts/tts_pipeline.py
git commit -m "feat: report TTS and merge progress to a progress file"
```

---

### Task 5: Reveal a file in its folder through `/api/open-file`

"Open final folder" should open Explorer with the final video selected. The existing `POST /api/open-file` already handles path checks, the executable deny-list and errors, so it gains an optional `reveal` flag instead of a new route. It is an existing POST route, so the CSRF inventory and `tests/csrf_route_baseline.txt` are untouched.

**Files:**

- Modify: `web/routes/utils.py` (`OpenFileRequest`, `_do_open_file`, `open_file`; locate by `grep -n "class OpenFileRequest\|def _do_open_file\|_do_open_file," web/routes/utils.py`)
- Test: `tests/test_open_file_reveal.py`

**Interfaces:**

- Consumes: existing `POST /api/open-file` (body `{path}`; returns `{"ok": true}` or `{"ok": false, "reason", "message"}`).
- Produces: body field `reveal: bool = False`; `_do_open_file(path: str, is_dir: bool = False, reveal: bool = False) -> None`. `reveal` is ignored for directories.

- [ ] **Step 1: Write the failing test**

Create `tests/test_open_file_reveal.py`:

```python
import os

import pytest
from fastapi.testclient import TestClient

from app import app
from routes import utils
from security import get_csrf_token


@pytest.fixture
def calls(monkeypatch):
    seen = []
    monkeypatch.setattr(utils.subprocess, "run", lambda cmd, **kw: seen.append(cmd))
    monkeypatch.setattr(utils, "no_window_kwargs", lambda: {})
    return seen


@pytest.fixture
def client():
    c = TestClient(app)
    c.headers["X-CSRF-Token"] = get_csrf_token("testserver")
    return c


@pytest.mark.parametrize(
    "platform,expected",
    [
        ("win32", lambda p: ["explorer", "/select," + os.path.normpath(p)]),
        ("darwin", lambda p: ["open", "-R", p]),
        ("linux", lambda p: ["xdg-open", os.path.dirname(p)]),
    ],
)
def test_reveal_selects_the_file(calls, monkeypatch, tmp_path, platform, expected):
    f = tmp_path / "AI_Gator_Demo.mp4"
    f.write_bytes(b"x")
    monkeypatch.setattr(utils.sys, "platform", platform)
    utils._do_open_file(str(f), False, True)
    assert calls == [expected(str(f))]


def test_file_without_reveal_still_opens_in_default_app(calls, monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(utils.os, "startfile", lambda p: started.append(p), raising=False)
    f = tmp_path / "a.mp4"
    f.write_bytes(b"x")
    utils._do_open_file(str(f))
    assert started == [str(f)]
    assert calls == []


def test_directory_ignores_reveal(calls, monkeypatch, tmp_path):
    monkeypatch.setattr(utils.sys, "platform", "linux")
    utils._do_open_file(str(tmp_path), True, True)
    assert calls == [["xdg-open", str(tmp_path)]]


def test_route_forwards_reveal(client, monkeypatch, tmp_path):
    f = tmp_path / "AI_Gator_Demo.mp4"
    f.write_bytes(b"x")
    seen = []
    monkeypatch.setattr(
        utils, "_do_open_file",
        lambda path, is_dir=False, reveal=False: seen.append((path, is_dir, reveal)),
    )
    r = client.post("/api/open-file", json={"path": str(f), "reveal": True})
    assert r.json() == {"ok": True}
    r = client.post("/api/open-file", json={"path": str(f)})
    assert r.json() == {"ok": True}
    assert seen == [(str(f), False, True), (str(f), False, False)]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_open_file_reveal.py -v`
Expected: FAIL — `TypeError: _do_open_file() takes from 1 to 2 positional arguments but 3 were given`; the route test fails because `reveal` is ignored.

- [ ] **Step 3: Implement**

In `web/routes/utils.py`:

1. Replace

```python
class OpenFileRequest(BaseModel):
    path: str
```

with

```python
class OpenFileRequest(BaseModel):
    path: str
    reveal: bool = False
```

2. Replace the `_do_open_file` signature and add the reveal branch. Replace

```python
def _do_open_file(path: str, is_dir: bool = False) -> None:
    """Open a file in its default app, or reveal a folder in the OS file manager.

    For directories we invoke the file manager explicitly rather than rely on
    os.startfile()'s ambiguous folder handling, which could fail silently."""
    if is_dir:
```

with

```python
def _do_open_file(path: str, is_dir: bool = False, reveal: bool = False) -> None:
    """Open a file in its default app, or reveal a folder in the OS file manager.

    For directories we invoke the file manager explicitly rather than rely on
    os.startfile()'s ambiguous folder handling, which could fail silently."""
    if reveal and not is_dir:
        if sys.platform == "win32":
            subprocess.run(["explorer", "/select," + os.path.normpath(path)], **no_window_kwargs())
            return
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", path])
            return
        subprocess.run(["xdg-open", os.path.dirname(path)])
        return
    if is_dir:
```

3. In `open_file`, replace

```python
        await loop.run_in_executor(None, _do_open_file, str(p), p.is_dir())
```

with

```python
        await loop.run_in_executor(None, _do_open_file, str(p), p.is_dir(), req.reveal)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_open_file_reveal.py -v`
Expected: all PASS. Then run any existing open-file tests: `python -m pytest tests -k "open_file" -v` — expected PASS (the new parameters have defaults).

- [ ] **Step 5: Commit**

```bash
git add tests/test_open_file_reveal.py web/routes/utils.py
git commit -m "feat: open-file can reveal a file in its folder"
```

---

### Task 6: Project summary and merge-progress routes

The delivery widget needs the final file, source count and working-file size; the editor needs the latest progress record. Both are read-only, so they are GET routes (no CSRF dependency needed) and live next to SP3's project routes.

**Files:**

- Create: `web/demo_project_delivery.py`
- Modify: `web/routes/demo_projects.py` (add one import and two routes at the end)
- Test: `tests/demo_project_state/test_delivery.py`

**Interfaces:**

- Consumes (SP3): `demo_projects.get_project(project_id) -> dict` with `path`, `raw` (absolute path of the current raw video, or `None`), `final_dir`, `final` (absolute path of the newest file in `final/`, or `None`), `segments` (list of absolute source paths); `KeyError` for an unknown id. In `web/routes/demo_projects.py`: `router`, `_get(project_id)` (404 on unknown id). Test fixture `store` from `tests/demo_project_state/conftest.py`.
- Produces:
  - `delivery.project_summary(project_id) -> {"project_id", "path", "final_dir", "final", "final_rel", "raw_rel", "source_count", "work_bytes"}` where `final_rel` is `"final/<filename>"` or `None`, `raw_rel` is the project-relative POSIX path of the current raw video (or `None` when the project has no raw video; the editor's preview uses it, so no widget-side path maths is needed), `source_count = len(segments)`, `work_bytes` = total file bytes under `<project>/work`.
  - `delivery.read_progress(project_id) -> dict`: the parsed `work/logs/merge_progress.json`, or `{"state": "none"}` when missing, unreadable or not a JSON object.
  - `GET /api/demo-projects/{project_id}/summary` and `GET /api/demo-projects/{project_id}/progress`.

- [ ] **Step 1: Write the failing test**

Create `tests/demo_project_state/test_delivery.py`:

```python
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import demo_project_delivery as delivery
from app import app
from security import get_csrf_token


@pytest.fixture
def client():
    c = TestClient(app)
    c.headers["X-CSRF-Token"] = get_csrf_token("testserver")
    return c


def _project(store):
    proj = store.create_project("Delivery demo")
    return proj["project_id"], Path(proj["path"])


def test_summary_without_final(store):
    pid, root = _project(store)
    s = delivery.project_summary(pid)
    assert s["project_id"] == pid
    assert s["final"] is None and s["final_rel"] is None
    assert s["source_count"] == 0
    assert Path(s["final_dir"]).name == "final"


def test_summary_raw_rel_is_project_relative(store):
    pid, root = _project(store)
    (root / "source").mkdir(parents=True, exist_ok=True)
    raw = root / "source" / "raw.mp4"
    raw.write_bytes(b"v")
    store.update_project(pid, raw=str(raw))
    assert delivery.project_summary(pid)["raw_rel"] == "source/raw.mp4"


def test_summary_raw_rel_none_without_a_raw_video(store):
    pid, root = _project(store)
    assert delivery.project_summary(pid)["raw_rel"] is None


def test_summary_with_final_sources_and_work_bytes(store):
    pid, root = _project(store)
    base = delivery.project_summary(pid)["work_bytes"]
    (root / "final").mkdir(parents=True, exist_ok=True)
    (root / "final" / "AI_Gator_Demo.mp4").write_bytes(b"abc")
    (root / "work" / "tts").mkdir(parents=True, exist_ok=True)
    (root / "work" / "logs").mkdir(parents=True, exist_ok=True)
    (root / "work" / "tts" / "a.mp3").write_bytes(b"x" * 1000)
    (root / "work" / "logs" / "b.log").write_bytes(b"y" * 24)
    (root / "source").mkdir(parents=True, exist_ok=True)
    sources = []
    for i in range(3):
        f = root / "source" / f"s{i}.mp4"
        f.write_bytes(b"v")
        sources.append(str(f))
    store.update_project(pid, segments=sources)

    s = delivery.project_summary(pid)
    assert s["final_rel"] == "final/AI_Gator_Demo.mp4"
    assert Path(s["final"]).name == "AI_Gator_Demo.mp4"
    assert s["source_count"] == 3
    assert s["work_bytes"] - base == 1024


def test_read_progress_states(store):
    pid, root = _project(store)
    assert delivery.read_progress(pid) == {"state": "none"}
    target = root / "work" / "logs" / "merge_progress.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"approval_id": "a1", "state": "running", "message": "Merging"}), encoding="utf-8")
    assert delivery.read_progress(pid)["approval_id"] == "a1"
    target.write_text("{not json", encoding="utf-8")
    assert delivery.read_progress(pid) == {"state": "none"}
    target.write_text("[1, 2]", encoding="utf-8")
    assert delivery.read_progress(pid) == {"state": "none"}


def test_routes(store, client):
    pid, root = _project(store)
    (root / "final").mkdir(parents=True, exist_ok=True)
    (root / "final" / "AI_Gator_Demo.mp4").write_bytes(b"abc")
    r = client.get(f"/api/demo-projects/{pid}/summary")
    assert r.status_code == 200
    assert r.json()["final_rel"] == "final/AI_Gator_Demo.mp4"
    r = client.get(f"/api/demo-projects/{pid}/progress")
    assert r.status_code == 200
    assert r.json() == {"state": "none"}


def test_unknown_project_is_404(store, client):
    assert client.get("/api/demo-projects/demo_missing/summary").status_code == 404
    assert client.get("/api/demo-projects/demo_missing/progress").status_code == 404
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/demo_project_state/test_delivery.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'demo_project_delivery'`

- [ ] **Step 3: Implement**

Create `web/demo_project_delivery.py`:

```python
import json
from pathlib import Path

import demo_projects as dp

PROGRESS_REL = Path("work") / "logs" / "merge_progress.json"


def _dir_bytes(folder):
    total = 0
    for f in Path(folder).rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            continue
    return total


def _rel_inside(root, target):
    if not target:
        return None
    try:
        return Path(target).resolve().relative_to(Path(root).resolve()).as_posix()
    except (OSError, ValueError):
        return None


def project_summary(project_id):
    proj = dp.get_project(project_id)
    root = Path(proj["path"])
    final = proj["final"]
    return {
        "project_id": project_id,
        "path": str(root),
        "final_dir": str(proj["final_dir"]),
        "final": str(final) if final else None,
        "final_rel": (Path("final") / Path(final).name).as_posix() if final else None,
        "raw_rel": _rel_inside(root, proj.get("raw")),
        "source_count": len(proj["segments"]),
        "work_bytes": _dir_bytes(root / "work"),
    }


def read_progress(project_id):
    root = Path(dp.get_project(project_id)["path"])
    try:
        data = json.loads((root / PROGRESS_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "none"}
    return data if isinstance(data, dict) else {"state": "none"}
```

In `web/routes/demo_projects.py`, add `import demo_project_delivery as delivery` next to the existing `import demo_projects as dp`, and append at the end of the file:

```python
@router.get("/api/demo-projects/{project_id}/summary")
async def project_summary_route(project_id: str):
    _get(project_id)
    return delivery.project_summary(project_id)


@router.get("/api/demo-projects/{project_id}/progress")
async def project_progress_route(project_id: str):
    _get(project_id)
    return delivery.read_progress(project_id)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/demo_project_state tests/test_csrf_route_inventory.py -v`
Expected: all PASS (the CSRF inventory ignores GET routes; `tests/csrf_route_baseline.txt` is unchanged).

- [ ] **Step 5: Commit**

```bash
git add web/demo_project_delivery.py web/routes/demo_projects.py tests/demo_project_state/test_delivery.py
git commit -m "feat: add demo project summary and progress routes"
```

---

### Task 7: Narration editor — "Pause after" control and pacing tips

All edits are inside the Phase 3 `html:widget` block of `web/skills/gator-demo-recorder/SKILL.md` (the block containing `Edit Narration Script`). Anchors below are exact strings from that template; locate them with `grep -n`, not line numbers.

**Files:**

- Modify: `web/skills/gator-demo-recorder/SKILL.md` (Phase 3 editor widget and the prose line above it)
- Test: `tests/narration_editor_widget.test.js` (created here, extended in Task 8)

**Interfaces:**

- Consumes: Task 3's pipeline coercion (`pause_after` in the approved segment objects).
- Produces (inside the editor widget): `pauseValue(raw) -> number` (0 to 10 in 0.1 steps; garbage, negative or empty gives 0), `segOut(s, text, voice, speed, pauseRaw) -> {start_at, text, voice, speed, pause_after}`, input ids `pa<i>`, tooltip id `pacing-tip`. SP2's `approve()` keeps its `data.map(function(s,i){ return …; })` shape; this task only swaps the `return` line for `segOut(...)`.

- [ ] **Step 1: Write the failing test**

Create `tests/narration_editor_widget.test.js`:

````js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const skill = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'skills', 'gator-demo-recorder', 'SKILL.md'),
  'utf8',
);
const blocks = [...skill.matchAll(/```html:widget\n([\s\S]*?)\n```/g)].map((m) => m[1]);
const editor = blocks.find((b) => b.includes('Edit Narration Script'));
assert.ok(editor, 'narration editor widget found in SKILL.md');

function fn(name) {
  const m = editor.match(new RegExp('function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}'));
  if (!m) throw new Error(name + ' not found in editor widget');
  return m[0];
}
const plain = (x) => JSON.parse(JSON.stringify(x));

// pauseValue / segOut
{
  const { pauseValue, segOut } = vm.runInNewContext(
    fn('pauseValue') + '\n' + fn('segOut') + '\n({ pauseValue, segOut })',
  );
  assert.strictEqual(pauseValue('1.5'), 1.5);
  assert.strictEqual(pauseValue('abc'), 0);
  assert.strictEqual(pauseValue(null), 0);
  assert.strictEqual(pauseValue(undefined), 0);
  assert.strictEqual(pauseValue(''), 0);
  assert.strictEqual(pauseValue(-3), 0);
  assert.strictEqual(pauseValue(99), 10);
  assert.strictEqual(pauseValue(1.26), 1.3);
  assert.deepStrictEqual(plain(segOut({ start_at: 4 }, 'hi', 'af_heart', 1, '2')), {
    start_at: 4,
    text: 'hi',
    voice: 'af_heart',
    speed: 1,
    pause_after: 2,
  });
  assert.deepStrictEqual(plain(segOut({ start: 5 }, 'x', 'af_nova', 1.1, '')), {
    start_at: 5,
    text: 'x',
    voice: 'af_nova',
    speed: 1.1,
    pause_after: 0,
  });
}

// Template wiring
assert.ok(editor.includes('Pause after (s)'), 'pause label');
assert.ok(editor.includes('id="pacing-tip"'), 'tooltip id');
assert.ok(editor.includes('Use commas and periods for natural breaths'), 'tooltip text');
assert.ok(!editor.includes('[pause:'), 'no [pause:...] syntax advertised');
assert.ok(editor.includes("'pa'+i"), 'per-segment pause input id');
assert.ok(
  editor.includes(
    "segOut(s, document.getElementById('s'+i).value, voice, speed, document.getElementById('pa'+i).value)",
  ),
  'approve() goes through segOut',
);

console.log('narration_editor_widget: PASS');
````

- [ ] **Step 2: Run the test to verify it fails**

Run: `node tests/narration_editor_widget.test.js`
Expected: FAIL with `Error: pauseValue not found in editor widget`

- [ ] **Step 3: Edit the editor template in `SKILL.md`**

3a. CSS — directly after the line `  .btn-seg-preview:hover{border-color:#f97316;color:#f97316}` add:

```css
.seg-pause {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.68rem;
  color: #6b8db5;
  margin-left: auto;
}
.seg-pause input {
  width: 56px;
  background: #111827;
  border: 1px solid #1e3a52;
  border-radius: 5px;
  color: #dbeafe;
  padding: 3px 6px;
  font-size: 0.72rem;
  font-family: inherit;
}
.seg-pause input:focus {
  outline: none;
  border-color: #4ade80;
}
.help {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border: 1px solid #1e3a52;
  border-radius: 50%;
  color: #6b8db5;
  font-size: 0.7rem;
  cursor: help;
}
.help:hover,
.help:focus {
  border-color: #f97316;
  color: #f97316;
  outline: none;
}
.tip {
  display: none;
  position: absolute;
  top: 24px;
  right: 0;
  width: 260px;
  z-index: 5;
  background: #0f1a28;
  border: 1px solid #1e3a52;
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 0.7rem;
  line-height: 1.4;
  color: #dbeafe;
  text-align: left;
  cursor: default;
}
.help:hover .tip,
.help:focus .tip,
.help:focus-within .tip {
  display: block;
}
```

3b. Tooltip — directly after the line `    <button class="btn-play-all" id="btn-play-all" onclick="playAll()">▶▶ Play all</button>` (still inside `.voice-row`) add:

```html
<span class="help" tabindex="0" role="button" aria-describedby="pacing-tip" aria-label="Pacing tips"
  >?<span class="tip" role="tooltip" id="pacing-tip"
    ><b>Pacing tips</b> — Use commas and periods for natural breaths; use <code>…</code> for a
    longer, trailing pause. For an exact silent gap after this section, set
    <b>Pause after</b>.</span
  ></span
>
```

3c. Helpers — insert immediately above the line that starts with `// ── Segments`:

```js
function pauseValue(raw) {
  var n = parseFloat(raw);
  if (!isFinite(n) || n < 0) {
    return 0;
  }
  return Math.min(10, Math.round(n * 10) / 10);
}

function segOut(s, text, voice, speed, pauseRaw) {
  return {
    start_at: s.start_at || s.start || 0,
    text: text,
    voice: voice,
    speed: speed,
    pause_after: pauseValue(pauseRaw),
  };
}
```

3d. Segment builder — directly after the line `  acts.appendChild(pb);` add:

```js
var pl = document.createElement('label');
pl.className = 'seg-pause';
pl.appendChild(document.createTextNode('Pause after (s)'));
var pi = document.createElement('input');
pi.type = 'number';
pi.id = 'pa' + i;
pi.min = '0';
pi.max = '10';
pi.step = '0.1';
pi.value = pauseValue(s.pause_after);
pi.oninput = function () {
  document.getElementById('dirty' + i).style.display = 'inline';
};
pl.appendChild(pi);
acts.appendChild(pl);
```

3e. `approve()` — replace the single line (SP2 keeps it inside `data.map(function(s,i){ … })`)

```js
return {
  start_at: s.start_at || s.start || 0,
  text: document.getElementById('s' + i).value,
  voice: voice,
  speed: speed,
};
```

with

```js
return segOut(
  s,
  document.getElementById('s' + i).value,
  voice,
  speed,
  document.getElementById('pa' + i).value,
);
```

3f. Prose — in the bullet that starts ``- `SEGMENTS_PLACEHOLDER` with a JSON array``, change it to:

```markdown
- `SEGMENTS_PLACEHOLDER` with a JSON array of `[{start_at: <seconds>, text: "<spoken text>"}]`. Each item may also carry an optional `pause_after` (seconds of silence after that segment, 0 to 10) — the widget shows it in the "Pause after" box.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `node tests/narration_editor_widget.test.js`
Expected: `narration_editor_widget: PASS`

- [ ] **Step 5: Commit**

```bash
git add tests/narration_editor_widget.test.js web/skills/gator-demo-recorder/SKILL.md
git commit -m "feat: add Pause after control and pacing tips to the narration editor"
```

---

### Task 8: Narration editor — project-scoped video and merge progress

The editor must stop calling `/api/recorder/latest-output` (SP3 removes it) and instead show the raw recording through the project file route. After SP2 replies that an approval was saved, the editor polls the Task 6 progress route and shows generation state, the failure text, or a stall message, and re-enables Approve on failure or stall. SP2 owns save and approve; this task only adds an independent listener for SP2's reply and never touches SP2's approve transaction.

**Files:**

- Modify: `web/skills/gator-demo-recorder/SKILL.md` (Phase 3 editor widget, the prose line above it, and the Phase 4 `subprocess.run` list)
- Test: `tests/narration_editor_widget.test.js` (extend)

**Interfaces:**

- Consumes:
  - SP2 editor: `var _PROJECT_ID = 'PROJECT_ID_PLACEHOLDER';`, the button `id="btn-approve"`, and the parent's reply message `{type:'gator:narration-approval-result', ok:true, approval:{approval_id, version, segment_count, reused}}` (the flat shape `{ok, approval_id, …}` is also accepted). SP2's Phase 4 variables `PROJECT_DIR` (a `Path`) and `verdict` (dict with `approval_id`).
  - Task 4 CLI flags; Task 6 `raw_rel` in the summary and `GET /api/demo-projects/{id}/progress`; SP3 `GET /api/demo-projects/{id}/file?rel=` (used only as the `<video>` `src`, a resource load).
  - Task 8a parent bridge actions `gator:demo-summary` and `gator:demo-progress` (see Task 8a). The widget makes no `fetch` call of its own.
- Produces (inside the editor widget): `progressView(p, approvalId, waitedMs, sinceMs) -> {text, color, stop, retry}`, `setMergeStatus`, `stopProgress`, `startProgress(approvalId, projectId)`, `requestDemoData(type, projectId)`, element `id="merge-status"`.

- [ ] **Step 1: Write the failing tests**

In `tests/narration_editor_widget.test.js`, insert the following immediately above the final `console.log('narration_editor_widget: PASS');` line:

```js
// Precondition from SP2
assert.ok(
  editor.includes("var _PROJECT_ID = 'PROJECT_ID_PLACEHOLDER'"),
  'SP2 must be merged: editor needs _PROJECT_ID',
);
assert.ok(
  editor.includes('id="btn-approve"'),
  'SP2 must be merged: Approve button needs id="btn-approve"',
);

// progressView
{
  const { progressView } = vm.runInNewContext(fn('progressView') + '\n({ progressView })');

  const SINCE = 1000000;
  const rec = (o) => Object.assign({ approval_id: 'a1', updated_at: SINCE / 1000 + 5 }, o);
  const view = (p, waited) =>
    plain(progressView(p, 'a1', waited === undefined ? 1000 : waited, SINCE));
  const WAITING = {
    text: 'Waiting for generation to start…',
    color: '#6b8db5',
    stop: false,
    retry: false,
  };
  const STALLED = {
    text: 'Generation has not started yet. Check that the AI Gator agent is still working, or click Approve to retry.',
    color: '#f87171',
    stop: true,
    retry: true,
  };

  assert.deepStrictEqual(view({ state: 'none' }), WAITING);
  assert.deepStrictEqual(view(null), WAITING);
  assert.deepStrictEqual(view(rec({ state: 'running', message: 'Generating speech 2 of 5' })), {
    text: 'Generating speech 2 of 5',
    color: '#f97316',
    stop: false,
    retry: false,
  });
  assert.deepStrictEqual(view(rec({ state: 'done' })), {
    text: 'Done — your demo video is ready.',
    color: '#4ade80',
    stop: true,
    retry: false,
  });
  assert.deepStrictEqual(view(rec({ state: 'failed', error: 'ffmpeg exploded' })), {
    text: 'Generation failed: ffmpeg exploded',
    color: '#f87171',
    stop: true,
    retry: true,
  });
  assert.deepStrictEqual(
    view(rec({ state: 'done', updated_at: SINCE / 1000 - 1 })),
    WAITING,
    'stale same-id record',
  );
  assert.deepStrictEqual(
    view(rec({ state: 'done', approval_id: 'a2' })),
    WAITING,
    'other approval',
  );
  assert.deepStrictEqual(view({ state: 'none' }, 120000), STALLED);
  assert.deepStrictEqual(
    view(rec({ state: 'running', approval_id: 'a2' }), 130000),
    STALLED,
    'other id does not mask a stall',
  );
  assert.strictEqual(
    view(rec({ state: 'done' }), 130000).text,
    'Done — your demo video is ready.',
    'a real result wins over the stall timer',
  );
}

// Template and SKILL.md wiring
assert.ok(editor.includes('id="merge-status"'), 'merge status element');
assert.ok(editor.includes('gator:narration-approval-result'), 'listens for the approval reply');
assert.ok(editor.includes("'gator:demo-summary'"), 'asks the parent for the project summary');
assert.ok(editor.includes("'gator:demo-progress'"), 'asks the parent for merge progress');
assert.ok(
  editor.includes('gator:demo-summary-result') && editor.includes('gator:demo-progress-result'),
  'listens for the parent replies',
);
assert.ok(!/fetch\(/.test(editor), 'editor makes no direct backend calls');
assert.ok(!editor.includes('latest-output'), 'editor no longer uses latest-output');
assert.ok(
  /"--progress-file", str\(PROJECT_DIR \/ "work" \/ "logs" \/ "merge_progress\.json"\),\s*"--approval-id", verdict\["approval_id"\]/.test(
    skill,
  ),
  'Phase 4 passes the progress flags',
);
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node tests/narration_editor_widget.test.js`
Expected: FAIL with `Error: progressView not found in editor widget` (or the `_PROJECT_ID` precondition message if SP2 is not merged — merge SP2 first).

- [ ] **Step 3: Edit `SKILL.md`**

3a. Video preview — in the editor script, replace everything from the comment line that starts `// ── Video preview` up to (not including) the line that starts `// ── Approve` with:

```js
// ── Video preview — summary comes from the parent; the video is a resource load ─
function requestDemoData(type, projectId) {
  parent.postMessage({ type: type, project_id: projectId }, '*');
}

var _pid = /^demo_\d/.test(_PROJECT_ID) ? _PROJECT_ID : '';
if (_pid) {
  requestDemoData('gator:demo-summary', _pid);
}

window.addEventListener('message', function (ev) {
  var m = ev.data || {};
  if (m.type !== 'gator:demo-summary-result' || m.project_id !== _pid) {
    return;
  }
  var rel = m.ok && m.summary && m.summary.raw_rel;
  if (!rel) {
    return;
  }
  var vp = document.getElementById('video-player');
  var vs = document.getElementById('video-section');
  vp.src = _BASE + '/api/demo-projects/' + _pid + '/file?rel=' + encodeURIComponent(rel);
  vp.onerror = function () {
    vs.style.display = 'none';
  };
  vs.style.display = 'block';
});
```

3b. Prose — replace the sentence that starts `The raw video path is fetched automatically by the widget` with:

```markdown
The widget learns the raw video's project-relative path from the parent (`gator:demo-summary`) and plays it through the project's file route (`/api/demo-projects/<id>/file`) using the project id — do NOT embed any file path in the widget HTML.
```

3c. Status line — directly after the line containing `id="btn-approve"` (the Approve button) add:

```html
<div class="status" id="merge-status"></div>
```

3d. Progress script — insert immediately above the editor's closing `</script>` (after the `approve()` function):

```js
// ── Merge progress ────────────────────────────────────────────────────────────
var _progressTimer = null;

function progressView(p, approvalId, waitedMs, sinceMs) {
  var mine = !!p && p.approval_id === approvalId && (p.updated_at || 0) * 1000 >= sinceMs;
  if (mine && p.state === 'done') {
    return { text: 'Done — your demo video is ready.', color: '#4ade80', stop: true, retry: false };
  }
  if (mine && p.state === 'failed') {
    return {
      text: 'Generation failed: ' + (p.error || p.message || 'unknown error'),
      color: '#f87171',
      stop: true,
      retry: true,
    };
  }
  if (mine && p.state === 'running') {
    return { text: p.message || 'Generating…', color: '#f97316', stop: false, retry: false };
  }
  if (waitedMs >= 120000) {
    return {
      text: 'Generation has not started yet. Check that the AI Gator agent is still working, or click Approve to retry.',
      color: '#f87171',
      stop: true,
      retry: true,
    };
  }
  return { text: 'Waiting for generation to start…', color: '#6b8db5', stop: false, retry: false };
}

function setMergeStatus(text, color) {
  var s = document.getElementById('merge-status');
  s.textContent = text || '';
  s.style.color = color || '#6b8db5';
}

function stopProgress() {
  if (_progressTimer) {
    clearInterval(_progressTimer);
    _progressTimer = null;
  }
}

var _progressApproval = null,
  _progressSince = 0;

function startProgress(approvalId, projectId) {
  stopProgress();
  _progressApproval = approvalId;
  _progressSince = Date.now();
  _progressTimer = setInterval(function () {
    requestDemoData('gator:demo-progress', projectId);
  }, 1500);
  requestDemoData('gator:demo-progress', projectId);
}

window.addEventListener('message', function (ev) {
  var m = ev.data || {};
  if (m.type === 'gator:demo-progress-result') {
    if (!_progressApproval || m.project_id !== _pid) {
      return;
    }
    var v = progressView(
      m.ok ? m.progress : { state: 'none' },
      _progressApproval,
      Date.now() - _progressSince,
      _progressSince,
    );
    setMergeStatus(v.text, v.color);
    if (v.stop) {
      stopProgress();
    }
    if (v.retry) {
      document.getElementById('btn-approve').disabled = false;
    }
    return;
  }
  if (m.type !== 'gator:narration-approval-result') {
    return;
  }
  var a = m.approval || m;
  if (m.ok && a.approval_id && _pid) {
    startProgress(a.approval_id, _pid);
  } else {
    stopProgress();
    setMergeStatus('', '');
  }
});
```

3e. Phase 4 — in the `subprocess.run([...])` list that starts with `sys.executable, str(skill_dir / "tts_pipeline.py")`, add these two entries as the last items, directly before the closing `],`:

```python
    "--progress-file", str(PROJECT_DIR / "work" / "logs" / "merge_progress.json"),
    "--approval-id", verdict["approval_id"],
```

Then add this sentence directly under that code block's lead-in text ("After running this code:" paragraph's preceding prose, or right below the code block):

```markdown
The pipeline writes its stage to `work/logs/merge_progress.json`; the narration editor polls it through `GET /api/demo-projects/<id>/progress` and shows "Generating speech N of M", "Merging audio and video", "Done", or the error text.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `node tests/narration_editor_widget.test.js`
Expected: `narration_editor_widget: PASS`

- [ ] **Step 5: Commit**

```bash
git add tests/narration_editor_widget.test.js web/skills/gator-demo-recorder/SKILL.md
git commit -m "feat: show merge progress and errors in the narration editor"
```

---

### Task 8a: Parent bridge for the demo widgets (`gator:demo-summary`, `gator:demo-progress`, `gator:demo-open-folder`)

Widgets must not call the backend themselves: a follow-up PR drops `allow-same-origin` from the widget sandbox and puts an endpoint allow-list on the parent bridge. This task adds exactly three named actions, each with fixed parameters, handled in the parent. The widget supplies only a project id (and, for folders, one of two literal targets); it never supplies a path. The sandbox attribute, `gatorWidgetCspHtml()` and the CSRF handling are not touched.

**Files:**

- Modify: `web/static/app.js` (helpers `GATOR_DEMO_ID_RE`, `GATOR_DEMO_TARGETS`, `gatorWidgetFrameForSource`, `gatorDemoBridge` next to the other `gatorWidget*` helpers; three `case` labels in the `window.addEventListener('message', …)` switch, directly after the `gator:recorder` case, and after SP3's `gator:pick-demo-folder` case if present)
- Test: `tests/demo_widget_bridge.test.js` (create)

**Interfaces:**

- Consumes: Task 6 `GET /api/demo-projects/{id}/summary` and `/progress`; Task 5 `POST /api/open-file` body `{path, reveal}`; the page's global `fetch` wrapper (attaches the CSRF token; the widget never sees it).
- Produces (message in → reply to `e.source` only):
  - `{type:'gator:demo-summary', project_id}` → `{type:'gator:demo-summary-result', project_id, ok, summary}` or `{…, ok:false, error}`
  - `{type:'gator:demo-progress', project_id}` → `{type:'gator:demo-progress-result', project_id, ok, progress}` or `{…, ok:false, error}`
  - `{type:'gator:demo-open-folder', project_id, target:'final'|'project'}` → `{type:'gator:demo-open-folder-result', project_id, ok, message}`. `final` reveals `summary.final` when it exists, otherwise opens `summary.final_dir`; `project` opens `summary.path`.
- Rules enforced by the handler: the message is ignored unless `e.source` is the `contentWindow` of a `.gator-widget-frame`; `project_id` must match `/^demo_\d[\w-]*$/`; `target` must be `final` or `project`; any other field in the message (including a widget-supplied `path`) is ignored.

- [ ] **Step 1: Write the failing test**

Create `tests/demo_widget_bridge.test.js`:

```js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function fn(name) {
  const m = source.match(
    new RegExp('(?:async )?function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}'),
  );
  if (!m) throw new Error(name + ' not found in app.js');
  return m[0];
}
function line(re) {
  const m = source.match(re);
  if (!m) throw new Error(String(re) + ' not found in app.js');
  return m[0];
}

// The three cases sit after gator:recorder and delegate to gatorDemoBridge.
{
  const rec = source.indexOf("case 'gator:recorder':");
  assert(rec > 0, 'gator:recorder case found');
  for (const t of ['gator:demo-summary', 'gator:demo-progress', 'gator:demo-open-folder']) {
    const at = source.indexOf("case '" + t + "':");
    assert(at > rec, t + ' case follows gator:recorder');
    assert(
      source.slice(at, at + 160).includes('gatorDemoBridge(d, e)'),
      t + ' delegates to gatorDemoBridge',
    );
  }
}

const frameWin = { name: 'widget' };
const otherWin = { name: 'other' };
const fetchCalls = [];
let routes = {};
const ctx = {
  document: { querySelectorAll: () => [{ contentWindow: frameWin }] },
  fetch: (url, opts) => {
    fetchCalls.push({ url, opts: opts ? JSON.parse(JSON.stringify(opts)) : null });
    const h = routes[url];
    if (!h) return Promise.reject(new Error('no route ' + url));
    return Promise.resolve(h(opts));
  },
};
const api = vm.runInNewContext(
  [
    line(/const GATOR_DEMO_ID_RE = [^\n]+;/),
    line(/const GATOR_DEMO_TARGETS = [^\n]+;/),
    fn('gatorWidgetFrameForSource'),
    fn('gatorDemoBridge'),
    '({ gatorWidgetFrameForSource, gatorDemoBridge })',
  ].join('\n'),
  ctx,
);

const ok = (body) => ({ ok: true, status: 200, json: () => Promise.resolve(body) });
const bad = (status) => ({ ok: false, status, json: () => Promise.resolve({}) });

async function run(d, src) {
  const sent = [];
  fetchCalls.length = 0;
  const e = { source: { postMessage: (m, o) => sent.push(JSON.parse(JSON.stringify({ m, o }))) } };
  if (src === 'frame') e.source = Object.assign(frameWin, { postMessage: e.source.postMessage });
  else if (src === 'other')
    e.source = Object.assign(otherWin, { postMessage: e.source.postMessage });
  else if (src === null) e.source = null;
  await api.gatorDemoBridge(d, e);
  return sent;
}

(async () => {
  const SUMMARY = {
    path: 'C:\\p',
    final_dir: 'C:\\p\\final',
    final: 'C:\\p\\final\\AI_Gator_Demo.mp4',
    final_rel: 'final/AI_Gator_Demo.mp4',
    raw_rel: 'source/raw.mp4',
    source_count: 3,
    work_bytes: 5,
  };

  // summary and progress
  routes = { '/api/demo-projects/demo_1/summary': () => ok(SUMMARY) };
  let sent = await run({ type: 'gator:demo-summary', project_id: 'demo_1' }, 'frame');
  assert.deepStrictEqual(sent, [
    {
      m: { type: 'gator:demo-summary-result', project_id: 'demo_1', ok: true, summary: SUMMARY },
      o: '*',
    },
  ]);

  routes = {
    '/api/demo-projects/demo_1/progress': () => ok({ state: 'running', approval_id: 'a1' }),
  };
  sent = await run({ type: 'gator:demo-progress', project_id: 'demo_1' }, 'frame');
  assert.deepStrictEqual(sent[0].m, {
    type: 'gator:demo-progress-result',
    project_id: 'demo_1',
    ok: true,
    progress: { state: 'running', approval_id: 'a1' },
  });

  routes = { '/api/demo-projects/demo_1/summary': () => bad(404) };
  sent = await run({ type: 'gator:demo-summary', project_id: 'demo_1' }, 'frame');
  assert.deepStrictEqual(sent[0].m, {
    type: 'gator:demo-summary-result',
    project_id: 'demo_1',
    ok: false,
    error: 'HTTP 404',
  });

  routes = {};
  sent = await run({ type: 'gator:demo-summary', project_id: 'demo_1' }, 'frame');
  assert.strictEqual(sent[0].m.ok, false, 'network failure becomes an error reply');

  // validation and origin
  routes = { '/api/demo-projects/demo_1/summary': () => ok(SUMMARY) };
  sent = await run({ type: 'gator:demo-summary', project_id: '../../etc' }, 'frame');
  assert.strictEqual(sent[0].m.ok, false);
  assert.strictEqual(fetchCalls.length, 0, 'invalid project id makes no request');
  sent = await run({ type: 'gator:demo-summary', project_id: 'demo_1' }, 'other');
  assert.strictEqual(sent.length, 0, 'message from a non-widget window is ignored');
  assert.strictEqual(fetchCalls.length, 0);
  sent = await run({ type: 'gator:demo-summary', project_id: 'demo_1' }, null);
  assert.strictEqual(fetchCalls.length, 0, 'message without a source is ignored');

  // open folder: the parent picks the path, the widget cannot
  const opens = [];
  routes = {
    '/api/demo-projects/demo_1/summary': () => ok(SUMMARY),
    '/api/open-file': (o) => {
      opens.push(JSON.parse(o.body));
      return ok({ ok: true });
    },
  };
  sent = await run(
    {
      type: 'gator:demo-open-folder',
      project_id: 'demo_1',
      target: 'final',
      path: 'C:\\Windows\\System32\\calc.exe',
    },
    'frame',
  );
  assert.deepStrictEqual(
    opens[0],
    { path: 'C:\\p\\final\\AI_Gator_Demo.mp4', reveal: true },
    'final reveals the final video; widget path ignored',
  );
  assert.deepStrictEqual(sent[0].m, {
    type: 'gator:demo-open-folder-result',
    project_id: 'demo_1',
    ok: true,
    message: '',
  });

  routes['/api/demo-projects/demo_1/summary'] = () =>
    ok(Object.assign({}, SUMMARY, { final: null }));
  await run({ type: 'gator:demo-open-folder', project_id: 'demo_1', target: 'final' }, 'frame');
  assert.deepStrictEqual(
    opens[1],
    { path: 'C:\\p\\final', reveal: false },
    'no final video: open the final folder',
  );

  routes['/api/demo-projects/demo_1/summary'] = () => ok(SUMMARY);
  await run({ type: 'gator:demo-open-folder', project_id: 'demo_1', target: 'project' }, 'frame');
  assert.deepStrictEqual(opens[2], { path: 'C:\\p', reveal: false });

  const before = opens.length;
  sent = await run(
    { type: 'gator:demo-open-folder', project_id: 'demo_1', target: 'C:\\Windows' },
    'frame',
  );
  assert.strictEqual(sent[0].m.ok, false);
  assert.strictEqual(fetchCalls.length, 0, 'unknown target makes no request');
  assert.strictEqual(opens.length, before);

  routes['/api/open-file'] = () => ok({ ok: false, message: 'That path no longer exists: C:\\p' });
  sent = await run(
    { type: 'gator:demo-open-folder', project_id: 'demo_1', target: 'project' },
    'frame',
  );
  assert.deepStrictEqual(sent[0].m, {
    type: 'gator:demo-open-folder-result',
    project_id: 'demo_1',
    ok: false,
    message: 'That path no longer exists: C:\\p',
  });

  console.log('demo_widget_bridge: PASS');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node tests/demo_widget_bridge.test.js`
Expected: FAIL with `AssertionError [ERR_ASSERTION]: gator:demo-summary case follows gator:recorder`.

- [ ] **Step 3: Implement the helpers and cases in `web/static/app.js`**

3a. Next to the other `gatorWidget*` helper functions (top level, not inside the message listener), add:

```js
const GATOR_DEMO_ID_RE = /^demo_\d[\w-]*$/;
const GATOR_DEMO_TARGETS = ['final', 'project'];

function gatorWidgetFrameForSource(source) {
  if (!source) return null;
  const frames = document.querySelectorAll('.gator-widget-frame');
  for (const f of frames) {
    if (f.contentWindow === source) return f;
  }
  return null;
}

async function gatorDemoBridge(d, e) {
  if (!gatorWidgetFrameForSource(e.source)) return;
  const id = String(d.project_id || '');
  const reply = (body) => {
    try {
      e.source.postMessage({ type: d.type + '-result', project_id: id, ...body }, '*');
    } catch (_) {}
  };
  if (!GATOR_DEMO_ID_RE.test(id)) {
    reply({ ok: false, error: 'invalid project id' });
    return;
  }
  const base = '/api/demo-projects/' + id;
  try {
    if (d.type === 'gator:demo-summary' || d.type === 'gator:demo-progress') {
      const isSummary = d.type === 'gator:demo-summary';
      const r = await fetch(base + (isSummary ? '/summary' : '/progress'));
      if (!r.ok) {
        reply({ ok: false, error: 'HTTP ' + r.status });
        return;
      }
      const data = await r.json();
      reply(isSummary ? { ok: true, summary: data } : { ok: true, progress: data });
      return;
    }
    if (!GATOR_DEMO_TARGETS.includes(d.target)) {
      reply({ ok: false, message: 'Unknown folder.' });
      return;
    }
    const sr = await fetch(base + '/summary');
    if (!sr.ok) {
      reply({ ok: false, message: 'Could not load the project (HTTP ' + sr.status + ').' });
      return;
    }
    const s = await sr.json();
    let target = s.path;
    let reveal = false;
    if (d.target === 'final') {
      target = s.final || s.final_dir;
      reveal = !!s.final;
    }
    const orsp = await fetch('/api/open-file', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: target, reveal }),
    });
    const od = await orsp.json();
    reply({
      ok: od.ok !== false,
      message: od.ok === false ? od.message || 'Could not open the folder.' : '',
    });
  } catch (err) {
    reply({ ok: false, error: String(err), message: 'Could not open the folder: ' + err });
  }
}
```

3b. In the `window.addEventListener('message', …)` switch, directly after the closing `}` of the `gator:recorder` case (and after SP3's `gator:pick-demo-folder` case if it is already there), add:

```js
    case 'gator:demo-summary':
    case 'gator:demo-progress':
    case 'gator:demo-open-folder':
      gatorDemoBridge(d, e);
      break;
```

Do not edit the iframe `sandbox` attribute, `gatorWidgetCspHtml()`, or any `__CSRF_TOKEN__` handling.

- [ ] **Step 4: Run the test to verify it passes**

Run: `node tests/demo_widget_bridge.test.js`
Expected: `demo_widget_bridge: PASS`

- [ ] **Step 5: Commit**

```bash
git add tests/demo_widget_bridge.test.js web/static/app.js
git commit -m "feat: parent bridge actions for the demo widget summary, progress and folders"
```

---

### Task 9: Delivery widget — Open final folder, Open project folder, summary line

Replaces the Phase 5 widget. "⬇ Download" is removed (it was redundant with the in-widget video and the file now lives in the project's `final/` folder). The widget makes no backend call of its own and never holds or sends a filesystem path. It asks the parent for the project summary (`gator:demo-summary`) and shows `Final: final/AI_Gator_Demo.mp4 · Sources: 3 · Working files: 280 MB`; the final video plays through the project file route as a `<video>` `src` (a resource load). The two folder buttons each send one named action (`gator:demo-open-folder` with `target` `final` or `project`); the parent resolves the path from the project summary and calls `POST /api/open-file` (exempt from the CSRF dependency today via `tests/csrf_route_baseline.txt`; this plan does not change that).

**Files:**

- Modify: `web/skills/gator-demo-recorder/SKILL.md` (Phase 5)
- Test: `tests/demo_ready_widget.test.js`

**Interfaces:**

- Consumes: Task 8a parent actions `gator:demo-summary` (reply `{type:'gator:demo-summary-result', project_id, ok, summary|error}`, `summary` = `{path, final_dir, final, final_rel, raw_rel, source_count, work_bytes}`) and `gator:demo-open-folder` (message `{type, project_id, target:'final'|'project'}`, reply `{type:'gator:demo-open-folder-result', project_id, ok, message}`); SP3 `GET /api/demo-projects/{id}/file?rel=` (video `src`); SP2's pinned `gator:send-message` form.
- Produces (inside the widget): `formatBytes(n)`, `summaryLine(s)`, `setOpenStatus(msg)`, `requestOpen(target)`, `openFinal()`, `openProject()`, `handleOpenResult(m)`; placeholder `PROJECT_ID_PLACEHOLDER` (the agent replaces it with `PROJECT_DIR.name`).

- [ ] **Step 1: Write the failing test**

Create `tests/demo_ready_widget.test.js`:

````js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const skill = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'skills', 'gator-demo-recorder', 'SKILL.md'),
  'utf8',
);
const blocks = [...skill.matchAll(/```html:widget\n([\s\S]*?)\n```/g)].map((m) => m[1]);
const widget = blocks.find((b) => b.includes('Demo Ready'));
assert.ok(widget, 'delivery widget found in SKILL.md');

function fn(name) {
  const m = widget.match(new RegExp('function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}'));
  if (!m) throw new Error(name + ' not found in delivery widget');
  return m[0];
}

// Markup
assert.ok(!/download/i.test(widget), 'no Download button, function or style');
assert.ok(!widget.includes('latest-output'), 'no latest-output');
assert.ok(!/fetch\(/.test(widget), 'widget makes no direct backend calls');
assert.ok(!widget.includes('/api/open-file'), 'widget never calls open-file itself');
assert.ok(
  !/window\.top|window\.parent|__CSRF_TOKEN__/.test(widget),
  'widget does not reach into the parent',
);
assert.ok(widget.includes("'gator:demo-summary'"), 'asks the parent for the summary');
assert.ok(widget.includes("'gator:demo-open-folder'"), 'asks the parent to open folders');
assert.ok(widget.includes('📁 Open final folder'), 'Open final folder button');
assert.ok(widget.includes('Open project folder'), 'Open project folder button');
assert.ok(widget.includes("var _PROJECT_ID = 'PROJECT_ID_PLACEHOLDER';"), 'project id placeholder');
assert.ok(
  skill.includes('replacing only `PROJECT_ID_PLACEHOLDER`'),
  'prose names the one placeholder',
);

// Pinned sends: every gator:send-message carries pin_skill and project_id.
{
  const idxs = [...widget.matchAll(/type:'gator:send-message'/g)].map((m) => m.index);
  assert.ok(idxs.length >= 2, 'editNarration and cleanup both send');
  for (const i of idxs) {
    const tail = widget.slice(i, i + 260);
    assert.ok(
      tail.includes("pin_skill:'gator-demo-recorder'"),
      'pin_skill present: ' + tail.slice(0, 80),
    );
    assert.ok(tail.includes('project_id:_PROJECT_ID'), 'project_id present: ' + tail.slice(0, 80));
  }
}

// Pure helpers
const code = [
  "var _pid='demo_1';",
  fn('formatBytes'),
  fn('summaryLine'),
  fn('setOpenStatus'),
  fn('requestOpen'),
  fn('openFinal'),
  fn('openProject'),
  fn('handleOpenResult'),
  '({ formatBytes, summaryLine, openFinal, openProject, handleOpenResult, setPid: function(p){ _pid=p; } })',
].join('\n');

const posted = [];
const statusEl = { textContent: '' };
const ctx = {
  parent: { postMessage: (m, origin) => posted.push(JSON.parse(JSON.stringify({ m, origin }))) },
  document: { getElementById: () => statusEl },
};
const api = vm.runInNewContext(code, ctx);

const MB = 1048576;
assert.strictEqual(api.formatBytes(0), '0 B');
assert.strictEqual(api.formatBytes(1023), '1023 B');
assert.strictEqual(api.formatBytes(1536), '2 KB');
assert.strictEqual(api.formatBytes(280 * MB), '280 MB');
assert.strictEqual(api.formatBytes(1.5 * 1024 * MB), '1.5 GB');
assert.strictEqual(
  api.summaryLine({ final_rel: 'final/AI_Gator_Demo.mp4', source_count: 3, work_bytes: 280 * MB }),
  'Final: final/AI_Gator_Demo.mp4 · Sources: 3 · Working files: 280 MB',
);
assert.strictEqual(
  api.summaryLine({ final_rel: null, source_count: 0, work_bytes: 0 }),
  'Final: none · Sources: 0 · Working files: 0 B',
);

// Each button posts one named action with fixed parameters and no path.
api.openFinal();
assert.deepStrictEqual(posted[0], {
  m: { type: 'gator:demo-open-folder', project_id: 'demo_1', target: 'final' },
  origin: '*',
});
api.openProject();
assert.deepStrictEqual(posted[1], {
  m: { type: 'gator:demo-open-folder', project_id: 'demo_1', target: 'project' },
  origin: '*',
});

// The parent's reply drives the status line; replies for other projects are ignored.
statusEl.textContent = '';
api.handleOpenResult({
  type: 'gator:demo-open-folder-result',
  project_id: 'demo_1',
  ok: false,
  message: 'That path no longer exists: C:\\p',
});
assert.strictEqual(statusEl.textContent, 'That path no longer exists: C:\\p');
api.handleOpenResult({ type: 'gator:demo-open-folder-result', project_id: 'demo_1', ok: false });
assert.strictEqual(statusEl.textContent, 'Could not open the folder.');
api.handleOpenResult({ type: 'gator:demo-open-folder-result', project_id: 'demo_1', ok: true });
assert.strictEqual(statusEl.textContent, '');
statusEl.textContent = 'keep';
api.handleOpenResult({
  type: 'gator:demo-open-folder-result',
  project_id: 'demo_9',
  ok: false,
  message: 'other',
});
assert.strictEqual(statusEl.textContent, 'keep', 'reply for another project is ignored');

// No project id: nothing is posted.
api.setPid('');
const before = posted.length;
api.openFinal();
api.openProject();
assert.strictEqual(posted.length, before, 'no request without a project id');

console.log('demo_ready_widget: PASS');
````

- [ ] **Step 2: Run the test to verify it fails**

Run: `node tests/demo_ready_widget.test.js`
Expected: FAIL with `AssertionError: no Download button, function or style`

- [ ] **Step 3: Replace the Phase 5 widget in `SKILL.md`**

3a. Replace the line `Then output this widget verbatim — no placeholders to replace:` with:

```markdown
Then output this widget verbatim, replacing only `PROJECT_ID_PLACEHOLDER` with the project id (`PROJECT_DIR.name`):
```

3b. Replace the entire second `html:widget` block (the one containing `🎬 Demo Ready`, from its opening fence through its closing fence) with the block below. Keep the line after it ("After showing the widget, report the file path and size in plain text for reference.") unchanged.

````markdown
```html:widget
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#111827;font-family:system-ui,sans-serif;padding:16px}
  .panel{background:#1a2332;border:1px solid #1e3a52;border-radius:12px;padding:16px;max-width:560px}
  h3{color:#4ade80;font-size:.9rem;font-weight:700;margin-bottom:10px}
  video{width:100%;border-radius:8px;background:#000;display:block;margin-bottom:10px}
  .meta{font-size:.72rem;color:#6b8db5;margin-bottom:6px;word-break:break-all}
  .status{font-size:.7rem;color:#f87171;margin-bottom:8px;min-height:14px}
  .actions{display:flex;gap:8px;flex-wrap:wrap}
  .btn{padding:8px 14px;border-radius:7px;border:none;font-size:.78rem;font-weight:700;cursor:pointer}
  .btn-open{background:rgba(74,222,128,.15);border:1px solid rgba(74,222,128,.35);color:#4ade80}
  .btn-open:hover{background:rgba(74,222,128,.25)}
  .btn-edit{background:rgba(96,165,250,.1);border:1px solid rgba(96,165,250,.3);color:#60a5fa}
  .btn-edit:hover{background:rgba(96,165,250,.2)}
  .btn-clean{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);color:#f87171}
  .btn-clean:hover{background:rgba(239,68,68,.2)}
</style>
</head>
<body>
<div class="panel">
  <h3>🎬 Demo Ready</h3>
  <video id="vp" controls preload="metadata"></video>
  <div class="meta" id="summary">Loading...</div>
  <div class="meta" id="duration"></div>
  <div class="status" id="open-status"></div>
  <div class="actions">
    <button class="btn btn-open" onclick="openFinal()">📁 Open final folder</button>
    <button class="btn btn-open" onclick="openProject()">Open project folder</button>
    <button class="btn btn-edit" onclick="editNarration()">✏️ Edit narration & regenerate</button>
    <button class="btn btn-clean" onclick="cleanup()">🗑 Delete intermediates</button>
  </div>
</div>
<script>
var _BASE=window._GATOR||'http://localhost:8003';
var _PROJECT_ID = 'PROJECT_ID_PLACEHOLDER';
var _pid=/^demo_\d/.test(_PROJECT_ID)?_PROJECT_ID:'';
var vp=document.getElementById('vp');

function formatBytes(n){
  n=Number(n)||0;
  if(n<1024){ return n+' B'; }
  if(n<1048576){ return Math.round(n/1024)+' KB'; }
  if(n<1073741824){ return Math.round(n/1048576)+' MB'; }
  return (n/1073741824).toFixed(1)+' GB';
}

function summaryLine(s){
  return 'Final: '+(s.final_rel||'none')+' · Sources: '+s.source_count+' · Working files: '+formatBytes(s.work_bytes);
}

function setOpenStatus(msg){
  document.getElementById('open-status').textContent=msg||'';
}

function requestOpen(target){
  if(!_pid){ return; }
  setOpenStatus('');
  parent.postMessage({type:'gator:demo-open-folder', project_id:_pid, target:target}, '*');
}

function openFinal(){
  requestOpen('final');
}

function openProject(){
  requestOpen('project');
}

function handleOpenResult(m){
  if(m.project_id!==_pid){ return; }
  setOpenStatus(m.ok===false ? (m.message||'Could not open the folder.') : '');
}

function applySummary(m){
  if(m.project_id!==_pid){ return; }
  if(!m.ok || !m.summary){
    document.getElementById('summary').textContent='Error loading: '+(m.error||'summary unavailable');
    return;
  }
  var s=m.summary;
  document.getElementById('summary').textContent=summaryLine(s);
  if(s.final_rel){
    vp.src=_BASE+'/api/demo-projects/'+_pid+'/file?rel='+encodeURIComponent(s.final_rel);
  } else {
    document.getElementById('duration').textContent='No final video was found in this project.';
  }
}

window.addEventListener('message', function(ev){
  var m=ev.data||{};
  if(m.type==='gator:demo-summary-result'){ applySummary(m); }
  else if(m.type==='gator:demo-open-folder-result'){ handleOpenResult(m); }
});

if(!_pid){
  document.getElementById('summary').textContent='Project not specified — cannot load the final video.';
} else {
  parent.postMessage({type:'gator:demo-summary', project_id:_pid}, '*');
}

vp.onloadedmetadata=function(){
  document.getElementById('duration').textContent='Duration: '+Math.round(vp.duration)+'s';
};
vp.onerror=function(){
  document.getElementById('duration').textContent='Could not load the final video.';
};

function editNarration(){
  parent.postMessage({type:'gator:send-message', pin_skill:'gator-demo-recorder', project_id:_PROJECT_ID,
    text:'NARRATION_REEDIT: Re-show the Phase 3 narration editor widget now.'},'*');
}
function cleanup(){
  parent.postMessage({type:'gator:send-message', pin_skill:'gator-demo-recorder', project_id:_PROJECT_ID,
    text:'Please delete the frames/ and tts_work/ intermediates for the current session.'},'*');
}
</script>
</body>
</html>
```
````

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node tests/demo_ready_widget.test.js && node tests/narration_editor_widget.test.js`
Expected: `demo_ready_widget: PASS` then `narration_editor_widget: PASS`

- [ ] **Step 5: Commit**

```bash
git add tests/demo_ready_widget.test.js web/skills/gator-demo-recorder/SKILL.md
git commit -m "feat: delivery widget opens the final and project folders and shows a summary"
```

---

## Out of scope for this plan: Intro option control (SP5)

SP5 owns the intro option and its fields. This plan adds no intro fields. When SP5's spec lands, its control is inserted into the Phase 3 editor between the `.voice-row` block and `<audio id="global-audio">` (a new `.intro-row`), and its values join the object returned by `segOut` / the approve payload through SP5's own contract. No code in Tasks 1–9 needs to change for that.

---

### Task 10: Full verification and manual browser check

**Files:** none modified.

- [ ] **Step 1: Run every new automated test**

Run:

```bash
node tests/widget_resize_scroll.test.js
node tests/widget_reveal_once.test.js
node tests/narration_editor_widget.test.js
node tests/demo_widget_bridge.test.js
node tests/demo_ready_widget.test.js
python -m pytest tests/test_tts_pipeline_pacing.py tests/test_tts_pipeline_progress.py tests/test_open_file_reveal.py tests/demo_project_state tests/test_csrf_route_inventory.py -v
```

Expected: five `PASS` lines from node, then all pytest tests pass.

- [ ] **Step 2: Confirm the CSRF baseline and the widget sandbox are untouched**

Run: `git diff --stat main -- tests/csrf_route_baseline.txt`
Expected: no output.

Run: `git diff main -- web/static/app.js | grep -nE "^[+-].*(sandbox=|allow-same-origin|gatorWidgetCspHtml|__CSRF_TOKEN__|window\.top)"`
Expected: no output (this plan adds no line that touches the sandbox attribute, the CSP helper, the CSRF token or `window.top`).

Run: `grep -nE "fetch\(|window\.top|window\.parent|__CSRF_TOKEN__" web/skills/gator-demo-recorder/SKILL.md`
Expected: any matches are outside the narration editor and delivery widgets (the Task 8 and Task 9 tests already assert those two contain no `fetch(`).

- [ ] **Step 3: Start the app**

Run: `uv run uvicorn web.app:app --host 127.0.0.1 --port 8003 --reload`
Open `http://127.0.0.1:8003` in a browser. Use a Demo Recorder run that reaches Phase 3 with at least 10 narration segments (record a short demo, or ask the agent: "Draft 12 narration segments for this recording and show the narration editor").

- [ ] **Step 4: Scroll and caret (Task 1)**

1. In the chat, scroll until segments 5 and 6 are in the middle of the visible area.
2. Click into segment 6's text box, type three new lines, then drag its resize handle taller and shorter.
3. Expected: the chat does not jump, segment 6 stays on screen, and the caret stays in the text box and keeps accepting typing.
4. Click "▶ Preview voice" and "▶▶ Play all"; expected: the status line changes without moving the scroll position.

- [ ] **Step 5: Reveal once (Task 2)**

1. Approve the narration and wait for the "Demo Ready" widget.
2. Click "✏️ Edit narration & regenerate".
3. Expected while the replacement editor streams in: the editor's title "✏️ Edit Narration Script" is at the top of the chat view, and the chat does not keep scrolling past it. When the response finishes there is no jump to the bottom.
4. Scroll up manually during a later stream; expected: no scroll is forced. Send a new message; expected: autoscroll behaves normally again.

- [ ] **Step 6: Pause after and pacing tips (Task 7)**

1. Hover the `?` next to "▶▶ Play all"; expected: the pacing-tips tooltip appears with no `[pause:…]` text. Press Tab to focus the `?`; expected: the tooltip also appears.
2. Set "Pause after (s)" on segment 2 to `1.5`, segment 3 to `-4` and segment 4 to `99`, then Approve.
3. Open `<project>/work/tts/segments.json`; expected: segment 2 has `"pause_after": 1.5`, segment 3 has `0`, segment 4 has `10`.
4. Re-open the editor via Edit narration; expected: the boxes show `1.5`, `0` and `10`.

- [ ] **Step 7: Merge progress (Task 8)**

1. Approve a narration. Expected, in order under the Approve button: "Waiting for generation to start…", "Generating speech N of M", "Merging audio and video", "Done — your demo video is ready."
2. Simulate a failure. With the editor open, run in the browser DevTools console (top frame):

```js
document
  .querySelector('.gator-widget-frame')
  .contentWindow.postMessage(
    { type: 'gator:narration-approval-result', ok: true, approval: { approval_id: 'a1' } },
    '*',
  );
```

Then immediately write the record (replace the path with the project folder):

```bash
python -c "import json,time,sys; open(sys.argv[1],'w').write(json.dumps({'approval_id':'a1','state':'failed','stage':'merge','step':2,'total':2,'message':'Generation failed','error':'ffmpeg exploded','updated_at':time.time()}))" "<project>/work/logs/merge_progress.json"
```

Expected: within 2 seconds the status turns red with "Generation failed: ffmpeg exploded" and the Approve button is enabled. 3. Post the same console message again without writing any file. Expected: "Waiting for generation to start…" for 2 minutes, then the red "Generation has not started yet…" message with Approve enabled. 4. The raw recording preview in the editor plays (the parent supplies the project-relative path through `gator:demo-summary`; the video loads through `/api/demo-projects/<id>/file`). 5. In DevTools → Network, filter on `demo-projects`; expected: the `/summary` and `/progress` requests come from the top page (the parent), none from the widget frame.

- [ ] **Step 8: Delivery widget (Tasks 5, 6, 9)**

1. Expected summary line under the video: `Final: final/AI_Gator_Demo.mp4 · Sources: <n> · Working files: <size>`, and no Download button.
2. Click "📁 Open final folder"; expected: Explorer opens the project's `final` folder with `AI_Gator_Demo.mp4` selected.
3. Click "Open project folder"; expected: Explorer opens the project folder.
4. Rename the project folder, click "Open project folder"; expected: the red status line shows "That path no longer exists: …". Rename it back.
5. In the top-frame DevTools console, post the action from the top window itself (not a widget frame):

```js
window.postMessage(
  { type: 'gator:demo-open-folder', project_id: 'demo_1', target: 'project' },
  '*',
);
```

Expected: nothing opens and no `/api/open-file` request appears in the Network tab, because the parent ignores messages whose source is not a widget frame.

---

## Self-Review

**Spec coverage**

| Spec item                                                                                           | Task                  |
| --------------------------------------------------------------------------------------------------- | --------------------- |
| Scroll and caret loss, fixed generically in the widget wrapper (issue #55 item 8, plan D1)          | 1, 2                  |
| Per-segment "Pause after" driving `pause_after`, pacing tips, no `[pause:…]`, no probe (item 9, D2) | 3, 7                  |
| Merge progress and error display in the widget (D3)                                                 | 4, 6, 8a, 8           |
| Delivery widget: Open final folder replaces Download, Open project folder, summary line             | 5, 6, 8a, 9           |
| Widgets make no backend calls; three named parent-handled actions, sandbox/CSP/CSRF untouched       | 8a, 8, 9, 10 (Step 2) |
| Intro option UI placeholder only                                                                    | Out-of-scope section  |
| Project-scoped widgets (`PROJECT_ID_PLACEHOLDER` / `_PROJECT_ID`, no `latest-output`)               | 8, 9                  |
| Pinned `gator:send-message` form from SP2                                                           | 9                     |

**Placeholder scan:** no TBD/TODO steps; every code step shows the code; the only deferred item is the SP5 intro control, which is explicitly outside this plan. `PROJECT_ID_PLACEHOLDER` is a runtime template token that SP2 already defines, not a plan placeholder.

**Type consistency:** `gatorWidgetScrollSnapshot` / `gatorWidgetScrollRestore` (Task 1) are used unchanged in Task 2's source text; `_pause_after` and `PAUSE_MAX` (Task 3) are reused as-is in Task 4's `main()`; `write_progress` keys `approval_id, state, stage, step, total, message, error, updated_at` (Task 4) match `read_progress` pass-through (Task 6) and `progressView` field reads (Task 8); `final_rel`, `source_count`, `work_bytes` (Task 6) match `summaryLine` / `applySummary` (Task 9) and `raw_rel` (Task 6) matches the editor's video preview (Task 8); `final`, `final_dir`, `path` (Task 6) are read only by `gatorDemoBridge` (Task 8a); `reveal` (Task 5) matches the `/api/open-file` body built in `gatorDemoBridge` (Task 8a); the message types `gator:demo-summary`, `gator:demo-progress`, `gator:demo-open-folder` and their `-result` replies (Task 8a) match the widget posts and listeners in Tasks 8 and 9 (`summary`, `progress`, `ok`, `message`, `error`, `project_id`); `segOut` / `pauseValue` / `pa<i>` (Task 7) are the only names Task 8 and the approve payload rely on.
