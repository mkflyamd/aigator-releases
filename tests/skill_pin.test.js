const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function extract(name) {
  const m = source.match(new RegExp(`function ${name}\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}`));
  assert(m, `${name} not found in app.js`);
  return m[0];
}
const constLine = source.match(/const _DEMO_RECORDER_SKILL = '[^']+';/);
assert(constLine, '_DEMO_RECORDER_SKILL not found in app.js');

const names = ['_pinFromMessage', '_mergePin', '_pinForSend'];
const fns = vm.runInNewContext(
  `${constLine[0]}\n${names.map(extract).join('\n')}\n({ ${names.join(', ')} });`,
  {},
);
const plain = (v) => JSON.parse(JSON.stringify(v));
const DR = 'gator-demo-recorder';

// _pinFromMessage: explicit pin_skill wins
assert.deepStrictEqual(
  plain(fns._pinFromMessage({ pin_skill: DR, project_id: 'demo_20261019_101500' }, 'anything')),
  { skill: DR, projectId: 'demo_20261019_101500' },
);
// invalid project ids are dropped but the skill pin is kept
assert.deepStrictEqual(plain(fns._pinFromMessage({ pin_skill: DR, project_id: '../x' }, 'hi')), {
  skill: DR,
  projectId: null,
});
assert.deepStrictEqual(plain(fns._pinFromMessage({ pin_skill: DR }, 'hi')), {
  skill: DR,
  projectId: null,
});
// legacy prefix inference
for (const prefix of [
  'Recording complete. Output: x',
  'NARRATION_APPROVED:[{"text":"a"}]',
  'NARRATION_REEDIT:[{"text":"a"}]',
  'Please delete the frames/ and tts_work/ folders',
]) {
  assert.deepStrictEqual(
    plain(fns._pinFromMessage({ project_id: 'demo_1' }, prefix)),
    { skill: DR, projectId: 'demo_1' },
    prefix,
  );
}
// ordinary widget messages do not pin
assert.strictEqual(fns._pinFromMessage({}, 'Show my calendar'), null);
assert.strictEqual(fns._pinFromMessage(null, 'Show my calendar'), null);

// _mergePin
const existing = { skill: DR, projectId: 'demo_1' };
assert.deepStrictEqual(plain(fns._mergePin(existing, null)), existing);
assert.strictEqual(fns._mergePin(null, null), null);
assert.deepStrictEqual(plain(fns._mergePin(existing, { skill: DR, projectId: null })), existing);
assert.deepStrictEqual(
  plain(fns._mergePin(existing, { skill: DR, projectId: 'demo_2' })),
  { skill: DR, projectId: 'demo_2' },
);
assert.deepStrictEqual(
  plain(fns._mergePin(existing, { skill: 'jira', projectId: null })),
  { skill: 'jira', projectId: null },
);

// _pinForSend: slash commands escape the pin
assert.strictEqual(fns._pinForSend(null, 'hello'), null);
assert.deepStrictEqual(plain(fns._pinForSend(existing, 'hello')), existing);
assert.strictEqual(fns._pinForSend(existing, '/jira list'), null);
assert.strictEqual(fns._pinForSend(existing, '  /jira list'), null);

// source wiring
assert(/localStorage\.removeItem\('tab-pin-' \+ tabId\)/.test(source), 'tab close must drop the pin');
assert(/_tabPins\.delete\(tabId\)/.test(source), 'tab close must clear the pin map');
assert(
  /pinned_skill: _sendPin\.skill/.test(source) && /pinned_project_id: _sendPin\.projectId/.test(source),
  'doSend must send the pin',
);
assert(
  (source.match(/\.\.\._sendPinFields/g) || []).length === 2,
  'pin fields must be in both the resend payload and the post body',
);

// The pin chip is drawn whenever the active tab changes or loads, not only in switchTab
for (const name of ['createTab', 'createTabWithId', '_initTabSystem']) {
  assert(/_renderPinChip\(/.test(extract(name)), `${name} must draw the active tab's pin chip`);
}

console.log('skill_pin: all assertions passed');
