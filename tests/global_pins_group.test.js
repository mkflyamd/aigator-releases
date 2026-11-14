const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');
const m = source.match(/function _groupPinsByScope\([^)]*\)\s*\{[\s\S]*?\n\}/);
assert(m, '_groupPinsByScope not found in app.js');
const { _groupPinsByScope } = vm.runInNewContext(`${m[0]}\n({ _groupPinsByScope });`, {});
const plain = (v) => JSON.parse(JSON.stringify(v));

// splits by scope and keeps order
const pins = [{ id: '1', scope: 'global' }, { id: '2' }, { id: '3', scope: 'global' }, { id: '4' }];
const grouped = plain(_groupPinsByScope(pins));
assert.deepStrictEqual(
  grouped.globals.map((p) => p.id),
  ['1', '3'],
);
assert.deepStrictEqual(
  grouped.locals.map((p) => p.id),
  ['2', '4'],
);

// no pins / bad input
assert.deepStrictEqual(plain(_groupPinsByScope([])), { globals: [], locals: [] });
assert.deepStrictEqual(plain(_groupPinsByScope(null)), { globals: [], locals: [] });
