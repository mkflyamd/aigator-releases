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
function line(re) {
  const m = src.match(re);
  if (!m) throw new Error(String(re) + ' not found in app.js');
  return m[0];
}

const code = [
  line(/const GATOR_WIDGET_MAX_H = \d+;/),
  extract('gatorWidgetScrollSnapshot'),
  extract('gatorWidgetScrollRestore'),
  extract('gatorWidgetApplyHeight'),
  extract('gatorWidgetFrameForSource'),
  extract('gatorWidgetOnResize'),
  extract('gatorWidgetFrameScript'),
  'let reveals = [];',
  'function gatorWidgetRevealOnce(f) { reveals.push(f); }',
  '({ gatorWidgetApplyHeight, gatorWidgetScrollSnapshot, gatorWidgetScrollRestore, gatorWidgetOnResize, gatorWidgetFrameScript, reveals })',
].join('\n');

// A fake iframe whose height setter clamps every ancestor scroller the way a
// browser does: max scrollTop = other + iframeHeight - view.
function makeWorld({ scrollers, frames }) {
  const style = {};
  let heightStr = '';
  Object.defineProperty(style, 'height', {
    get() {
      return heightStr;
    },
    set(v) {
      heightStr = v;
      const px = parseFloat(v) || 0;
      for (const s of scrollers) {
        const max = Math.max(0, s.other + px - s.view);
        if (s.scrollTop > max) s.scrollTop = max;
      }
    },
  });
  for (let i = 0; i < scrollers.length; i++) scrollers[i].parentElement = scrollers[i + 1] || null;
  const iframe = {
    style,
    parentElement: scrollers[0] || null,
    dataset: {},
    contentWindow: { name: 'w' },
  };
  const ctx = { document: { querySelectorAll: () => frames || [iframe] } };
  const api = vm.runInNewContext(code, ctx);
  return { iframe, api };
}
const scroller = (top, other, view) => ({ scrollTop: top, other, view, parentElement: null });

// 1. A reported height sets the frame height; the chat scroller keeps its place.
{
  const msgs = scroller(2000, 2000, 600);
  const { iframe, api } = makeWorld({ scrollers: [msgs] });
  api.gatorWidgetApplyHeight(iframe, 1202);
  assert.strictEqual(iframe.style.height, '1202px');
  assert.strictEqual(msgs.scrollTop, 2000, 'chat scrollTop kept');
}

// 2. Every scrolled ancestor is restored, not only the outermost.
{
  const wrap = scroller(300, 200, 100);
  const msgs = scroller(2000, 2000, 600);
  const { iframe, api } = makeWorld({ scrollers: [wrap, msgs] });
  const snap = api.gatorWidgetScrollSnapshot(iframe);
  wrap.scrollTop = 0;
  msgs.scrollTop = 10;
  api.gatorWidgetScrollRestore(snap);
  assert.strictEqual(wrap.scrollTop, 300);
  assert.strictEqual(msgs.scrollTop, 2000);
}

// 3. The height is capped and rounded up.
{
  const { iframe, api } = makeWorld({ scrollers: [] });
  api.gatorWidgetApplyHeight(iframe, 5000);
  assert.strictEqual(iframe.style.height, '3000px');
  api.gatorWidgetApplyHeight(iframe, 410.2);
  assert.strictEqual(iframe.style.height, '411px');
}

// 4. Restore never undoes growth: a position already past the snapshot is kept.
{
  const el = { scrollTop: 300 };
  const { api } = makeWorld({ scrollers: [] });
  api.gatorWidgetScrollRestore({ saved: [{ el, top: 100 }] });
  assert.strictEqual(el.scrollTop, 300);
}

