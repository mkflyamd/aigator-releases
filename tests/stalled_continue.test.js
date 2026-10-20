// A stall caused by a rejected tool call must make Continue resubmit the original
// request plus the failure note; every other stall keeps the plain Continue prompt.
// The real handler code is cut out of app.js and run against fake state.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function braceBlock(startMarker) {
  const start = source.indexOf(startMarker);
  assert(start > 0, `${startMarker} not found in app.js`);
  const open = source.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < source.length; i++) {
    if (source[i] === '{') depth++;
    if (source[i] === '}' && --depth === 0) return source.slice(open + 1, i);
  }
  throw new Error(`${startMarker} block not closed`);
}

function fn(name) {
  const match = source.match(new RegExp(`function ${name}\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}`));
  assert(match, `${name} not found in app.js`);
  return match[0];
}

const stalledBranch = braceBlock('} else if (msg.stalled) {');
const bannerBlock = braceBlock('if (_streamExhausted) {');
const helpers = `${fn('_lastUserRequestText')}\n${fn('_continueRequestText')}`;

const RETRY = 'Note: the previous attempt failed because the call to run_python (code) had missing or invalid arguments.';

function onStalled(msg) {
  const ctx = { msg, _streamExhausted: false, _exhaustedMessage: '', _continueRetryNote: '' };
  vm.runInNewContext(stalledBranch, ctx);
  return ctx;
}

// stalled event: banner text and retry note are captured
let ctx = onStalled({ stalled: true, message: 'Gator could not form a valid call to run_python (code)', retry_note: RETRY });
assert.strictEqual(ctx._streamExhausted, true);
assert.strictEqual(ctx._exhaustedMessage, 'Gator could not form a valid call to run_python (code)');
assert.strictEqual(ctx._continueRetryNote, RETRY);

// stalled event without a note (watchdog, end-of-turn failure) leaves the note empty
ctx = onStalled({ stalled: true, message: 'Gator stopped after going silent' });
assert.strictEqual(ctx._continueRetryNote, '');

function clickContinue({ retryNote, history, requestTabId = 'tab-1', activeTabId = 'tab-1' }) {
  const created = [];
  const input = { textContent: '', dispatchEvent() {} };
  const form = { submits: 0, requestSubmit() { this.submits++; } };
  const el = () => {
    const e = { className: '', textContent: '', children: [], listeners: {}, removed: false };
    e.appendChild = (c) => e.children.push(c);
    e.addEventListener = (type, cb) => { e.listeners[type] = cb; };
    e.remove = () => { e.removed = true; };
    created.push(e);
    return e;
  };
  const prose = { parentElement: { appendChild() {} } };
  const state = {
    document: {
      createElement: el,
      getElementById: (id) => (id === 'chat-input' ? input : id === 'chat-form' ? form : null),
    },
    Event: function Event() {},
    prose,
    msgDiv: {},
    requestTabId,
    _activeTabId: activeTabId,
    _exhaustedMessage: 'banner text',
    _continueRetryNote: retryNote,
    _loadTabHistory: () => history,
  };
  vm.runInNewContext(`${helpers}\n${bannerBlock}`, state);
  const btn = created.find((e) => e.className === 'exhausted-continue-btn');
  assert(btn, 'Continue button created');
  btn.listeners.click();
  return { input, form, banner: created[0] };
}

const history = [
  { role: 'user', content: 'record my demo' },
  { role: 'assistant', content: 'working' },
];

// rejected-call stall: original request + note, resubmitted once
let r = clickContinue({ retryNote: RETRY, history });
assert.strictEqual(r.input.textContent, `record my demo\n\n${RETRY}`);
assert.strictEqual(r.form.submits, 1);

// no note: the plain Continue prompt, as before
r = clickContinue({ retryNote: '', history });
assert.strictEqual(r.input.textContent, 'Continue where you left off.');
assert.strictEqual(r.form.submits, 1);

// note but no recorded user request: plain Continue
r = clickContinue({ retryNote: RETRY, history: [] });
assert.strictEqual(r.input.textContent, 'Continue where you left off.');

// note-carrying Continue must not resubmit a request into a different tab
r = clickContinue({ retryNote: RETRY, history, requestTabId: 'tab-1', activeTabId: 'tab-2' });
assert.strictEqual(r.form.submits, 0);
assert.strictEqual(r.banner.removed, false);

console.log('stalled_continue: all assertions passed');
