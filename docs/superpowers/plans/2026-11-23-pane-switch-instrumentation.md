# Pane Switch Instrumentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in timing instrumentation for a rail click so we can measure why pane switching feels choppy before changing any behaviour (PR 1 of 4 in `docs/superpowers/specs/2026-11-23-rail-pane-transitions-design.md`).

**Architecture:** A small pure module `shell/pane-trace.js` records timestamped marks for one rail click at a time and logs a one-line JSON summary. The renderer reports the click time through preload, and `shell/main.js` marks the show IPC, hide IPCs, each layout pass, and the target view's first frame. It is off unless `AIGATOR_PANE_TRACE=1`, so normal runs change nothing.

**Tech Stack:** Node `node:test` for tests, Electron main/preload IPC, plain browser JS in `web/static/app.js`.

## Global Constraints

- Branch: `feat/pane-switch-instrumentation`, stacked on `feat/browser-rail-pane`. One branch per PR. No push, no PR until the user says so.
- Commit messages carry no `Co-Authored-By` line (project rule in CLAUDE.md).
- Never call the project a POC. Use `aigator-fake-api-key` if a fake credential is ever needed.
- No new HTTP routes in this PR, so no `verify_csrf` work.
- Source files are LF (no CRLF). Do not change line endings.
- `web/static/app.js` startup consts must stay above the Init block; this PR adds no top-level consts there.
- Test in the real shell on a separate backend port and profile. Never touch the user's sessions on `:8006` and `:8000`, and never write the shared `config.json`.
- Behaviour with `AIGATOR_PANE_TRACE` unset must be identical to today.

---

### Task 1: Pure trace module

**Files:**

- Create: `shell/pane-trace.js`
- Test: `tests/pane-trace.test.js`

**Interfaces:**

- Produces: `createPaneTrace({ enabled, now, log, schedule, settleMs })` returning `{ enabled, click(app, t?), mark(event, detail?), finish() }`, and `summarize(rec)`. Event names used by later tasks: `'ipc-show'`, `'ipc-hide'` (detail `{ app, noop }`), `'layout'` (detail `{ active }`), `'frame'`.

- [ ] **Step 1: Write the failing tests**

Create `tests/pane-trace.test.js`:

```js
const test = require('node:test');
const assert = require('node:assert');
const { createPaneTrace, summarize } = require('../shell/pane-trace');

function makeTrace(extra = {}) {
  const clock = { t: 0 };
  const lines = [];
  const timers = [];
  const trace = createPaneTrace({
    enabled: true,
    now: () => clock.t,
    log: (line) => lines.push(line),
    schedule: (fn) => {
      timers.push(fn);
      return {};
    },
    ...extra,
  });
  return { trace, clock, lines, timers };
}

test('disabled trace records and logs nothing', () => {
  const lines = [];
  const trace = createPaneTrace({ enabled: false, log: (l) => lines.push(l) });
  trace.click('teams', 1000);
  trace.mark('frame');
  assert.strictEqual(trace.enabled, false);
  assert.strictEqual(lines.length, 0);
});

test('a click summarizes timings, passes and hides', () => {
  const { trace, clock, lines } = makeTrace();
  trace.click('teams', 1000);
  clock.t = 1004;
  trace.mark('ipc-hide', { app: 'outlook', noop: true });
  clock.t = 1006;
  trace.mark('ipc-show', { app: 'teams' });
  clock.t = 1010;
  trace.mark('layout', { active: 'teams' });
  clock.t = 1030;
  trace.mark('frame');
  assert.strictEqual(lines.length, 1);
  assert.ok(lines[0].startsWith('[pane-trace] '));
  assert.deepStrictEqual(JSON.parse(lines[0].slice('[pane-trace] '.length)), {
    app: 'teams',
    clickToShowIpcMs: 6,
    clickToLayoutMs: 10,
    clickToFrameMs: 30,
    layoutPasses: 1,
    nullActivePasses: 0,
    hideIpcs: 1,
    noopHideIpcs: 1,
  });
});

test('layout passes with no active app are counted', () => {
  const rec = {
    app: 'slack',
    t0: 0,
    marks: [
      { event: 'layout', t: 5, detail: { active: null } },
      { event: 'layout', t: 9, detail: { active: 'slack' } },
    ],
  };
  const s = summarize(rec);
  assert.strictEqual(s.layoutPasses, 2);
  assert.strictEqual(s.nullActivePasses, 1);
  assert.strictEqual(s.clickToFrameMs, null);
  assert.strictEqual(s.clickToShowIpcMs, null);
});

test('a new click flushes the unfinished previous click', () => {
  const { trace, clock, lines } = makeTrace();
  trace.click('calendar', 100);
  clock.t = 110;
  trace.mark('layout', { active: null });
  trace.click('teams', 200);
  assert.strictEqual(lines.length, 1);
  assert.strictEqual(JSON.parse(lines[0].slice(13)).app, 'calendar');
});

test('marks after the frame are ignored', () => {
  const { trace, clock, lines } = makeTrace();
  trace.click('teams', 0);
  clock.t = 5;
  trace.mark('frame');
  clock.t = 9;
  trace.mark('layout', { active: 'teams' });
  trace.finish();
  assert.strictEqual(lines.length, 1);
  assert.strictEqual(JSON.parse(lines[0].slice(13)).layoutPasses, 0);
});

test('the settle timer finishes a click that never got a frame', () => {
  const { trace, lines, timers } = makeTrace();
  trace.click('calendar', 0);
  assert.strictEqual(timers.length, 1);
  timers[0]();
  assert.strictEqual(lines.length, 1);
  timers[0]();
  assert.strictEqual(lines.length, 1);
});

test('a stale settle timer does not finish a newer click', () => {
  const { trace, lines, timers } = makeTrace();
  trace.click('calendar', 0);
  trace.click('teams', 10);
  assert.strictEqual(lines.length, 1);
  timers[0]();
  assert.strictEqual(lines.length, 1);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test tests/pane-trace.test.js`
