// Issue #6: After attaching a file via Ctrl+O, the file chip in the prompt bar
// could not be removed by clicking its ✕ button.
//
// Root cause: the chip is appended into #chat-input, which is a
// `contenteditable` host. A plain `click` listener on a child button is
// unreliable inside contenteditable — the preceding `mousedown` moves the
// selection/caret and the button often never receives the click. The remove
// button only listened for `click`, so it was effectively unresponsive.
//
// The fix extracts a pure helper `_wireChipRemove(removeBtn, chip, input)` that
// wires BOTH a `mousedown` handler (preventDefault, so the contenteditable does
// not steal the interaction) and a `click` handler that removes the chip.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'app.js'),
  'utf8',
);

const match = source.match(
  /function _wireChipRemove\([^)]*\)\s*\{[\s\S]*?\n\}/,
);
assert(match, '_wireChipRemove not found in app.js');
const _wireChipRemove = vm.runInNewContext(
  match[0] + '; _wireChipRemove;',
  {},
);

function fakeBtn() {
  const listeners = {};
  return {
    listeners,
    addEventListener(type, fn) { listeners[type] = fn; },
  };
}

function fakeEvent() {
  return {
    _prevented: false,
    _stopped: false,
    preventDefault() { this._prevented = true; },
    stopPropagation() { this._stopped = true; },
  };
}

// --- The bug: mousedown must be wired so contenteditable doesn't swallow the click ---
{
  const btn = fakeBtn();
  const chip = { removed: false, remove() { this.removed = true; } };
  const input = { focused: false, focus() { this.focused = true; } };
  _wireChipRemove(btn, chip, input);

  assert(typeof btn.listeners.mousedown === 'function',
    'remove button must register a mousedown handler (contenteditable fix)');
  const md = fakeEvent();
  btn.listeners.mousedown(md);
  assert(md._prevented,
    'mousedown handler must call preventDefault so the click is not swallowed');
}

// --- Clicking ✕ removes the chip and restores focus to the input ---
{
  const btn = fakeBtn();
  const chip = { removed: false, remove() { this.removed = true; } };
  const input = { focused: false, focus() { this.focused = true; } };
  _wireChipRemove(btn, chip, input);

  assert(typeof btn.listeners.click === 'function',
    'remove button must register a click handler');
  const ev = fakeEvent();
  btn.listeners.click(ev);
  assert(chip.removed, 'click must remove the chip');
  assert(input.focused, 'click must return focus to the input');
  assert(ev._prevented && ev._stopped,
    'click handler must preventDefault and stopPropagation');
}

// --- Both chip-creation paths (Ctrl+O picker AND drag-drop/attach upload) must
//     route through the shared helper, so neither regresses to a bare click. ---
{
  const callSites = (source.match(/_wireChipRemove\(removeBtn, chip, input\)/g) || []).length;
  assert(callSites >= 2,
    'both file-chip paths (Ctrl+O and drag-drop upload) must use _wireChipRemove');
  // No file-chip remove button should be wired with a bare inline click handler.
  assert(!/file-chip-remove[\s\S]{0,200}?addEventListener\('click'/.test(source),
    'file-chip remove buttons must not use an inline click listener (use _wireChipRemove)');
}

console.log('file_chip_remove.test.js: all assertions passed');
