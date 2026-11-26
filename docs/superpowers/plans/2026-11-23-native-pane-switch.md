# Native Pane Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switching between native right-rail panes becomes one atomic main-process step (one IPC, one layout pass) so no intermediate full-width-Gator frame, no white flash, no stale async result from an earlier click.

**Architecture:** A pure `shell/pane-switch.js` holds the "last click wins" gate. `shell/main.js` gets a `pane:switch` IPC that reuses the existing show logic (extracted into `showNativePane`), applies the theme background to the incoming view, raises the toolbar above lazily created views, and skips redundant Gator-split scripts. `web/static/third-pane.js` calls `gatorShell.switchPane` for native targets and skips the per-type hides, behind one revert constant `USE_SWITCH_PANE`. Classic panes (Calendar, Code Agent, HITL forms) are not touched.

**Tech Stack:** Electron main process (CommonJS), renderer JS, `node:test`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-11-23-rail-pane-transitions-design.md`, section "PR 2 — Native switch". Baseline "before" numbers: `.superpowers/baselines/2026-11-23-pane-switch-baseline.txt`.
- Branch `feat/native-pane-switch`, stacked on `feat/pane-switch-instrumentation`. Commit locally only. No push, no PR.
- Behaviour with `AIGATOR_PANE_TRACE` unset must stay identical apart from the intended fixes. The `paneTrace` marks must keep working for the new path (`ipc-show`, `layout`, `frame`).
- IPC only. No new HTTP routes (no CSRF concern).
- Classic panes untouched. Keep the same-app home reload, Slack's `getLastSlackUrl()` home, GitHub's `GITHUB_URL` home, and the `_redirectIfNotShown` / `_redirectToSetup` flows.
- The old per-type hide+show path stays in the file and runs when `USE_SWITCH_PANE` is `false`.
- `web/static/app.js` is not touched. If it must be, top-level consts stay above the Init block.
- No `Co-Authored-By` lines in commits. Never call the project a POC. Fake credential, if any: `aigator-fake-api-key`.
- Files use LF line endings.
- Test command: `node --test tests/pane-switch.test.js`; full JS suite `node --test tests/` (known unrelated failure: `tests/demo_media_ui.test.js`, CRLF on this machine).

---

### Task 1: The switch gate (pure module)

**Files:**

- Create: `shell/pane-switch.js`
- Test: `tests/pane-switch.test.js`

**Interfaces:**

- Produces: `createSwitchGate()` returning `{ begin(seq): number|null, isCurrent(ticket): boolean, invalidate(): void }`. `begin` returns a ticket for a fresh, strictly increasing finite `seq`, or `null` for a stale or invalid one. `isCurrent(ticket)` is true only while no later `begin` or `invalidate` has happened.
- Also exports `PANE_BG = { dark: '#0a0f1a', light: '#f0f4f8' }` (the `--bg` values in `web/static/style.css`, lines 90 and 21051) and `paneBackground(theme)` returning `PANE_BG.light` for `'light'` and `PANE_BG.dark` otherwise.

- [ ] **Step 1: Write the failing tests**

```js
const test = require('node:test');
const assert = require('node:assert');
const { createSwitchGate, paneBackground, PANE_BG } = require('../shell/pane-switch');

test('begin accepts a fresh seq and returns a ticket', () => {
  const gate = createSwitchGate();
  const t = gate.begin(1);
  assert.notStrictEqual(t, null);
  assert.strictEqual(gate.isCurrent(t), true);
});

test('a later begin makes the earlier ticket stale (last click wins)', () => {
  const gate = createSwitchGate();
  const a = gate.begin(1);
  const b = gate.begin(2);
  assert.strictEqual(gate.isCurrent(a), false);
  assert.strictEqual(gate.isCurrent(b), true);
});

test('begin rejects a stale or repeated seq', () => {
  const gate = createSwitchGate();
  gate.begin(5);
  assert.strictEqual(gate.begin(5), null);
  assert.strictEqual(gate.begin(3), null);
});

