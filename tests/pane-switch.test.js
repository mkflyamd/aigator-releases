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
  assert.match(main, /if \(!preexisting\) _raiseToolbarView\(\);\s*if \(ticket !== null && !_switchGate\.isCurrent\(ticket\)\) return 'superseded';/);
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
  assert.match(tp, /window\.gatorShell\.switchPane\(appId, \+\+_paneSwitchSeq\)/);
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
