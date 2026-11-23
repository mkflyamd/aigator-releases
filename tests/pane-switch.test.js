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
