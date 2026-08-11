// Decision #12 (2026-08-07 milestone — Plugin Marketplace A+B+E, Increment
// 4b): command discovery in the "/" compose-bar dropdown.
//
// _fuzzyFilterCommands is the pure filter/ranking predicate that decides
// which installed plugin commands show up in the COMMANDS section, matching
// the Increment 4a convention (_cardActionState, _findCollisionEntry, etc.)
// of pulling DOM-adjacent logic out into a plain function so it's testable
// without a browser. _fuzzyScore is its only dependency (also in app.js),
// so both are extracted together into the same vm context.
//
// The other new pieces in this increment — _commitCommandOnly (text-node
// insertion via _replaceAtHashInInput), the COMMANDS section render inside
// _openSkillPickerDropdown, and window.registerPluginCommand — all require
// a live `document`/DOM (contenteditable manipulation, selection ranges),
// which this repo's vm-based harness does not provide (no jsdom, matching
// marketplace_verified_consent.test.js's own documented limitation for
// _installVerifiedPlugin/_showVerifiedConsentModal). That surface was
// verified by static review instead — see the increment's final report.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'app.js'),
  'utf8',
);

function extractFn(name) {
  const re = new RegExp('function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}');
  const match = source.match(re);
  assert(match, name + ' not found in app.js');
  return match[0];
}

const combined = extractFn('_fuzzyScore') + '\n' + extractFn('_fuzzyFilterCommands') +
  ';\nthis._fuzzyScore = _fuzzyScore; this._fuzzyFilterCommands = _fuzzyFilterCommands;';
const sandbox = {};
vm.runInNewContext(combined, sandbox);
const _fuzzyFilterCommands = sandbox._fuzzyFilterCommands;

const COMMANDS = [
  { name: 'standup', description: 'Daily standup template', plugin_id: 'amd-skills' },
  { name: 'code-review', description: 'Request a code review', plugin_id: 'code-review' },
  { name: 'rocm-basics', description: '', plugin_id: 'rocm-toolkit' },
];

// Empty query -> everything, unranked (same contract as _fuzzyFilterSkills).
assert.deepStrictEqual(_fuzzyFilterCommands(COMMANDS, ''), COMMANDS, 'empty query returns all commands, unfiltered');

// Exact-prefix match -> only the matching command.
{
  const result = _fuzzyFilterCommands(COMMANDS, 'stand');
  assert.strictEqual(result.length, 1);
  assert.strictEqual(result[0].name, 'standup');
}

// Fuzzy (non-contiguous, in-order) match still hits — "crv" against "code-review".
{
  const result = _fuzzyFilterCommands(COMMANDS, 'crv');
  assert.ok(result.some(c => c.name === 'code-review'), 'non-contiguous in-order chars must still match');
}

// No match for any command -> empty array, not an error.
assert.deepStrictEqual(_fuzzyFilterCommands(COMMANDS, 'zzzzz'), []);

// Matching is on the bare command name only — a query matching only the
// description/plugin_id (not the name) must NOT match, unlike skills (which
// also fuzzy-match on label). This is the documented difference from
// _fuzzyFilterSkills noted in _fuzzyFilterCommands' own comment.
assert.deepStrictEqual(_fuzzyFilterCommands(COMMANDS, 'daily'), [], 'must not match on description text');
assert.deepStrictEqual(_fuzzyFilterCommands(COMMANDS, 'amd-skills'), [], 'must not match on plugin_id text');

// Ranking: a tighter/prefix match for one query character set outranks a
// scattered match, same ordering guarantee _fuzzyFilterSkills already relies on.
{
  const candidates = [
    { name: 'rocm-basics', description: '', plugin_id: 'x' },
    { name: 'rocm-advanced-config', description: '', plugin_id: 'x' },
  ];
  const result = _fuzzyFilterCommands(candidates, 'rocm');
  assert.strictEqual(result[0].name, 'rocm-basics', 'shorter/tighter prefix match should rank first');
}

console.log('plugin_commands_dropdown: all assertions passed');