Expected: FAIL with `Cannot find module '../shell/pane-trace'`.

- [ ] **Step 3: Write the module**

Create `shell/pane-trace.js`:

```js
'use strict';

function summarize(rec) {
  const first = (event) => rec.marks.find((m) => m.event === event);
  const since = (m) => (m ? m.t - rec.t0 : null);
  const layouts = rec.marks.filter((m) => m.event === 'layout');
  const hides = rec.marks.filter((m) => m.event === 'ipc-hide');
  return {
    app: rec.app,
    clickToShowIpcMs: since(first('ipc-show')),
    clickToLayoutMs: since(layouts[0]),
    clickToFrameMs: since(first('frame')),
    layoutPasses: layouts.length,
    nullActivePasses: layouts.filter((m) => m.detail.active == null).length,
    hideIpcs: hides.length,
    noopHideIpcs: hides.filter((m) => m.detail.noop).length,
  };
}

function createPaneTrace({
  enabled = false,
  now = Date.now,
  log = console.log,
  schedule = setTimeout,
  settleMs = 1500,
} = {}) {
  let current = null;

  function finish() {
    if (!current) return null;
    const summary = summarize(current);
    current = null;
    log('[pane-trace] ' + JSON.stringify(summary));
    return summary;
  }

  function click(app, t = now()) {
    if (!enabled) return;
    finish();
    const rec = { app, t0: t, marks: [] };
    current = rec;
    const handle = schedule(() => {
      if (current === rec) finish();
    }, settleMs);
    if (handle && handle.unref) handle.unref();
  }

  function mark(event, detail = {}) {
    if (!enabled || !current) return;
    current.marks.push({ event, t: now(), detail });
    if (event === 'frame') finish();
  }

  return { enabled, click, mark, finish };
}

module.exports = { createPaneTrace, summarize };
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test tests/pane-trace.test.js`
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add shell/pane-trace.js tests/pane-trace.test.js
git commit -m "feat(trace): add an opt-in timing recorder for rail pane switches"
```

---

### Task 2: Wire the trace into the shell and the rail click

**Files:**

- Modify: `shell/main.js` (require near line 14; `_layoutNow` near line 4267; `external-pane:show` near line 4530; `external-pane:hide` near line 4600; `slack-pane:hide` near line 4656)
- Modify: `shell/preload.js:7-8`
- Modify: `web/static/app.js:1610-1612` (`selectSkill`)
- Test: `tests/pane-trace.test.js` (add a wiring test)

**Interfaces:**

- Consumes: `createPaneTrace(...)` from Task 1 with `click`, `mark`, `enabled`.
- Produces: renderer API `window.gatorShell.paneTraceClick(app)`; IPC channel `pane-trace:click` `(app: string, t: number epoch ms)`.

- [ ] **Step 1: Write the failing wiring test**

Append to `tests/pane-trace.test.js`:

```js
const fs = require('node:fs');
const path = require('node:path');
const read = (rel) => fs.readFileSync(path.join(__dirname, '..', rel), 'utf8');

