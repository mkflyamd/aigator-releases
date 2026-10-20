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
  extract('gatorWidgetScrollSnapshot'),
  extract('gatorWidgetScrollRestore'),
  extract('gatorWidgetResize'),
].join('\n');

// Build a fake iframe whose height setter clamps every ancestor scroller the
// way a browser does: max scrollTop = other + iframeHeight - view.
function makeWorld({ scrollers, contentH, innerY }) {
  const timers = [];
  let heightStr = '';
  let win;
  const style = {};
  Object.defineProperty(style, 'height', {
    get() { return heightStr; },
    set(v) {
      heightStr = v;
      const px = parseFloat(v) || 0;
      for (const s of scrollers) {
        const max = Math.max(0, s.other + px - s.view);
        if (s.scrollTop > max) s.scrollTop = max;
      }
      if (px === 0 && win) win.scrollY = 0;
    },
  });
  const doc = {
    body: { scrollHeight: contentH, offsetHeight: contentH },
    documentElement: { scrollHeight: contentH },
    head: { appendChild() {} },
    getElementById() { return null; },
    createElement() { return {}; },
  };
  win = {
    scrollX: 0,
    scrollY: innerY || 0,
    scrollTo(x, y) { this.scrollX = x; this.scrollY = y; },
    document: doc,
    ResizeObserver: class { observe() {} },
  };
  // scrollers[0] is the iframe's parent, the last one is the outermost.
  for (let i = 0; i < scrollers.length; i++) {
    scrollers[i].parentElement = scrollers[i + 1] || null;
  }
  const iframe = {
    style,
    parentElement: scrollers[0] || null,
    contentDocument: doc,
    contentWindow: win,
  };
  const ctx = { setTimeout: (fn) => { timers.push(fn); return timers.length; } };
  const api = vm.runInNewContext(
    code + '\n;({ gatorWidgetResize, gatorWidgetScrollSnapshot, gatorWidgetScrollRestore })',
    ctx
  );
  return { iframe, win, timers, api };
}

function scroller(top, other, view) {
  return { scrollTop: top, other, view, parentElement: null };
}

// 1. The outer chat scroller keeps its position through a re-measure.
{
  const msgs = scroller(2000, 2000, 600);
  const { iframe, timers, api } = makeWorld({ scrollers: [msgs], contentH: 1200 });
  api.gatorWidgetResize(iframe);
  assert.strictEqual(msgs.scrollTop, 2000, 'chat scrollTop restored after resize');
  assert.strictEqual(iframe.style.height, '1202px');
  timers.forEach((fn) => fn());
  assert.strictEqual(msgs.scrollTop, 2000, 'chat scrollTop restored after delayed measures');
  assert.strictEqual(iframe.style.height, '1202px');
}

// 2. Every scrolled ancestor is restored, not only the outermost.
{
  const wrap = scroller(300, 200, 100);
  const msgs = scroller(2000, 2000, 600);
  const { iframe, api } = makeWorld({ scrollers: [wrap, msgs], contentH: 1200 });
  api.gatorWidgetResize(iframe);
  assert.strictEqual(wrap.scrollTop, 300);
  assert.strictEqual(msgs.scrollTop, 2000);
}

// 3. The widget's own inner scroll survives the 3000px cap path.
{
  const msgs = scroller(0, 2000, 600);
  const { iframe, win, api } = makeWorld({ scrollers: [msgs], contentH: 5000, innerY: 400 });
  api.gatorWidgetResize(iframe);
  assert.strictEqual(win.scrollY, 400, 'inner scrollY restored');
  assert.strictEqual(iframe.style.height, '3000px');
}

// 4. An unscrolled widget stays unscrolled.
{
  const msgs = scroller(0, 2000, 600);
  const { iframe, win, api } = makeWorld({ scrollers: [msgs], contentH: 900 });
  api.gatorWidgetResize(iframe);
  assert.strictEqual(msgs.scrollTop, 0);
  assert.strictEqual(win.scrollY, 0);
}

// 5. Restore never undoes growth: a position already past the snapshot is kept.
{
  const el = { scrollTop: 300 };
  const { api } = makeWorld({ scrollers: [], contentH: 100 });
  api.gatorWidgetScrollRestore({ saved: [{ el, top: 100 }], inner: null });
  assert.strictEqual(el.scrollTop, 300);
}

console.log('widget_resize_scroll: PASS');