test('begin rejects non-numeric seq', () => {
  const gate = createSwitchGate();
  assert.strictEqual(gate.begin('1'), null);
  assert.strictEqual(gate.begin(NaN), null);
  assert.strictEqual(gate.begin(undefined), null);
});

test('invalidate makes the in-flight ticket stale', () => {
  const gate = createSwitchGate();
  const t = gate.begin(1);
  gate.invalidate();
  assert.strictEqual(gate.isCurrent(t), false);
});

test('a rejected begin does not invalidate the current ticket', () => {
  const gate = createSwitchGate();
  const t = gate.begin(2);
  gate.begin(1);
  assert.strictEqual(gate.isCurrent(t), true);
});

test('paneBackground follows the theme', () => {
  assert.strictEqual(paneBackground('light'), PANE_BG.light);
  assert.strictEqual(paneBackground('dark'), PANE_BG.dark);
  assert.strictEqual(paneBackground(undefined), PANE_BG.dark);
});
```

- [ ] **Step 2: Run to verify failure**

Run: `node --test tests/pane-switch.test.js`
Expected: FAIL, `Cannot find module '../shell/pane-switch'`.

- [ ] **Step 3: Implement**

```js
'use strict';

const PANE_BG = { dark: '#0a0f1a', light: '#f0f4f8' };

function paneBackground(theme) {
  return theme === 'light' ? PANE_BG.light : PANE_BG.dark;
}

function createSwitchGate() {
  let lastSeq = 0;
  let version = 0;
  return {
    begin(seq) {
      if (typeof seq !== 'number' || !Number.isFinite(seq) || seq <= lastSeq) return null;
      lastSeq = seq;
      version += 1;
      return version;
    },
    isCurrent(ticket) {
      return ticket === version;
    },
    invalidate() {
      version += 1;
    },
  };
}

module.exports = { createSwitchGate, paneBackground, PANE_BG };
```

- [ ] **Step 4: Run to verify pass**

Run: `node --test tests/pane-switch.test.js`
Expected: 7 pass.

- [ ] **Step 5: Commit**

```bash
git add shell/pane-switch.js tests/pane-switch.test.js
git commit -m "feat(rail): add the pane switch gate so the last click wins"
```

---

### Task 2: Main process `pane:switch`, theme background, toolbar stacking, split cache

**Files:**

- Modify: `shell/main.js` (the `external-pane:show` handler near line 4534, `external-pane:hide` near 4617, `slack-pane:hide` near 4674, `_syncGatorSplit` near 4432, `shell:set-theme` near 5063, the `nativeTheme.on('updated')` block near 5070, `gatorView` creation near 1305)
- Modify: `shell/preload.js` (add `switchPane` next to `paneTraceClick`)
- Test: `tests/pane-switch.test.js` (append a source-grep wiring test, same style as `tests/pane-trace.test.js`)

**Interfaces:**

- Consumes: `createSwitchGate`, `paneBackground` from `./pane-switch`; existing `viewForApp`, `ensureAtlassianView`, `ensureGitHubView`, `createGenericPane`, `APP_HOME_URL`, `getLastSlackUrl`, `activeExternalApp`, `layout`, `paneTrace`, `toolbarView`, `_effectiveTheme`, `_genericPanes`.
- Produces:
  - Internal `async function showNativePane(appName, ticket)`: the body of today's `external-pane:show` handler from `let view = viewForApp(appName)` through `return true`, with two additions described below. `ticket` is `null` for the legacy handler.
  - `ipcMain.handle('pane:switch', async (_e, to, seq) => boolean)`.
  - Preload: `switchPane: (to, seq) => ipcRenderer.invoke('pane:switch', to, seq)`.

- [ ] **Step 1: Extract `showNativePane`**

Rename the handler body into `async function showNativePane(appName, ticket)` placed directly above the handler. `ipcMain.handle('external-pane:show', ...)` becomes:

```js
ipcMain.handle('external-pane:show', async (_e, appName) => {
  paneTrace.mark('ipc-show', { app: appName });
  return showNativePane(appName, null);
});
```

The `paneTrace.mark('ipc-show', ...)` line moves out of the body into the two handlers so that both paths mark it once. Behaviour must be byte-for-byte the same for the legacy path.

- [ ] **Step 2: Add the gate checks and the creation flag inside `showNativePane`**

At the top of the function body add `const preexisting = !!viewForApp(appName);` (before any `ensure*View` / `createGenericPane`). After the last `if (!view) return false;` add:

```js
if (ticket !== null && !_switchGate.isCurrent(ticket)) return false;
```

so that a later click (or a hide) that arrived while a Jira, Confluence, GitHub or generic view was being created discards this result before it changes `activeExternalApp`.

Right after that check, and before the `activeExternalApp === appName` branch, add:

```js
if (view.setBackgroundColor) view.setBackgroundColor(paneBackground(_effectiveTheme));
if (!preexisting) _raiseToolbarView();
```

At module level (near `viewForApp`) add:

```js
const { createSwitchGate, paneBackground } = require('./pane-switch');
const _switchGate = createSwitchGate();

