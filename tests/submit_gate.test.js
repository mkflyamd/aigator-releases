// Issue #30: pressing Enter must submit when the prompt has ONLY a staged
// image (no text). The send gate should fire when text, a file chip, OR an
// image is present. We extract _canSubmitMessage from app.js and verify the
// OR logic in isolation.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'app.js'),
  'utf8',
);

const match = source.match(/function _canSubmitMessage\(hasText, hasFileChips, hasImages\)\s*\{[\s\S]*?\n\}/);
assert(match, '_canSubmitMessage not found in app.js');
const _canSubmitMessage = vm.runInNewContext(match[0] + '; _canSubmitMessage;', {});

// image-only (the bug): no text, no file chip, one image -> MUST submit
assert.strictEqual(_canSubmitMessage('', false, true), true, 'image-only must submit');
// text-only -> submit
assert.strictEqual(_canSubmitMessage('hello', false, false), true);
// file-chip-only -> submit
assert.strictEqual(_canSubmitMessage('', true, false), true);
// text + image -> submit
assert.strictEqual(_canSubmitMessage('hi', false, true), true);
// truly empty -> MUST NOT submit
assert.strictEqual(_canSubmitMessage('', false, false), false, 'empty must not submit');

console.log('submit_gate: all assertions passed');
