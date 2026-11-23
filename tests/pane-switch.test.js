const test = require('node:test');
const assert = require('node:assert');
const {
  createSwitchGate,
  paneBackground,
  applyPaneBackground,
  PANE_BG,
  PANE_BG_SETTLED,
} = require('../shell/pane-switch');

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

const fs = require('node:fs');
const path = require('node:path');
const read = (rel) => fs.readFileSync(path.join(__dirname, '..', rel), 'utf8');

test('pane:switch is wired through main and preload', () => {
  const main = read('shell/main.js');
  assert.match(main, /require\('\.\/pane-switch'\)/);
  assert.match(main, /ipcMain\.handle\('pane:switch'/);
  assert.match(main, /async function showNativePane\(appName, ticket\)/);
  assert.match(main, /ipcMain\.handle\('external-pane:show'[\s\S]*?showNativePane\(appName, null\)/);
  assert.match(main, /_switchGate\.invalidate\(\)/);
  assert.match(main, /if \(!preexisting\) _raiseToolbarView\(\);\s*if \(ticket !== null && !_switchGate\.isCurrent\(ticket\)\) \{[^}]*?if \(!preexisting\) layout\(\);\s*return 'superseded';/);
  assert.match(main, /_pushThemeToToolbar\(\);\s*_applyPaneBackgrounds\(\);/);
  assert.strictEqual(main.match(/_pushThemeToToolbar\(\);\s*_applyPaneBackgrounds\(\);/g).length, 2);
  assert.match(main, /_gatorSplitApplied/);
  assert.match(read('shell/preload.js'), /switchPane: \(to, seq\) => ipcRenderer\.invoke\('pane:switch', to, seq\)/);
});

test('stale switches resolve to superseded, not false', () => {
  const main = read('shell/main.js');
  assert.match(main, /if \(ticket === null\) return 'superseded';/);
  assert.match(main, /'superseded'/);
});

test('third-pane switches native panes through switchPane behind USE_SWITCH_PANE', () => {
  const tp = read('web/static/third-pane.js');
  assert.match(tp, /const USE_SWITCH_PANE = true;/);
  assert.match(tp, /function _nativeShellAppId\(type\)/);
  assert.match(tp, /window\.gatorShell\.switchPane\(appId, _nextPaneSwitchSeq\(\)\)/);
  assert.match(tp, /const _switchTo = USE_SWITCH_PANE \? _nativeShellAppId\(type\) : null;/);
});

test('reset lets the renderer start its seq over after a reload', () => {
  const gate = createSwitchGate();
  gate.begin(7);
  gate.reset();
  assert.notStrictEqual(gate.begin(1), null);
});

test('reset makes the previous ticket stale', () => {
  const gate = createSwitchGate();
  const t = gate.begin(1);
  gate.reset();
  assert.strictEqual(gate.isCurrent(t), false);
});

test('main resets the switch gate when Gator navigates its main frame', () => {
  const main = read('shell/main.js');
  assert.match(
    main,
    /'did-start-navigation'[\s\S]*?if \(isMainFrame\) \{\s*_gatorSplitApplied = null;[\s\S]*?_switchGate\.reset\(\);/,
  );
});

test('the shared seq helper is clock-seeded and used by both switch call sites', () => {
  const tp = read('web/static/third-pane.js');
  assert.match(tp, /_paneSwitchSeq = Math\.max\(_paneSwitchSeq \+ 1, Date\.now\(\)\);/);
  assert.match(tp, /switchPane\(switchTo, _nextPaneSwitchSeq\(\)\)/);
  assert.doesNotMatch(tp, /\+\+_paneSwitchSeq/);
});

test('a target view that cannot be created clears the previous pane for a current switch', () => {
  const main = read('shell/main.js');
  assert.match(
    main,
    /if \(!view\) \{[^}]*?if \(ticket !== null && _switchGate\.isCurrent\(ticket\)\) \{\s*activeExternalApp = null;\s*layout\(\);\s*\}\s*return false;/,
  );
});

test('a hide arriving during an in-flight switch leaves nothing native visible', () => {
  const main = read('shell/main.js');
  assert.match(main, /let _pendingSwitchApp = null;/);
  assert.match(main, /_pendingSwitchTicket === ticket/);
  const hides = main.match(/_switchGate\.invalidate\(\);\s*if \(_pendingSwitchApp !== null\) \{\s*[^}]*activeExternalApp = null;\s*layout\(\);/g);
  assert.strictEqual(hides.length, 2);
  assert.match(main, /ipcMain\.handle\('slack-pane:hide'[\s\S]*?_pendingSwitchApp/);
  assert.match(main, /ipcMain\.handle\('external-pane:hide'[\s\S]*?_pendingSwitchApp/);
});

test('a legacy show invalidates any in-flight switch', () => {
  const main = read('shell/main.js');
  assert.match(main, /ipcMain\.handle\('external-pane:show', async \(_e, appName\) => \{[\s\S]*?_switchGate\.invalidate\(\);/);
});

test('the gate only resets on a real (not in-place) main-frame navigation', () => {
  const main = read('shell/main.js');
  assert.match(main, /if \(!isInPlace\) _switchGate\.reset\(\);/);
});

test('runtime-created generic panes raise the toolbar above themselves', () => {
  const main = read('shell/main.js');
  assert.match(main, /_attachToolbarListeners\(view, id\);\s*_raiseToolbarView\(\);/);
});

test('begin rejects Infinity and negative seq', () => {
  const gate = createSwitchGate();
  assert.strictEqual(gate.begin(Infinity), null);
  assert.strictEqual(gate.begin(-Infinity), null);
  assert.strictEqual(gate.begin(-1), null);
});

function fakeView({ loading = false, url = '' } = {}) {
  const calls = [];
  const listeners = {};
  let destroyed = false;
  const view = {
    calls,
    listeners,
    destroy: () => {
      destroyed = true;
    },
    setBackgroundColor: (c) => {
      if (destroyed) throw new Error('Object has been destroyed');
      calls.push(c);
    },
    webContents: {
      isDestroyed: () => destroyed,
      isLoading: () => loading,
      getURL: () => url,
      once: (ev, fn) => {
        listeners[ev] = (listeners[ev] || []).concat(fn);
      },
    },
  };
  return view;
}

test('a new view gets the themed colour until its first load finishes, then white', () => {
  const states = new WeakMap();
  const v = fakeView({ loading: true, url: 'https://example.com/' });
  applyPaneBackground(v, 'dark', states);
  assert.deepStrictEqual(v.calls, [PANE_BG.dark]);
  v.listeners['did-stop-loading'].forEach((fn) => fn());
  assert.deepStrictEqual(v.calls, [PANE_BG.dark, PANE_BG_SETTLED]);
});

test('the first-load listener is registered once per view, however often it is re-applied', () => {
  const states = new WeakMap();
  const v = fakeView({ loading: true, url: 'https://example.com/' });
  applyPaneBackground(v, 'dark', states);
  applyPaneBackground(v, 'light', states);
  applyPaneBackground(v, 'dark', states);
  assert.strictEqual(v.listeners['did-stop-loading'].length, 1);
  // A theme change before the first load finishes still re-themes the unsettled view.
  assert.deepStrictEqual(v.calls, [PANE_BG.dark, PANE_BG.light, PANE_BG.dark]);
});

test('a settled view is never re-themed', () => {
  const states = new WeakMap();
  const v = fakeView({ loading: true, url: 'https://example.com/' });
  applyPaneBackground(v, 'dark', states);
  v.listeners['did-stop-loading'].forEach((fn) => fn());
  v.calls.length = 0;
  applyPaneBackground(v, 'light', states);
  assert.deepStrictEqual(v.calls, []);
});

test('a view that finished loading before its first show is settled to white at once', () => {
  const states = new WeakMap();
  const v = fakeView({ loading: false, url: 'https://example.com/' });
  applyPaneBackground(v, 'dark', states);
  assert.deepStrictEqual(v.calls, [PANE_BG_SETTLED]);
  assert.strictEqual(v.listeners['did-stop-loading'], undefined);
  applyPaneBackground(v, 'light', states);
  assert.deepStrictEqual(v.calls, [PANE_BG_SETTLED]);
});

test('a view that never started loading is themed and waits for its first load', () => {
  const states = new WeakMap();
  const v = fakeView({ loading: false, url: '' });
  applyPaneBackground(v, 'light', states);
  assert.deepStrictEqual(v.calls, [PANE_BG.light]);
  assert.strictEqual(v.listeners['did-stop-loading'].length, 1);
});

test('a view destroyed before its first load finishes does not throw', () => {
  const states = new WeakMap();
  const v = fakeView({ loading: true, url: 'https://example.com/' });
  applyPaneBackground(v, 'dark', states);
  v.destroy();
  assert.doesNotThrow(() => v.listeners['did-stop-loading'].forEach((fn) => fn()));
  assert.doesNotThrow(() => applyPaneBackground(v, 'dark', states));
  assert.doesNotThrow(() => applyPaneBackground(null, 'dark', states));
});

test('main applies pane backgrounds through the settle helper only', () => {
  const main = read('shell/main.js');
  assert.match(main, /const _paneBgStates = new WeakMap\(\);/);
  assert.match(main, /_applyPaneBackground\(view\);\s*if \(activeExternalApp === appName/);
  assert.match(main, /for \(const v of views\) _applyPaneBackground\(v\);/);
  assert.doesNotMatch(main, /view\.setBackgroundColor\(paneBackground/);
  assert.doesNotMatch(main, /v\.setBackgroundColor\(bg\)/);
});

test('pane:switch rejects only non-strings and empty or over-long names', () => {
  const main = read('shell/main.js');
  assert.match(main, /if \(typeof to !== 'string' \|\| !to \|\| to\.length > 200\) return false;/);
  assert.doesNotMatch(main, /\[a-z0-9_-\]\{1,200\}/);
});

test('USE_SWITCH_PANE documents that main-side behaviour stays on', () => {
  const tp = read('web/static/third-pane.js');
  assert.match(tp, /\/\/ Internal revert switch: only restores the renderer's per-type hide\/show calls;/);
});

function loadNativeShellAppId(env) {
  const vm = require('node:vm');
  const tp = read('web/static/third-pane.js');
  const m = tp.match(/function _nativeShellAppId\(type\) \{[\s\S]*?\n\}\n/);
  assert.ok(m, '_nativeShellAppId not found');
  const sandbox = {
    window: { gatorShell: env.shell },
    _nativeSlack: { _inShell: () => env.slackInShell !== false },
    _outlookNativeEnabled: () => env.native !== false,
    _onenoteNativeEnabled: () => env.native !== false,
    _onedriveNativeEnabled: () => env.native !== false,
    _jiraNativeEnabled: () => env.native !== false,
    _confluenceNativeEnabled: () => env.native !== false,
    _githubNativeEnabled: () => env.native !== false,
    SKILL_MAP: {
      calendar: { id: 'calendar' },
      code_agent: { id: 'code_agent' },
      'my-app': { _customApp: true },
      'g-gmail': { _googleService: true },
      browser: { _browserPane: true },
    },
    _isShellWebPaneSkill: (skill) =>
      !!(skill && (skill._customApp || skill._googleService || skill._browserPane)),
  };
  vm.createContext(sandbox);
  vm.runInContext(`${m[0]}\nthis.fn = _nativeShellAppId;`, sandbox);
  return sandbox.fn;
}

const IN_SHELL = { isShell: true, switchPane: () => {} };

test('_nativeShellAppId maps skill types to shell app ids when native', () => {
  const fn = loadNativeShellAppId({ shell: IN_SHELL });
  assert.strictEqual(fn('teams'), 'teams');
  assert.strictEqual(fn('slack'), 'slack');
  assert.strictEqual(fn('email'), 'outlook');
  for (const t of ['onenote', 'onedrive', 'jira', 'confluence', 'github']) {
    assert.strictEqual(fn(t), t);
  }
  for (const t of ['my-app', 'g-gmail', 'browser']) assert.strictEqual(fn(t), t);
});

test('_nativeShellAppId is null for classic panes and unknown types', () => {
  const fn = loadNativeShellAppId({ shell: IN_SHELL });
  assert.strictEqual(fn('calendar'), null);
  assert.strictEqual(fn('code_agent'), null);
  assert.strictEqual(fn('nope'), null);
});

test('_nativeShellAppId is null for classic-mode native apps', () => {
  const fn = loadNativeShellAppId({ shell: IN_SHELL, native: false, slackInShell: false });
  for (const t of ['slack', 'email', 'onenote', 'onedrive', 'jira', 'confluence', 'github']) {
    assert.strictEqual(fn(t), null, t);
  }
  assert.strictEqual(fn('teams'), 'teams');
});

test('_nativeShellAppId is null outside the shell or without switchPane', () => {
  for (const shell of [undefined, { isShell: false, switchPane() {} }, { isShell: true }]) {
    const fn = loadNativeShellAppId({ shell });
    assert.strictEqual(fn('teams'), null);
    assert.strictEqual(fn('my-app'), null);
  }
});

test('the toolbar is raised once after the startup panes are created', () => {
  const main = read('shell/main.js');
  assert.match(main, /githubView\.setBounds\(\{ x: 1599, y: 0, width: 1, height: 900 \}\);\s*\}\s*_raiseToolbarView\(\);/);
});

function loadPaneSwitchHandler() {
  const vm = require('node:vm');
  const main = read('shell/main.js');
  const m = main.match(/ipcMain\.handle\('pane:switch', async \(_e, to, seq\) => \{[\s\S]*?\n\}\);/);
  assert.ok(m, 'pane:switch handler not found');
  const calls = [];
  let handler = null;
  const sandbox = {
    ipcMain: { handle: (name, fn) => { if (name === 'pane:switch') handler = fn; } },
    paneTrace: { mark: () => {} },
    _switchGate: createSwitchGate(),
    showNativePane: async (to, ticket) => { calls.push([to, ticket]); return true; },
  };
  vm.createContext(sandbox);
  vm.runInContext(m[0], sandbox);
  return { handler, calls };
}

test('pane:switch runtime: bad names are rejected before the gate or showNativePane', async () => {
  const { handler, calls } = loadPaneSwitchHandler();
  assert.strictEqual(await handler({}, '', 1), false);
  assert.strictEqual(await handler({}, null, 2), false);
  assert.strictEqual(await handler({}, { x: 1 }, 3), false);
  assert.strictEqual(await handler({}, 'a'.repeat(201), 4), false);
  assert.strictEqual(calls.length, 0);
});

test('pane:switch runtime: a rejected name does not consume the sequence number', async () => {
  const { handler, calls } = loadPaneSwitchHandler();
  assert.strictEqual(await handler({}, '', 10), false);
  assert.strictEqual(await handler({}, 'teams', 10), true);
  assert.strictEqual(calls.length, 1);
});

test('pane:switch runtime: a prototype-key name reaches showNativePane, which owns the lookup', async () => {
  const { handler, calls } = loadPaneSwitchHandler();
  assert.strictEqual(await handler({}, 'constructor', 1), true);
  assert.strictEqual(calls[0][0], 'constructor');
});

test('pane:switch runtime: a stale seq returns superseded without showing', async () => {
  const { handler, calls } = loadPaneSwitchHandler();
  assert.strictEqual(await handler({}, 'teams', 5), true);
  assert.strictEqual(await handler({}, 'slack', 4), 'superseded');
  assert.strictEqual(calls.length, 1);
});

test('the lazily created GitHub view raises the toolbar above itself', () => {
  const main = read('shell/main.js');
  assert.match(main, /win\.contentView\.addChildView\(githubView\);\s*_raiseToolbarView\(\);\s*githubView\.setVisible\(false\);/);
});
