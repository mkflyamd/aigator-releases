const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function extract(name) {
  const m = src.match(new RegExp('function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}'));
  if (!m) throw new Error(name + ' not found in app.js');
  return m[0];
}

const code = [
  'let _userScrolledUp = false;',
  'let _gatorWidgetRevealHold = false;',
  extract('gatorWidgetShouldReveal'),
  extract('gatorWidgetRevealOnce'),
  '({ gatorWidgetShouldReveal, gatorWidgetRevealOnce,',
  '   state: () => ({ up: _userScrolledUp, hold: _gatorWidgetRevealHold }),',
  '   setUp: (v) => { _userScrolledUp = v; } })',
].join('\n');

function world({ streaming, wrapH, viewportH }) {
  const wrap = {
    offsetHeight: wrapH,
    getBoundingClientRect: () => ({ top: 700 }),
  };
  const msgs = {
    clientHeight: viewportH,
    scrollTop: 1000,
    getBoundingClientRect: () => ({ top: 100 }),
    contains: (el) => el === wrap,
  };
  const iframe = { closest: (sel) => (sel === '.gator-widget-wrap' ? wrap : null) };
  const ctx = {
    _chatTaskIds: new Set(streaming ? ['t1'] : []),
    _activeTabId: 't1',
    document: { getElementById: (id) => (id === 'messages' ? msgs : null) },
  };
  const api = vm.runInNewContext(code, ctx);
  return { api, msgs, iframe };
}

// Truth table for the pure decision.
const T = (...a) =>
  vm.runInNewContext(
    extract('gatorWidgetShouldReveal') + ';gatorWidgetShouldReveal(' + a.join(',') + ')',
  );
assert.strictEqual(T(true, true, 900, 500), true);
assert.strictEqual(T(false, true, 900, 500), false, 'not streaming');
assert.strictEqual(T(true, false, 900, 500), false, 'user scrolled up');
assert.strictEqual(T(true, true, 400, 500), false, 'widget fits the viewport');
assert.strictEqual(T(true, true, 500, 500), false, 'equal height does not need a reveal');

// Reveal scrolls the widget top into view and sets both flags.
{
  const { api, msgs, iframe } = world({ streaming: true, wrapH: 900, viewportH: 500 });
  api.gatorWidgetRevealOnce(iframe);
  assert.strictEqual(msgs.scrollTop, 1600);
  assert.deepStrictEqual(JSON.parse(JSON.stringify(api.state())), { up: true, hold: true });
}

// No reveal: short widget, not streaming, or the user already scrolled up.
{
  const short = world({ streaming: true, wrapH: 300, viewportH: 500 });
  short.api.gatorWidgetRevealOnce(short.iframe);
  assert.strictEqual(short.msgs.scrollTop, 1000);
  assert.deepStrictEqual(JSON.parse(JSON.stringify(short.api.state())), { up: false, hold: false });

  const idle = world({ streaming: false, wrapH: 900, viewportH: 500 });
  idle.api.gatorWidgetRevealOnce(idle.iframe);
  assert.strictEqual(idle.msgs.scrollTop, 1000);

  const away = world({ streaming: true, wrapH: 900, viewportH: 500 });
  away.api.setUp(true);
  away.api.gatorWidgetRevealOnce(away.iframe);
  assert.strictEqual(away.msgs.scrollTop, 1000);
  assert.strictEqual(away.api.state().hold, false);
}

// Source wiring.
assert.ok(/let _gatorWidgetRevealHold = false;/.test(src), 'hold flag declared');
assert.ok(
  /if \(_activeTabId === requestTabId && !_userScrolledUp && !_gatorWidgetRevealHold\)\s*_pinScrollToBottom\(messages\);/.test(
    src,
  ),
  'post-stream pin respects the hold',
);
assert.ok(
  /const doSend = async \(overridePayload\) => \{\s*_userScrolledUp = false;\s*_gatorWidgetRevealHold = false;/.test(
    src,
  ),
  'doSend clears the hold',
);
assert.ok(
  /gatorWidgetApplyHeight\(frame, h\);[\s\S]*?gatorWidgetRevealOnce\(frame\);/.test(src),
  'the first reported size reveals once',
);

console.log('widget_reveal_once: PASS');
