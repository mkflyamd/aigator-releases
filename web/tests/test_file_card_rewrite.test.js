/**
 * A file the model rewrites during one turn keeps one card, not one per rewrite.
 *
 * Each run of run_python writes into its own folder, so the same name arrives again
 * with a new download link. The newer card replaces the older one.
 */

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.js'), 'utf8');
const start = source.indexOf('function _dropEarlierFileCard(');
assert.notStrictEqual(start, -1, '_dropEarlierFileCard must exist in app.js');
const end = source.indexOf('\n}\n', start) + 3;
const ctx = {};
vm.runInNewContext(source.slice(start, end), ctx);

function fakeRow(names) {
  const cards = names.map((n) => ({
    dataset: { fileName: n },
    removed: false,
    remove() { this.removed = true; },
  }));
  return { cards, querySelectorAll: () => cards };
}

const row = fakeRow(['demo.html', 'notes.txt']);
assert.strictEqual(ctx._dropEarlierFileCard(row, 'demo.html'), true);
assert.deepStrictEqual(row.cards.map((c) => c.removed), [true, false]);

const other = fakeRow(['notes.txt']);
assert.strictEqual(ctx._dropEarlierFileCard(other, 'demo.html'), false);
assert.strictEqual(other.cards[0].removed, false);

assert.ok(
  source.includes('wrapper.dataset.fileName = f.name;'),
  'each card must record its file name so a rewrite can find it',
);
assert.ok(source.includes('updated just now'), 'a replaced card says it was updated');

console.log('ok');
