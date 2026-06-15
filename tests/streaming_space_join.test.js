// Issue #52: the streaming assembler must re-insert a space dropped at a
// chunk boundary between two sentences, without corrupting decimals, domains,
// or filenames. We extract _joinStreamToken from app.js and exercise it in
// isolation (no DOM needed).

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'app.js'),
  'utf8',
);

const match = source.match(/function _joinStreamToken\(prev, tok\)\s*\{[\s\S]*?\n\}/);
assert(match, '_joinStreamToken not found in app.js');
const _joinStreamToken = vm.runInNewContext(match[0] + '; _joinStreamToken;', {});

// Helper: simulate streaming `parts` and return the assembled string.
function assemble(parts) {
  let full = '';
  for (const p of parts) full += _joinStreamToken(full, p);
  return full;
}

// ── Sentence boundaries that lost their space MUST be repaired ──
assert.strictEqual(assemble(['one.', 'Two']), 'one. Two');
assert.strictEqual(assemble(['Done!', 'Next']), 'Done! Next');
assert.strictEqual(assemble(['Really?', 'Yes']), 'Really? Yes');
assert.strictEqual(assemble(['end.', '"Quote"']), 'end. "Quote"');
assert.strictEqual(assemble(['done.', '**Note**']), 'done. **Note**');
assert.strictEqual(assemble(['done.', '`code`']), 'done. `code`');
assert.strictEqual(assemble(['done.', '[link]']), 'done. [link]');

// ── Already-spaced or paragraph-separated text MUST be untouched ──
assert.strictEqual(assemble(['one. ', 'Two']), 'one. Two');
assert.strictEqual(assemble(['one.\n', 'Two']), 'one.\nTwo');
assert.strictEqual(assemble(['one.', '\nTwo']), 'one.\nTwo');

// ── False positives that MUST stay glued ──
assert.strictEqual(assemble(['3.', '14']), '3.14');          // decimal
assert.strictEqual(assemble(['app.', 'js']), 'app.js');      // filename
assert.strictEqual(assemble(['claude.', 'ai']), 'claude.ai'); // domain
assert.strictEqual(assemble(['e.g.', 'something']), 'e.g.something'); // lowercase continuation
assert.strictEqual(assemble(['3,', '000']), '3,000');        // comma is not a sentence end

console.log('streaming_space_join: all assertions passed');