function _raiseToolbarView() {
  if (!win || !toolbarView) return;
  try {
    win.contentView.addChildView(toolbarView);
  } catch {}
}
```

Re-adding an existing child moves it to the top of the stack, which is what keeps the toolbar's dropdown above a lazily created pane. Do this only on creation (it recomposites).

- [ ] **Step 3: Add the `pane:switch` handler**

Directly after the `external-pane:show` handler:

```js
ipcMain.handle('pane:switch', async (_e, to, seq) => {
  if (typeof to !== 'string' || !to) return false;
  paneTrace.mark('ipc-show', { app: to.slice(0, 64) });
  const ticket = _switchGate.begin(seq);
  if (ticket === null) return false;
  return showNativePane(to, ticket);
});
```

`showNativePane` already swaps `activeExternalApp` and calls `layout()` once; `_layoutNow` hides every other view in the same pass, so no per-type hides are needed.

- [ ] **Step 4: Hides invalidate an in-flight switch**

As the first line of both `external-pane:hide` and `slack-pane:hide` (after the existing `paneTrace.mark`) add `_switchGate.invalidate();`. Reason: a classic open (Calendar, Code) hides natives directly; a Jira or GitHub switch still creating its view must not land afterwards.

- [ ] **Step 5: Theme background on theme change**

Add:

```js
function _applyPaneBackgrounds() {
  const bg = paneBackground(_effectiveTheme);
  const views = [
    slackView,
    teamsView,
    outlookView,
    onedriveView,
    onenoteView,
    confluenceView,
    jiraView,
    githubView,
  ];
  for (const pane of Object.values(_genericPanes)) views.push(pane.view);
  for (const v of views) {
    try {
      if (v && v.setBackgroundColor) v.setBackgroundColor(bg);
    } catch {}
  }
}
```

Call it right after `_pushThemeToToolbar();` in both `shell:set-theme` and the `nativeTheme.on('updated')` branch (and, if `_effectiveTheme` is assigned at startup near line 254 before the views exist, nothing else is needed: `showNativePane` sets the colour on first show).

- [ ] **Step 6: Skip the Gator split script when unchanged**

```js
let _gatorSplitApplied = null;
function _syncGatorSplit(split) {
  if (!gatorView || !gatorView.webContents || gatorView.webContents.isDestroyed()) return;
  if (_gatorSplitApplied === split) return;
  _gatorSplitApplied = split;
  gatorView.webContents
    .executeJavaScript("document.body.classList.toggle('gator-split', " + split + ');')
    .catch(() => {});
}
```

Reset the cache when the Gator page reloads: where `gatorView` is created (around line 1305, next to `gatorView.setBackgroundColor('#0a0f1a')`) add `gatorView.webContents.on('did-start-navigation', (_e, _url, _isInPlace, isMainFrame) => { if (isMainFrame) _gatorSplitApplied = null; });`. Declare `_gatorSplitApplied` before first use (it is used by `_layoutNow`, which runs after startup; place the `let` above `_layoutNow`).

- [ ] **Step 7: Preload**

In `shell/preload.js`, directly after the `paneTraceClick` line add:

```js
  switchPane: (to, seq) => ipcRenderer.invoke('pane:switch', to, seq),