test('the trace is wired through main, preload and the rail click', () => {
  const main = read('shell/main.js');
  assert.match(
    main,
    /require\('\.\/pane-trace'\)\.createPaneTrace\(\{\s*enabled: process\.env\.AIGATOR_PANE_TRACE === '1'/,
  );
  assert.match(main, /ipcMain\.on\('pane-trace:click'/);
  assert.match(main, /paneTrace\.mark\('ipc-show'/);
  assert.match(main, /paneTrace\.mark\('ipc-hide'/);
  assert.match(main, /paneTrace\.mark\('layout'/);
  assert.match(main, /paneTrace\.mark\('frame'\)/);
  assert.match(
    read('shell/preload.js'),
    /paneTraceClick: \(app\) => ipcRenderer\.send\('pane-trace:click', app, Date\.now\(\)\)/,
  );
  assert.match(read('web/static/app.js'), /window\.gatorShell\?\.paneTraceClick\?\.\(id\)/);
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `node --test tests/pane-trace.test.js`
Expected: FAIL on the new wiring test (first assertion).

- [ ] **Step 3: Wire `shell/main.js`**

After the line `const addressInput = require('./address-input');` add:

```js
const paneTrace = require('./pane-trace').createPaneTrace({
  enabled: process.env.AIGATOR_PANE_TRACE === '1',
});
```

In `_layoutNow`, directly after `if (!win) return;` add:

```js
paneTrace.mark('layout', { active: activeExternalApp });
```

In `external-pane:show`, make the first line of the handler body:

```js
paneTrace.mark('ipc-show', { app: appName });
```

and replace the final `layout();\n  return true;\n});` of that handler with:

```js
  layout();
  if (paneTrace.enabled && view.webContents && !view.webContents.isDestroyed()) {
    view.webContents
      .executeJavaScript(
        'new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r(true))))',
      )
      .then(() => paneTrace.mark('frame'))
      .catch(() => {});
  }
  return true;
});
ipcMain.on('pane-trace:click', (_e, app, t) => {
  if (typeof app === 'string' && Number.isFinite(t)) paneTrace.click(app.slice(0, 64), t);
});
```

In `external-pane:hide`, make the first line of the handler body:

```js
paneTrace.mark('ipc-hide', { app: appName, noop: activeExternalApp !== appName });
```

In `slack-pane:hide`, make the first line of the handler body:

```js
paneTrace.mark('ipc-hide', { app: 'slack', noop: activeExternalApp !== 'slack' });
```

- [ ] **Step 4: Wire `shell/preload.js`**

Directly after `platform: process.platform,` add:

```js
  paneTraceClick: (app) => ipcRenderer.send('pane-trace:click', app, Date.now()),
```

- [ ] **Step 5: Wire the rail click in `web/static/app.js`**

In `selectSkill`, directly after `if (!skill) return;` add:

```js
window.gatorShell?.paneTraceClick?.(id);
```

- [ ] **Step 6: Run the tests and syntax checks**

Run: `node --test tests/pane-trace.test.js && node --check shell/main.js && node --check shell/preload.js && node --check web/static/app.js`
Expected: all tests PASS, no syntax errors.

- [ ] **Step 7: Check line endings and diff scope**

Run: `grep -c $'\r' shell/main.js shell/preload.js web/static/app.js shell/pane-trace.js && git diff --stat`
Expected: every count is `0`; the diff touches only `shell/main.js`, `shell/preload.js`, `web/static/app.js`, `tests/pane-trace.test.js`.

- [ ] **Step 8: Commit**

```bash
git add shell/main.js shell/preload.js web/static/app.js tests/pane-trace.test.js
git commit -m "feat(trace): record rail click, show/hide IPC, layout passes and first frame when AIGATOR_PANE_TRACE=1"
```

---

### Task 3: Measurement recipe and a real-shell baseline

**Files:**

- Create: `docs/pane-switch-tracing.md`

**Interfaces:**

- Consumes: the `[pane-trace]` log line from Tasks 1 and 2.

- [ ] **Step 1: Write the recipe**

Create `docs/pane-switch-tracing.md`:

````markdown
# Pane Switch Tracing

Measures what happens between a right-rail click and the new pane appearing.

## Turn it on

Set `AIGATOR_PANE_TRACE=1` before starting the shell. Use a separate backend port and Electron profile so your normal sessions are untouched. For screenshots of hidden panes, also pass `--disable-features=CalculateNativeWinOcclusion --disable-backgrounding-occluded-windows --disable-renderer-backgrounding`.

Each rail click prints one line to the shell's stdout:

```
[pane-trace] {"app":"teams","clickToShowIpcMs":9,"clickToLayoutMs":14,"clickToFrameMs":41,"layoutPasses":2,"nullActivePasses":1,"hideIpcs":14,"noopHideIpcs":13}
```

| Field                       | Meaning                                                                                                                                                                                             |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `clickToShowIpcMs`          | Click in the renderer until the shell receives `external-pane:show`.                                                                                                                                |
| `clickToLayoutMs`           | Click until the first layout pass.                                                                                                                                                                  |
| `clickToFrameMs`            | Click until the target view has rendered two animation frames. A proxy for "visible", not exact compositor presentation. Missing (`null`) for panes with no native view, such as Calendar and Code. |
| `layoutPasses`              | Layout passes caused by the click. More than 1 means intermediate states were painted.                                                                                                              |
| `nullActivePasses`          | Passes that ran with no active external app. For a native-to-native switch this is the full-width Gator flash. For Calendar and Code it is expected.                                                |
| `hideIpcs` / `noopHideIpcs` | Hide calls received, and how many were ignored because that app was not active.                                                                                                                     |

## What to look for

- `nullActivePasses` above 0 on a native-to-native switch: hide and show landed in different event-loop turns.
- `clickToFrameMs` over about 100ms: the click-to-visible path is slow. Compare `clickToShowIpcMs` (renderer work before the IPC) with the gap after it (shell and first paint).
- A large `noopHideIpcs`: confirms most hides do nothing.

## Deeper checks

- Start the shell with `--remote-debugging-port=9223`, open the Gator page in DevTools, and record the Performance panel over ten rail clicks. Look for long tasks right after the click.
- Screen-record at 60 fps or higher and count blank or full-width-Gator frames per switch.
````

- [ ] **Step 2: Run a real-shell baseline**

Start the backend on a spare port (not `:8006` or `:8000`) and the shell with a separate profile and `AIGATOR_PANE_TRACE=1`, following `dev-shell.ps1` for the launch flags and the `run` skill. Click through Teams, Outlook, Slack, Browser, Calendar, Code and back, ten or more switches, including a native-to-native switch from a cold start. Copy the `[pane-trace]` lines.
Expected: one line per click. Report the numbers to the user. Do not commit them.

- [ ] **Step 3: Confirm tracing off changes nothing**

Start the shell without `AIGATOR_PANE_TRACE`, click through three items.
Expected: no `[pane-trace]` output, and the rail and panes behave as before.

- [ ] **Step 4: Commit**

```bash
git add docs/pane-switch-tracing.md
git commit -m "docs(trace): add the pane switch tracing recipe"
```

---

## Self-Review

- **Spec coverage (PR 1):** click-to-paint timestamps (Tasks 1-2), layout pass count and no-active-app passes (`layoutPasses`, `nullActivePasses`), tracing recipe (Task 3), run in the real shell on a separate port and profile (Task 3). Changes to behaviour belong to PR 2 and are out of scope here.
- **Deviation from the spec:** first paint is measured as two animation frames in the target view, since Electron gives no paint event for a normal view. The recipe says so.
- **Placeholders:** none.
- **Type consistency:** `paneTrace.click(app, t)`, `mark(event, detail)`, `enabled` and the event names `ipc-show`, `ipc-hide`, `layout`, `frame` are used identically in the module, the tests and `main.js`.
