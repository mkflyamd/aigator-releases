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
  for (const code of [
    'pane_unavailable',
    'pane_not_visible',
    'page_mismatch',
    'timeout',
    'empty_target',
  ]) {
    assert.ok(wp.errorMessage(code).length > 10, code);
  }
  assert.equal(wp.errorMessage('something_new'), wp.errorMessage('pane_unavailable'));
});

test('renderer never sends a message or falls back to the default tab', () => {
  const src = read('web', 'static', 'web-pins.js');
  assert.ok(!/sendMessage|chat-send|requestSubmit|\.submit\(/.test(src));
  assert.ok(!/['"]default['"]/.test(src));
});

test('app.js gives web pins the chat pin icon, a webpin card config and decorates cards', () => {
  const src = read('web', 'static', 'app.js');
  assert.match(src, /webpin: \{ label: 'Web view' \}/);
  assert.doesNotMatch(src, /WebPins\.icon/);
  assert.match(src, /window\.WebPins\.decorateCard\(card, p\)/);
});

test('index.html loads web-pins.js after marketplace-pane.js; css has the new rules', () => {
  const html = read('web', 'static', 'index.html');
  const a = html.indexOf('/static/marketplace-pane.js');
  const b = html.indexOf('/static/web-pins.js');
  assert.ok(a > 0 && b > a);
  const css = read('web', 'static', 'style.css');
  for (const sel of [
    '.pin-ref-chip.is-stale',
    '.wp-suggest-chip',
    '.wp-fly',
    '.pin-card-icon.has-thumb',
  ]) {
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
      remove: (...c) => c.forEach((x) => this.classes.delete(x)),
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
    if (this.parentElement)
      this.parentElement.children = this.parentElement.children.filter((c) => c !== this);
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

function makeEnv({ fetchImpl, gatorShell }) {
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
    gatorShell,
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

const payload = {
  appId: 'custom-x',
  image_b64: 'AAAA',
  text: 't',
  locator: {},
  url: 'https://e.x',
  title: 'T',
  aria_label: '',
};
const jsonRes = (obj, ok = true, status = 200) => ({ ok, status, json: async () => obj });
const flush = () => new Promise((r) => setImmediate(r));

test('hostile label and suggestion text are rendered as text, never as markup', async () => {
  const evil = '<img src=x onerror=1>"><script>alert(1)</script>';
  const { env, chips, form } = makeEnv({
    fetchImpl: async (url, opts) => {
      if (opts && opts.method === 'POST') return jsonRes({ id: 'p1', label: evil, captured_at: 1 });
      return jsonRes({
        suggestions: [
          { text: evil, kind: 'question' },
          { text: evil, kind: 'action' },
        ],
      });
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
  for (const fetchImpl of [
    async () => jsonRes({}, false, 500),
    async () => {
      throw new Error('net');
    },
  ]) {
    const { env, toasts, chips } = makeEnv({ fetchImpl });
    await env.WebPins.onCaptured(payload);
    assert.equal(chips.length, 0);
    assert.deepEqual(toasts, ['Could not pin that. Try again.']);
  }
});

test('a malformed or id-less success body toasts an error and inserts no chip', async () => {
  const bad = [
    {
      ok: true,
      status: 200,
      json: async () => {
        throw new SyntaxError('bad json');
      },
    },
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
  rows()[0]
    .all((e) => e.classes.has('wp-suggest-chip'))[0]
    .click();
  assert.deepEqual(filled, []);
  assert.equal(rows().length, 0);
});

// ---- Task 9: recapture round trip ----
const DETAIL = {
  meta: { app_id: 'custom-pbi', locator: { selector: '#a' }, url: 'https://x.test/y' },
};

function fakeFetch({
  detail = DETAIL,
  snapshot = { ok: true, changed: true, captured_at: 123, match: 'selector' },
} = {}) {
  const calls = [];
  const fn = async (url, opts = {}) => {
    calls.push({ url, opts });
    if (url.endsWith('/snapshot'))
      return { ok: snapshot.ok, status: snapshot.ok ? 200 : 409, json: async () => snapshot };
    return { ok: !!detail, status: detail ? 200 : 404, json: async () => detail };
  };
  fn.calls = calls;
  return fn;
}

function fakeShell(results) {
  const queue = [...results];
  const shell = {
    recaptureCalls: [],
    shown: [],
    goTo: [],
    webPinRecapture: async (...args) => {
      shell.recaptureCalls.push(args);
      return queue.shift();
    },
    showCustomApp: async (id) => shell.shown.push(id),
    webPinGoTo: async (...args) => {
      shell.goTo.push(args);
      return true;
    },
  };
  return shell;
}

const OK = { status: 'ok', image_b64: 'AA', text: 't', match: 'selector' };
const posts = (f) =>
  f.calls.filter((c) => c.url.endsWith('/snapshot')).map((c) => JSON.parse(c.opts.body));

test('recapture posts the snapshot with the request id and reports changed', async () => {
  const f = fakeFetch();
  const shell = fakeShell([OK]);
  const r = await wp
    .createRecapturer({ fetchFn: f, shell, sleep: async () => {} })
    .recapture('p1', { requestId: 'r1' });
  assert.deepEqual(r, { status: 'ok', changed: true, captured_at: 123, match: 'selector' });
  assert.deepEqual(posts(f)[0], {
    request_id: 'r1',
    status: 'ok',
    image_b64: 'AA',
    text: 't',
    match: 'selector',
  });
  assert.deepEqual(shell.recaptureCalls[0], ['custom-pbi', { selector: '#a' }, 'https://x.test/y']);
});

test('agent request on a hidden pane reports pane_not_visible and never switches panes', async () => {
  const f = fakeFetch();
  const shell = fakeShell([{ status: 'pane_not_visible' }]);
  const r = await wp
    .createRecapturer({ fetchFn: f, shell, sleep: async () => {} })
    .recapture('p1', { requestId: 'r1' });
  assert.equal(r.status, 'pane_not_visible');
  assert.deepEqual(shell.shown, []);
  assert.deepEqual(posts(f), [{ request_id: 'r1', status: 'pane_not_visible' }]);
});

test('user refresh on a hidden pane shows the app and retries once', async () => {
  const f = fakeFetch();
  const shell = fakeShell([{ status: 'pane_not_visible' }, OK]);
  const r = await wp
    .createRecapturer({ fetchFn: f, shell, sleep: async () => {} })
    .recapture('p1', { user: true });
  assert.equal(r.status, 'ok');
  assert.deepEqual(shell.shown, ['custom-pbi']);
  assert.equal(shell.recaptureCalls.length, 2);
  assert.equal(posts(f)[0].request_id, undefined);
});

test('user refresh gives up after one retry and posts nothing without a request id', async () => {
  const f = fakeFetch();
  const shell = fakeShell([{ status: 'pane_not_visible' }, { status: 'pane_not_visible' }]);
  const r = await wp
    .createRecapturer({ fetchFn: f, shell, sleep: async () => {} })
    .recapture('p1', { user: true });
  assert.equal(r.status, 'pane_not_visible');
  assert.equal(shell.recaptureCalls.length, 2);
  assert.deepEqual(posts(f), []);
});

// The route 404s before it resolves anything, so for a pin missing on disk the failure post is
// best effort only; the agent tool already checks the pin belongs to the tab before asking.
test('a missing pin never reaches the shell', async () => {
  const f = fakeFetch({ detail: null });
  const shell = fakeShell([]);
  const r = await wp
    .createRecapturer({ fetchFn: f, shell, sleep: async () => {} })
    .recapture('gone', { requestId: 'r9' });
  assert.equal(r.status, 'pane_unavailable');
  assert.equal(shell.recaptureCalls.length, 0);
});

test('page_mismatch carries the app and url so the card can offer Go to the pin page', async () => {
  const shell = fakeShell([{ status: 'page_mismatch' }]);
  const r = await wp
    .createRecapturer({ fetchFn: fakeFetch(), shell, sleep: async () => {} })
    .recapture('p1', { user: true });
  assert.deepEqual(r, { status: 'page_mismatch', appId: 'custom-pbi', url: 'https://x.test/y' });
});

test('a 409 on the snapshot post (request already answered) is not reported as success', async () => {
  const f = fakeFetch({ snapshot: { ok: false } });
  const shell = fakeShell([OK]);
  const r = await wp
    .createRecapturer({ fetchFn: f, shell, sleep: async () => {} })
    .recapture('p1', { requestId: 'r1' });
  assert.equal(r.status, 'pane_unavailable');
});

test('matchNote labels content and geometry-assisted matches only', () => {
  assert.match(wp.matchNote('fingerprint'), /matched it by its content/i);
  assert.match(wp.matchNote('fingerprint-geometry'), /check it is the right one/i);
  for (const m of ['stable-id', 'role-name', 'view', undefined]) assert.equal(wp.matchNote(m), '');
});

test('element_missing and element_ambiguous are posted to the server even for a user refresh', async () => {
  for (const code of ['element_missing', 'element_ambiguous']) {
    const f = fakeFetch();
    const shell = fakeShell([{ status: code }]);
    const r = await wp
      .createRecapturer({ fetchFn: f, shell, sleep: async () => {} })
      .recapture('p1', { user: true });
    assert.equal(r.status, code);
    assert.deepEqual(posts(f), [{ status: code }]);
  }
});

test('a successful recapture forwards match and confidence', async () => {
  const f = fakeFetch();
  const shell = fakeShell([{ ...OK, match: 'fingerprint', confidence: 0.82 }]);
  await wp
    .createRecapturer({ fetchFn: f, shell, sleep: async () => {} })
    .recapture('p1', { requestId: 'r1' });
  assert.equal(posts(f)[0].match, 'fingerprint');
  assert.equal(posts(f)[0].confidence, 0.82);
});

test('app.js routes webpin-recapture to the renderer and the renderer checks tab ownership', () => {
  assert.match(
    read('web', 'static', 'app.js'),
    /msg\.type === 'webpin-recapture'[\s\S]{0,300}onRecaptureRequest\(msg\)/,
  );
  assert.match(read('web', 'static', 'web-pins.js'), /_tabs\.some\(/);
});

test('a malformed snapshot reply body is reported as pane_unavailable, not thrown', async () => {
  for (const body of [null, 'x', {}]) {
    const f = async (url) =>
      url.endsWith('/snapshot')
        ? {
            ok: true,
            status: 200,
            json: async () => {
              if (body === null) throw new SyntaxError('bad');
              return body;
            },
          }
        : { ok: true, status: 200, json: async () => DETAIL };
    const shell = fakeShell([OK]);
    const r = await wp
      .createRecapturer({ fetchFn: f, shell, sleep: async () => {} })
      .recapture('p1', { requestId: 'r1' });
    assert.equal(r.status, 'pane_unavailable');
  }
});

test('a shell that throws or returns nothing still answers the waiting agent request', async () => {
  const bad = [
    async () => {
      throw new Error('ipc');
    },
    async () => undefined,
  ];
  for (const webPinRecapture of bad) {
    const f = fakeFetch();
    const r = await wp
      .createRecapturer({ fetchFn: f, shell: { webPinRecapture }, sleep: async () => {} })
      .recapture('p1', { requestId: 'r1' });
    assert.equal(r.status, 'pane_unavailable');
    assert.deepEqual(posts(f), [{ request_id: 'r1', status: 'pane_unavailable' }]);
  }
});

test('every shell failure code is forwarded to the agent unchanged', async () => {
  for (const code of [
    'timeout',
    'empty_target',
    'page_mismatch',
    'pane_unavailable',
    'pane_not_visible',
  ]) {
    const f = fakeFetch();
    const shell = fakeShell([{ status: code }]);
    const r = await wp
      .createRecapturer({ fetchFn: f, shell, sleep: async () => {} })
      .recapture('p1', { requestId: 'r1' });
    assert.equal(r.status, code);
    assert.deepEqual(posts(f), [{ request_id: 'r1', status: code }]);
  }
});

test('a shell code outside the known five falls back to pane_unavailable on the post', async () => {
  const f = fakeFetch();
  const shell = fakeShell([{ status: 'something_new' }]);
  const r = await wp
    .createRecapturer({ fetchFn: f, shell, sleep: async () => {} })
    .recapture('p1', { requestId: 'r1' });
  assert.equal(r.status, 'something_new');
  assert.deepEqual(posts(f), [{ request_id: 'r1', status: 'pane_unavailable' }]);
});

test('a success post rejected with 400/413/500 releases the waiting agent request', async () => {
  for (const status of [400, 413, 500]) {
    const calls = [];
    const f = async (url, opts = {}) => {
      calls.push({ url, opts });
      if (url.endsWith('/snapshot')) {
        const n = calls.filter((c) => c.url.endsWith('/snapshot')).length;
        return n === 1
          ? { ok: false, status, json: async () => ({}) }
          : { ok: true, status: 200, json: async () => ({ ok: false }) };
      }
      return { ok: true, status: 200, json: async () => DETAIL };
    };
    const shell = fakeShell([OK]);
    const r = await wp
      .createRecapturer({ fetchFn: f, shell, sleep: async () => {} })
      .recapture('p1', { requestId: 'r1' });
    assert.equal(r.status, 'pane_unavailable');
    const sent = calls
      .filter((c) => c.url.endsWith('/snapshot'))
      .map((c) => JSON.parse(c.opts.body));
    assert.equal(sent.length, 2, String(status));
    assert.equal(sent[0].status, 'ok');
    assert.deepEqual(sent[1], { request_id: 'r1', status: 'pane_unavailable' });
  }
});

test('a 409 or an undelivered success post sends no follow-up release', async () => {
  const f409 = fakeFetch({ snapshot: { ok: false } });
  await wp
    .createRecapturer({ fetchFn: f409, shell: fakeShell([OK]), sleep: async () => {} })
    .recapture('p1', { requestId: 'r1' });
  assert.equal(posts(f409).length, 1);
  const calls = [];
  const fNet = async (url) => {
    calls.push(url);
    if (url.endsWith('/snapshot')) throw new Error('net');
    return { ok: true, status: 200, json: async () => DETAIL };
  };
  const r = await wp
    .createRecapturer({ fetchFn: fNet, shell: fakeShell([OK]), sleep: async () => {} })
    .recapture('p1', { requestId: 'r1' });
  assert.equal(r.status, 'pane_unavailable');
  assert.equal(calls.filter((u) => u.endsWith('/snapshot')).length, 1);
});

test('a pin that has no app id still releases the waiting agent request', async () => {
  const f = fakeFetch({ detail: { meta: {} } });
  const r = await wp
    .createRecapturer({ fetchFn: f, shell: fakeShell([]), sleep: async () => {} })
    .recapture('p1', { requestId: 'r1' });
  assert.equal(r.status, 'pane_unavailable');
  assert.deepEqual(posts(f), [{ request_id: 'r1', status: 'pane_unavailable' }]);
});

test('SSE recapture request is ignored by a tab that does not own the context', async () => {
  const f = fakeFetch();
  const shell = fakeShell([OK]);
  const { env } = makeEnv({ fetchImpl: f, gatorShell: shell });
  env.WebPins.onRecaptureRequest({ request_id: 'r1', pin_id: 'p1', context_id: 'tab-zzz' });
  env.WebPins.onRecaptureRequest({ request_id: 'r1', pin_id: 'p1' });
  env.WebPins.onRecaptureRequest({ pin_id: 'p1', context_id: 'tab-a' });
  await flush();
  assert.equal(f.calls.length, 0);
  assert.equal(shell.recaptureCalls.length, 0);
});

test('SSE recapture request on an owning tab captures and answers with the request id', async () => {
  const f = fakeFetch();
  const shell = fakeShell([OK]);
  const { env } = makeEnv({ fetchImpl: f, gatorShell: shell });
  env.WebPins.onRecaptureRequest({ request_id: 'r1', pin_id: 'p1', context_id: 'tab-b' });
  await flush();
  assert.equal(shell.recaptureCalls.length, 1);
  assert.equal(posts(f)[0].request_id, 'r1');
});

test('SSE recapture request is ignored by a client without the desktop shell, so it never wins the claim', async () => {
  const f = fakeFetch();
  const { env } = makeEnv({ fetchImpl: f });
  env.WebPins.onRecaptureRequest({ request_id: 'r1', pin_id: 'p1', context_id: 'tab-a' });
  await flush();
  assert.equal(f.calls.length, 0);
  const { env: env2 } = makeEnv({ fetchImpl: f, gatorShell: {} });
  env2.WebPins.onRecaptureRequest({ request_id: 'r1', pin_id: 'p1', context_id: 'tab-a' });
  await flush();
  assert.equal(f.calls.length, 0);
});

function fakeCard() {
  const card = new FakeEl('div');
  const kids = {};
  for (const cls of ['pin-card-icon', 'pin-card-open', 'pin-card-meta', 'pin-card-ask']) {
    kids['.' + cls] = card.appendChild(new FakeEl('div'));
    kids['.' + cls].className = cls;
  }
  card.querySelector = (sel) => kids[sel] || null;
  card.insertBefore = (el, ref) => {
    card.children.splice(card.children.indexOf(ref), 0, el);
    el.parentElement = card;
  };
  return { card, kids };
}

const findRefresh = (card) => card.children.find((c) => c.classes.has('pin-card-refresh'));

test('card refresh on a different page offers a Go to link that navigates the pane', async () => {
  const shell = fakeShell([{ status: 'page_mismatch' }]);
  const { env, toasts } = makeEnv({ fetchImpl: fakeFetch(), gatorShell: shell });
  const { card, kids } = fakeCard();
  env.WebPins.decorateCard(card, { id: 'p1', meta: { app_name: 'Power BI' } });
  const refresh = findRefresh(card);
  assert.ok(refresh, 'refresh button inserted');
  refresh.click();
  await flush();
  await flush();
  const meta = kids['.pin-card-meta'];
  assert.match(meta.textContent, /^Different page/);
  const link = meta.children.find((c) => c.classes.has('wp-goto'));
  assert.ok(link);
  link.click();
  await flush();
  assert.deepEqual(shell.goTo, [['custom-pbi', 'https://x.test/y']]);
  assert.match(toasts[toasts.length - 1], /Back on the pinned page/);
  assert.equal(refresh.disabled, false);
});

test('the Go to link is re-enabled after a failed navigation so it can be retried', async () => {
  const shell = fakeShell([{ status: 'page_mismatch' }]);
  shell.webPinGoTo = async () => false;
  const { env, toasts } = makeEnv({ fetchImpl: fakeFetch(), gatorShell: shell });
  const { card, kids } = fakeCard();
  env.WebPins.decorateCard(card, { id: 'p1', meta: {} });
  findRefresh(card).click();
  await flush();
  await flush();
  const link = kids['.pin-card-meta'].children.find((c) => c.classes.has('wp-goto'));
  link.click();
  await flush();
  assert.equal(link.disabled, false);
  assert.match(toasts[toasts.length - 1], /open that page/);
});

test('card refresh error codes surface through the shared error messages', async () => {
  const shell = fakeShell([{ status: 'timeout' }]);
  const { env, toasts } = makeEnv({ fetchImpl: fakeFetch(), gatorShell: shell });
  const { card } = fakeCard();
  env.WebPins.decorateCard(card, { id: 'p1', meta: {} });
  findRefresh(card).click();
  await flush();
  await flush();
  assert.deepEqual(toasts, [env.WebPins.errorMessage('timeout')]);
});

test('results are spoken through one polite live region as well as toasted', async () => {
  const { env, toasts } = makeEnv({
    fetchImpl: async () => ({ ok: false, status: 500, json: async () => ({}) }),
  });
  env.setTimeout = (fn) => fn();
  await env.WebPins.onCaptured(payload);
  await flush();
  const live = env.document.getElementById('wp-live');
  assert.ok(live);
  assert.equal(live.attrs.role, 'status');
  assert.equal(live.attrs['aria-live'], 'polite');
  assert.equal(live.textContent, toasts[toasts.length - 1]);
  env.WebPins.onEvent && env.WebPins.onEvent({ type: 'error', code: 'element_missing' });
  assert.equal(env.document.body.all((e) => e.id === 'wp-live').length, 1);
});