// 5. gator:resize is honoured only from a widget frame, with a sane height.
{
  const a = { style: {}, dataset: {}, parentElement: null, contentWindow: { id: 'a' } };
  const b = { style: {}, dataset: {}, parentElement: null, contentWindow: { id: 'b' } };
  const { api } = makeWorld({ scrollers: [], frames: [a, b] });
  api.gatorWidgetOnResize({ height: 500 }, { source: b.contentWindow });
  assert.strictEqual(b.style.height, '500px');
  assert.strictEqual(a.style.height, undefined, 'other frames are untouched');
  api.gatorWidgetOnResize({ height: 700 }, { source: { id: 'outsider' } });
  assert.strictEqual(a.style.height, undefined, 'a non-widget window is ignored');
  assert.strictEqual(b.style.height, '500px');
  for (const bad of [0, -5, NaN, Infinity, 'x', null, undefined, {}]) {
    api.gatorWidgetOnResize({ height: bad }, { source: a.contentWindow });
  }
  assert.strictEqual(a.style.height, undefined, 'bad heights are ignored');
  api.gatorWidgetOnResize({ height: '640' }, { source: a.contentWindow });
  assert.strictEqual(a.style.height, '640px', 'numeric strings are accepted');
  assert.strictEqual(api.reveals.length, 2, 'reveal runs after the first size of each frame');
  assert.ok(api.reveals.includes(a) && api.reveals.includes(b));
  api.gatorWidgetOnResize({ height: 800 }, { source: b.contentWindow });
  assert.strictEqual(api.reveals.length, 2, 'reveal runs once per frame');
}

// 6. The script injected into the frame reports its own height by postMessage.
{
  const timers = [];
  const posted = [];
  const observed = [];
  let contentH = 400;
  let overflowStyle = '';
  const doc = {
    body: {
      get scrollHeight() {
        return contentH;
      },
    },
    documentElement: { getBoundingClientRect: () => ({ height: contentH }) },
    head: {
      appendChild(el) {
        overflowStyle = el.textContent;
      },
    },
    createElement: () => ({}),
  };
  const listeners = {};
  const ctx = {
    document: doc,
    parent: { postMessage: (m, o) => posted.push({ m: JSON.parse(JSON.stringify(m)), o }) },
    setTimeout: (fn, ms) => {
      timers.push({ fn, ms });
    },
    ResizeObserver: class {
      constructor(cb) {
        this.cb = cb;
      }
      observe(el) {
        observed.push(el);
        ctx.fire = this.cb;
      }
    },
    addEventListener: (t, fn) => {
      listeners[t] = fn;
    },
  };
  const { api } = makeWorld({ scrollers: [] });
  const script = api.gatorWidgetFrameScript();
  assert.ok(!/<\/?script/i.test(script), 'script text carries no script tags');
  vm.runInNewContext(script, ctx);
  assert.ok(observed.includes(doc.documentElement), 'observes the document element');
  assert.ok(listeners.load, 'measures on load');
  assert.deepStrictEqual(
    posted.map((p) => p.m),
    [{ type: 'gator:resize', height: 402 }],
    'reports content height + 2',
  );
  assert.strictEqual(posted[0].o, '*', 'an opaque-origin frame can only post to *');
  timers.forEach((t) => t.fn());
  assert.strictEqual(posted.length, 1, 'an unchanged height is not re-sent');
  contentH = 900;
  ctx.fire();
  assert.deepStrictEqual(posted[1].m, { type: 'gator:resize', height: 902 }, 'growth is reported');
  contentH = 120;
  ctx.fire();
  assert.deepStrictEqual(
    posted[2].m,
    { type: 'gator:resize', height: 122 },
    'shrinking is reported',
  );
  contentH = 6000;
  ctx.fire();
  assert.deepStrictEqual(
    posted[3].m,
    { type: 'gator:resize', height: 3000 },
    'reported height is capped',
  );
  assert.ok(/overflow-y:\s*auto/.test(overflowStyle), 'over the cap the frame scrolls internally');
}

// 7. No parent code reads into the widget frame any more.
for (const name of ['gatorWidgetScrollSnapshot', 'gatorWidgetApplyHeight', 'gatorWidgetOnResize']) {
  const body = extract(name);
  assert.ok(
    !/contentDocument|contentWindow|ResizeObserver/.test(body),
    name + ' does not reach into the frame',
  );
}
assert.ok(!/function gatorWidgetResize\(/.test(src), 'the DOM-reading gatorWidgetResize is gone');

console.log('widget_resize_scroll: PASS');
