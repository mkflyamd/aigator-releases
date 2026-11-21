const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const wp = require('../web/static/web-pins.js');
const read = (...p) => fs.readFileSync(path.join(__dirname, '..', ...p), 'utf8');

test('ageLabel buckets', () => {
  const now = 1_000_000_000_000;
  const at = (secAgo) => now / 1000 - secAgo;
  assert.equal(wp.ageLabel(at(5), now), 'just now');
  assert.equal(wp.ageLabel(at(5 * 60), now), '5 min ago');
  assert.equal(wp.ageLabel(at(3 * 3600), now), '3 h ago');
  assert.equal(wp.ageLabel(at(2 * 86400), now), '2 d ago');
  assert.equal(wp.ageLabel(at(-30), now), 'just now');
});

test('isStale flips at 30 minutes', () => {
  const now = 1_000_000_000_000;
  assert.equal(wp.isStale(now / 1000 - 29 * 60, now), false);
  assert.equal(wp.isStale(now / 1000 - 30 * 60, now), true);
});

test('errorMessage covers every shell error code and has a fallback', () => {
  for (const code of ['pane_unavailable', 'pane_not_visible', 'page_mismatch', 'timeout', 'empty_target']) {
    assert.ok(wp.errorMessage(code).length > 10, code);
  }
  assert.equal(wp.errorMessage('something_new'), wp.errorMessage('pane_unavailable'));
});

test('icon is an svg that inherits colour', () => {
  const svg = wp.icon(14);
  assert.match(svg, /^<svg/);
  assert.match(svg, /currentColor/);
  assert.match(svg, /width="14"/);
});