```

- [ ] **Step 8: Wiring test (append to `tests/pane-switch.test.js`)**

```js
const fs = require('node:fs');
const path = require('node:path');
const read = (rel) => fs.readFileSync(path.join(__dirname, '..', rel), 'utf8');

test('pane:switch is wired through main and preload', () => {
  const main = read('shell/main.js');
  assert.match(main, /require\('\.\/pane-switch'\)/);
  assert.match(main, /ipcMain\.handle\('pane:switch'/);
  assert.match(main, /async function showNativePane\(appName, ticket\)/);
  assert.match(
    main,
    /ipcMain\.handle\('external-pane:show'[\s\S]*?showNativePane\(appName, null\)/,
  );
  assert.match(main, /_switchGate\.invalidate\(\)/);
  assert.match(main, /_raiseToolbarView\(\)/);
  assert.match(main, /_applyPaneBackgrounds\(\)/);
  assert.match(main, /_gatorSplitApplied/);
  assert.match(
    read('shell/preload.js'),
    /switchPane: \(to, seq\) => ipcRenderer\.invoke\('pane:switch', to, seq\)/,
  );
});
```

- [ ] **Step 9: Run tests and check the shell still parses**

Run: `node --test tests/pane-switch.test.js tests/pane-trace.test.js`
Expected: all pass.
Run: `node --check shell/main.js && node --check shell/preload.js`
Expected: no output.

- [ ] **Step 10: Commit**

```bash
git add shell/main.js shell/preload.js tests/pane-switch.test.js
git commit -m "feat(rail): switch native panes in one IPC, theme the view background, keep the toolbar on top"
```

---

### Task 3: Renderer uses `switchPane` for native targets (behind `USE_SWITCH_PANE`)

**Files:**

- Modify: `web/static/third-pane.js` (`_openThirdPaneImpl` at about line 2402, the native branches through about line 2955, `_hideAllNativePanes` at about line 2357, `_nativeSlack.activate` at about line 97)
- Test: `tests/pane-switch.test.js` (append) and any existing test that source-greps `third-pane.js` for the calls you change (run `grep -rl "third-pane.js" tests/` and keep them passing)

**Interfaces:**

- Consumes: `window.gatorShell.switchPane(to, seq)` from Task 2.
- Produces, at module top level of `third-pane.js`:

```js
// Internal revert switch: false restores the per-type hide+show calls.
const USE_SWITCH_PANE = true;
let _paneSwitchSeq = 0;

// Shell app id this skill type opens natively, or null for classic panes / browser mode.
function _nativeShellAppId(type) {
  const shell = window.gatorShell;
  if (!shell || !shell.isShell || typeof shell.switchPane !== 'function') return null;
  switch (type) {
    case 'teams':
      return 'teams';
    case 'slack':
      return _nativeSlack._inShell() ? 'slack' : null;
    case 'email':
      return _outlookNativeEnabled() ? 'outlook' : null;
    case 'onenote':
      return _onenoteNativeEnabled() ? 'onenote' : null;
    case 'onedrive':
      return _onedriveNativeEnabled() ? 'onedrive' : null;
    case 'jira':
      return _jiraNativeEnabled() ? 'jira' : null;
    case 'confluence':
      return _confluenceNativeEnabled() ? 'confluence' : null;
    case 'github':
      return _githubNativeEnabled() ? 'github' : null;
    default:
      return typeof SKILL_MAP !== 'undefined' && _isShellWebPaneSkill(SKILL_MAP[type])
        ? type
        : null;
  }
}

function _switchNativePane(appId) {
  return window.gatorShell.switchPane(appId, ++_paneSwitchSeq);
}
```

Place the `const`/`let`/functions above `_openThirdPaneImpl` and make sure everything they reference (`_nativeSlack`, the `*NativeEnabled` helpers, `_isShellWebPaneSkill`) is defined at call time (they are function declarations or top-level objects used only inside the function, so ordering is safe; verify `_nativeSlack` is a top-level `const` defined earlier in the file than any call).

- [ ] **Step 1: Failing wiring test**

```js
test('third-pane switches native panes through switchPane behind USE_SWITCH_PANE', () => {
  const tp = read('web/static/third-pane.js');
  assert.match(tp, /const USE_SWITCH_PANE = true;/);
  assert.match(tp, /function _nativeShellAppId\(type\)/);
  assert.match(tp, /window\.gatorShell\.switchPane\(appId, \+\+_paneSwitchSeq\)/);
  assert.match(tp, /const _switchTo = USE_SWITCH_PANE \? _nativeShellAppId\(type\) : null;/);
});
```

Run: `node --test tests/pane-switch.test.js` — expect FAIL.

- [ ] **Step 2: Add the helpers above `_openThirdPaneImpl`** (code above).

- [ ] **Step 3: Decide the target once per open**

At the top of `_openThirdPaneImpl`, after `const _prevType = tpState.type;`:

```js
const _switchTo = USE_SWITCH_PANE ? _nativeShellAppId(type) : null;
```

- [ ] **Step 4: Skip the redundant hides when switching**

When `_switchTo` is non-null, the single `pane:switch` replaces every hide because main hides all other views in the same layout pass. Edit these sites so the hide calls run only when `!_switchTo`:

1. The outgoing-pane block at the top of the function (the `tpState.type && tpState.type !== type` block from about line 2410): keep `_nativeSlack.deactivate()` out when `_switchTo` (it calls `hideSlack`); keep `_shellDrag.unmount()` and the `tpState.selectedId = null; tpState.focusedId = null;` lines. Pattern for each of the `hideTeams()` / `hideOutlook()` / `hideOneDrive()` / `hideOneNote()` / `hideConfluence()` / `hideJira()` / `hideGitHub()` / `hideCustomApp()` calls: `if (!_switchTo) window.gatorShell.hideX();` and leave `_shellDrag.unmount()` as is.
2. The belt-and-suspenders block (about line 2508): wrap the whole body in `if (!_switchTo) { ... }`.
3. Per-branch hides before each show: Teams (`if (_prevType === 'slack') window.gatorShell.hideSlack();`), Outlook, OneNote, OneDrive, Jira, Confluence, Slack (`hideTeams`), GitHub (inside the `.then`), and `_hideAllNativePanes(type)` in the custom-app branch: wrap each in `if (!_switchTo)`.

Do not touch: the `pane.classList.remove('is-open')` / `add('hidden')` blocks, `_stopThreadPolling()`, `_stopChatListPolling()`, `_shellDrag.mount()`, `_dividerBtns.show()`, the `return`s, the classic branches, or anything for `code_agent`/Calendar.

- [ ] **Step 5: Replace each show with the switch**

In each native branch, replace the show call by a conditional, keeping the surrounding logic:

- Teams: `window.gatorShell.showTeams();` → `if (_switchTo) _switchNativePane(_switchTo); else window.gatorShell.showTeams();`
- Outlook, OneNote, OneDrive: same pattern with `showOutlook()`, `showOneNote()`, `showOneDrive()`.
- Jira and Confluence: `_redirectIfNotShown('jira', _switchTo ? _switchNativePane(_switchTo) : window.gatorShell.showJira());` (same for confluence). A superseded switch returns `false`, which would trigger `_redirectToSetup`: to avoid that, make `_redirectIfNotShown` ignore a result of `false` coming from a superseded switch by having `pane:switch` return `'superseded'` for stale tickets instead of `false` (see Step 6), so only a real `false` (no view) redirects.
- GitHub: `window.gatorShell.showGitHub().then(` → `(_switchTo ? _switchNativePane(_switchTo) : window.gatorShell.showGitHub()).then(` and treat `'superseded'` as neither shown nor an error: `if (shown === 'superseded') return;` at the top of the `.then` success callback.
- Slack: `_nativeSlack.activate()` calls `window.gatorShell.showSlack()` internally (line ~102). Add an optional argument: in `_openThirdPaneImpl`'s Slack branch call `_nativeSlack.activate(_switchTo)` and in `activate(switchTo)` replace the show line with `if (switchTo) window.gatorShell.switchPane(switchTo, ++_paneSwitchSeq); else window.gatorShell.showSlack();`. `_paneSwitchSeq` is a module-level `let`, so it is shared. Keep the context listener and drag handle calls.
- Custom apps / Google / Browser: `window.gatorShell.showCustomApp(type);` → `if (_switchTo) _switchNativePane(_switchTo); else window.gatorShell.showCustomApp(type);`

- [ ] **Step 6: Make main return `'superseded'` for stale switches**

In `shell/main.js` (Task 2 code) change the stale outcomes of the `pane:switch` path: in `pane:switch` return `'superseded'` when `begin` returns `null`, and in `showNativePane` return `'superseded'` (not `false`) when `ticket !== null && !_switchGate.isCurrent(ticket)`. Update the test in Task 2's wiring block only if it asserts the literal `return false` there (it does not). Add to the Task 1/2 test file: `assert.match(main, /'superseded'/);`.

- [ ] **Step 7: Check and run**

Run: `node --test tests/pane-switch.test.js` — pass.
Run: `node --check web/static/third-pane.js` — no output.
Run: `grep -rl "third-pane.js" tests/` and run each listed test with `node --test <file>`; they must pass unchanged. If one asserts a hide call that you now guard, adjust the assertion minimally to still prove the legacy path exists.
Run the full suite: `node --test tests/` — only `tests/demo_media_ui.test.js` may fail.

- [ ] **Step 8: Commit**

```bash
git add web/static/third-pane.js shell/main.js tests/pane-switch.test.js
git commit -m "feat(rail): open native panes with one switchPane call behind USE_SWITCH_PANE"
```

---

### Task 4: Real-shell verification (manual, not code)

Run by the controller through a fork; nothing is committed.

- [ ] **Step 1: Launch** the shell on backend port 8012 and CDP 9233 (not 8006, 8000, 8002, 9223), a temp profile, `AIGATOR_PANE_TRACE=1`, flags `--disable-features=CalculateNativeWinOcclusion --disable-backgrounding-occluded-windows --disable-renderer-backgrounding`. Never write the shared `config.json`.
- [ ] **Step 2: Click** through the same sequence as the baseline (Outlook, Teams, Slack, OneDrive, Jira, Confluence, Outlook, Slack, Teams, Calendar, Outlook, Browser, Slack, Outlook) plus 3 rapid back-to-back native clicks. Save the `[pane-trace]` lines to `.superpowers/baselines/2026-11-23-pane-switch-after.txt`.
- [ ] **Step 3: Compare** with the baseline: `nullActivePasses` should be 0 for every native-to-native row, `layoutPasses` should be 1, `hideIpcs` should drop to 0 for native-to-native. Rapid clicks end on the last target. Also confirm with a screenshot (dark and light theme) that a cold view shows the theme surface, not white, and that the toolbar dropdown opens above a freshly created pane.
- [ ] **Step 4: Revert check:** set `USE_SWITCH_PANE = false` locally (uncommitted), relaunch, confirm the old per-type calls work, then restore the constant.
- [ ] **Step 5: Trace off:** run without the env var and confirm no `[pane-trace]` output and working switches.
