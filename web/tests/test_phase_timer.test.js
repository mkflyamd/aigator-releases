/**
 * The running phase shows how long it has been going, and says so when it is slow.
 * The page times it from the event's start time, so the server sends nothing each second.
 */

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.js'), 'utf8');
const start = source.indexOf('function _phaseLine(');
assert.notStrictEqual(start, -1, '_phaseLine must exist in app.js');
const end = source.indexOf('\n}\n', start) + 3;
const ctx = {};
vm.runInNewContext(source.slice(start, end), ctx);

const t0 = 1_000_000;
const line = (...a) => JSON.parse(JSON.stringify(ctx._phaseLine(...a)));
const at = (seconds) => t0 + seconds * 1000;

assert.deepStrictEqual(line('Searching Jira...', t0, at(3)), { text: 'Searching Jira...', level: 'info' });
assert.deepStrictEqual(line('Searching Jira...', t0, at(45)), { text: 'Searching Jira... · 45s', level: 'info' });
assert.deepStrictEqual(line('Searching Jira...', t0, at(95)), { text: 'Searching Jira... · 1m 35s', level: 'info' });
assert.deepStrictEqual(line('Searching Jira...', t0, at(130)), {
  text: 'Searching Jira... · 2m 10s · Taking longer than usual',
  level: 'warn',
});
assert.deepStrictEqual(line('Searching Jira...', null, at(130)), { text: 'Searching Jira...', level: 'info' });

assert.ok(source.includes('msg.started_at'), 'the status handler must read started_at');

console.log('ok');