test('renderer never sends a message or falls back to the default tab', () => {
  const src = read('web', 'static', 'web-pins.js');
  assert.ok(!/sendMessage|chat-send|requestSubmit|\.submit\(/.test(src));
  assert.ok(!/['"]default['"]/.test(src));
});

test('app.js renders svg pin icons, a webpin card config and decorates cards', () => {
  const src = read('web', 'static', 'app.js');
  assert.match(src, /iconHtml\.startsWith\('<svg'\)/);
  assert.match(src, /if \(source === 'webpin'\)/);
  assert.match(src, /webpin: \{ icon: window\.WebPins/);
  assert.match(src, /window\.WebPins\.decorateCard\(card, p\)/);
});

test('index.html loads web-pins.js after marketplace-pane.js; css has the new rules', () => {
  const html = read('web', 'static', 'index.html');
  const a = html.indexOf('/static/marketplace-pane.js');
  const b = html.indexOf('/static/web-pins.js');
  assert.ok(a > 0 && b > a);
  const css = read('web', 'static', 'style.css');
  for (const sel of ['.pin-ref-chip.is-stale', '.wp-suggest-chip', '.wp-fly', '.pin-card-icon.has-thumb']) {
    assert.ok(css.includes(sel), sel);
  }
});

// ---- Behaviour tests: run the real web-pins.js against a small DOM shim (no jsdom in this repo) ----
const vm = require('node:vm');

class FakeEl {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.listeners = {};
    this.attrs = {};
    this.dataset = {};
    this.style = {};
    this.parentElement = null;
    this.id = '';
    this._text = '';
    this.title = '';
    this.classes = new Set();
    this.classList = {
      add: (...c) => c.forEach((x) => this.classes.add(x)),
      toggle: (c, on) => (on ? this.classes.add(c) : this.classes.delete(c)),
      contains: (c) => this.classes.has(c),
    };
  }
  set className(v) {
    this.classes = new Set(String(v).split(/\s+/).filter(Boolean));
  }
  set textContent(v) {
    this._text = String(v);
    this.children = [];
  }
  get textContent() {
    return this._text + this.children.map((c) => c.textContent).join('');
  }
  appendChild(kid) {
    kid.parentElement = this;
    this.children.push(kid);
    return kid;
  }
  setAttribute(k, v) {
    this.attrs[k] = v;
  }
  addEventListener(type, fn) {
    (this.listeners[type] ||= []).push(fn);
  }
  click() {
    (this.listeners.click || []).forEach((fn) => fn({}));
  }
  remove() {
    if (this.parentElement) this.parentElement.children = this.parentElement.children.filter((c) => c !== this);
    this.parentElement = null;
  }
  focus() {}
  dispatchEvent() {}
  getBoundingClientRect() {
    return { left: 10, top: 500 };
  }
  insertAdjacentElement(_where, el) {
    el.parentElement = this.parentElement;
    this.parentElement.children.splice(this.parentElement.children.indexOf(this), 0, el);
  }
  all(pred, out = []) {
    this.children.forEach((c) => {
      if (pred(c)) out.push(c);
      c.all(pred, out);
    });
    return out;
  }
}

function makeEnv({ fetchImpl }) {
  const body = new FakeEl('body');
  const form = new FakeEl('form');
  const input = new FakeEl('div');
  input.id = 'chat-input';
  body.appendChild(form);
  form.appendChild(input);
  const toasts = [];
  const chips = [];
  const filled = [];
  const env = {
    _activeTabId: 'tab-a',
    _tabs: [
      { id: 'tab-a', title: 'Chat A' },
      { id: 'tab-b', title: 'Chat B' },
    ],
    _showConnectivityToast: (m) => toasts.push(m),
    _refreshPinOrb: () => {},
    fetch: fetchImpl,
    setInterval: () => 0,
    setTimeout: () => 0,
    requestAnimationFrame: () => 0,
    innerWidth: 1000,
    innerHeight: 800,
    localStorage: { getItem: () => '1', setItem() {} },
    document: {
      body,
      getElementById: (id) => body.all((e) => e.id === id)[0] || null,
      createElement: (t) => new FakeEl(t),
      createRange: () => ({ selectNodeContents() {}, collapse() {} }),
      querySelectorAll: () => [],
      execCommand: (_c, _u, text) => filled.push(text),
    },
    Event: class {},
    getSelection: () => ({ removeAllRanges() {}, addRange() {} }),
    matchMedia: () => ({ matches: true }),
  };
  env.insertPinChipAtCaret = (pin) => chips.push(pin);
  env.window = env;
  vm.createContext(env);
  vm.runInContext(read('web', 'static', 'web-pins.js'), env);
  return { env, toasts, chips, filled, form, body };
}

const payload = { appId: 'custom-x', image_b64: 'AAAA', text: 't', locator: {}, url: 'https://e.x', title: 'T', aria_label: '' };
const jsonRes = (obj, ok = true, status = 200) => ({ ok, status, json: async () => obj });
const flush = () => new Promise((r) => setImmediate(r));

test('hostile label and suggestion text are rendered as text, never as markup', async () => {
  const evil = '<img src=x onerror=1>"><script>alert(1)</script>';
  const { env, chips, form } = makeEnv({
    fetchImpl: async (url, opts) => {
      if (opts && opts.method === 'POST') return jsonRes({ id: 'p1', label: evil, captured_at: 1 });
      return jsonRes({ suggestions: [{ text: evil, kind: 'question' }, { text: evil, kind: 'action' }] });
    },
  });
  await env.WebPins.onCaptured(payload);
  await flush();
  assert.equal(chips.length, 1);
  assert.equal(chips[0].label, evil); // handed to app.js's escaping chip builder untouched
  const chipBtns = form.parentElement.all((e) => e.classes.has('wp-suggest-chip'));
  assert.equal(chipBtns.length, 2);
  for (const b of chipBtns) {
    assert.equal(b.textContent, evil);
    assert.equal(b.children.length, 0);
  }
});

test('a failed POST toasts an error and inserts no chip', async () => {
  for (const fetchImpl of [async () => jsonRes({}, false, 500), async () => { throw new Error('net'); }]) {
    const { env, toasts, chips } = makeEnv({ fetchImpl });
    await env.WebPins.onCaptured(payload);
    assert.equal(chips.length, 0);
    assert.deepEqual(toasts, ['Could not pin that. Try again.']);
  }
});

test('a malformed or id-less success body toasts an error and inserts no chip', async () => {
  const bad = [
    { ok: true, status: 200, json: async () => { throw new SyntaxError('bad json'); } },
    jsonRes({}),
    jsonRes(null),
  ];
  for (const res of bad) {
    const { env, toasts, chips } = makeEnv({ fetchImpl: async () => res });
    await env.WebPins.onCaptured(payload);
    assert.equal(chips.length, 0);
    assert.deepEqual(toasts, ['Could not pin that. Try again.']);
  }
});

test('switching tabs mid-POST inserts no chip in the other tab', async () => {
  let release;
  const gate = new Promise((r) => (release = r));
  const { env, toasts, chips, form } = makeEnv({
    fetchImpl: async (url, opts) => {
      if (opts && opts.method === 'POST') {
        await gate;
        return jsonRes({ id: 'p1', label: 'L', captured_at: 1 });
      }
      return jsonRes({ suggestions: [{ text: 's', kind: 'question' }] });
    },
  });
  const pending = env.WebPins.onCaptured(payload);
  env._activeTabId = 'tab-b';
  release();
  await pending;
  await flush();
  assert.equal(chips.length, 0);
  assert.equal(toasts.length, 1);
  assert.match(toasts[0], /Pinned to Chat A/);
  assert.equal(form.parentElement.all((e) => e.id === 'wp-suggest').length, 0);
});

test('suggestion chips fill the composer only on the owning tab, and rows never duplicate', async () => {
  const { env, chips, filled, form } = makeEnv({
    fetchImpl: async (url, opts) =>
      opts && opts.method === 'POST'
        ? jsonRes({ id: 'p1', label: 'L', captured_at: 1 })
        : jsonRes({ suggestions: [{ text: 'ask this', kind: 'question' }] }),
  });
  await Promise.all([env.WebPins.onCaptured(payload), env.WebPins.onCaptured(payload)]);
  await flush();
  const rows = () => form.parentElement.all((e) => e.id === 'wp-suggest');
  assert.equal(chips.length, 2);
  assert.equal(rows().length, 1);
  env._activeTabId = 'tab-b';
  rows()[0].all((e) => e.classes.has('wp-suggest-chip'))[0].click();
  assert.deepEqual(filled, []);
  assert.equal(rows().length, 0);
});
