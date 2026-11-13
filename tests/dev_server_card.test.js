// Dev server status card: where it runs, an Open link only for localhost URLs, Stop with the CSRF
// token, and polling that turns the card into "Stopped". Functions are extracted from app.js
// and run against a tiny fake DOM, as in sandbox_ui.test.js.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');
const panes = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'agents-pane.js'),
  'utf8',
);

function extract(name) {
  const match = source.match(
    new RegExp(`(?:async )?function ${name}\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}`),
  );
  assert(match, `${name} not found in app.js`);
  return match[0];
}

function makeEl(tag) {
  return {
    tag,
    children: [],
    dataset: {},
    listeners: {},
    className: '',
    disabled: false,
    isConnected: true,
    _text: '',
    set innerHTML(_v) {
      throw new Error('innerHTML must never be used for the dev server card');
    },
    set textContent(v) {
      this._text = String(v);
      this.children = [];
    },
    get textContent() {
      return this._text + this.children.map((c) => c.textContent).join('');
    },
    appendChild(c) {
      this.children.push(c);
      c.parent = this;
      return c;
    },
    append(...cs) {
      cs.forEach((c) => this.appendChild(c));
    },
    addEventListener(type, fn) {
      this.listeners[type] = fn;
    },
    remove() {
      this.isConnected = false;
      if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this);
    },
    scrollIntoView() {},
  };
}

function walk(el, out = []) {
  out.push(el);
  el.children.forEach((c) => walk(c, out));
  return out;
}

function makeEnv({ activeTab = 'tab-1', processes = [] } = {}) {
  const messages = makeEl('div');
  const toasts = [];
  const fetches = [];
  const timers = [];
  const state = { processes, stopStatus: 200 };
  const ctx = {
    document: {
      createElement: makeEl,
      getElementById: (id) => (id === 'messages' ? messages : null),
      querySelectorAll: () => walk(messages).filter((e) => e.dataset && e.dataset.devServerPid),
    },
    window: { __CSRF_TOKEN__: 'aigator-fake-api-key' },
    _activeTabId: activeTab,
    _showConnectivityToast: (msg, type) => toasts.push({ msg, type }),
    setInterval: (fn, ms) => {
      timers.push({ fn, ms, cleared: false });
      return timers.length - 1;
    },
    clearInterval: (id) => {
      if (timers[id]) timers[id].cleared = true;
    },
    fetch: async (url, opts = {}) => {
      fetches.push({ url, method: opts.method || 'GET', headers: opts.headers });
      if (url === '/api/shell/background-processes') {
        return { ok: true, status: 200, json: async () => ({ processes: state.processes }) };
      }
      return { ok: state.stopStatus < 400, status: state.stopStatus, json: async () => ({}) };
    },
    encodeURIComponent,
    Number,
    String,
    Array,
    Promise,
  };
  vm.createContext(ctx);
  ['_postBackgroundStop', '_devServerUrl', '_showDevServerCard'].forEach((n) =>
    vm.runInContext(extract(n), ctx),
  );
  return { ctx, messages, toasts, fetches, timers, state };
}

const titleOf = (env) => walk(env.messages).find((e) => e.className === 'gcc-title')._text;
const buttonsOf = (env) => walk(env.messages).filter((e) => e.tag === 'button');
const linkOf = (env) => walk(env.messages).find((e) => e.tag === 'a');
const click = { stopPropagation() {} };

(async () => {
  const url = 'http://127.0.0.1:3030';

  // Only plain localhost origins pass; look-alike hosts and other schemes do not.
  const probe = makeEnv();
  for (const ok of [url, 'http://localhost:5173/', 'http://[::1]:8080', 'https://localhost:443/x']) {
    assert.strictEqual(probe.ctx._devServerUrl(ok), ok);
  }
  for (const bad of [
    'http://localhost.evil.com:80',
    'http://evil.com:3000',
    'http://localhost:3030@evil.com',
    'http://localhost:3030.evil.com',
    'http://localhost',
    'javascript:alert(1)',
    '',
    undefined,
    null,
    42,
  ]) {
    assert.strictEqual(probe.ctx._devServerUrl(bad), '', String(bad));
  }

  // With a url: title, an Open link that leaves the app safely, and a Stop button. Drawn once.
  const a = makeEnv();
  a.ctx._showDevServerCard({ pid: 7, url, command: 'npm run dev' }, 'tab-1');
  assert.strictEqual(a.messages.children.length, 1);
  assert.strictEqual(titleOf(a), `Running at ${url}`);
  const link = linkOf(a);
  assert.strictEqual(link.href, url);
  assert.strictEqual(link.target, '_blank');
  assert.match(link.rel, /noopener/);
  assert.strictEqual(link.textContent, 'Open');
  assert.deepStrictEqual(
    buttonsOf(a).map((b) => b.textContent),
    ['Stop'],
  );
  assert.strictEqual(a.fetches.length, 0, 'drawing the card sends nothing');
  assert.strictEqual(a.timers.length, 1);
  assert.strictEqual(a.timers[0].ms, 5000);
  a.ctx._showDevServerCard({ pid: 7, url }, 'tab-1');
  assert.strictEqual(a.messages.children.length, 1, 'same pid is not drawn twice');
  assert.strictEqual(a.timers.length, 1);

  // A url that is not localhost is shown without a link; no url shows the pid.
  const evil = makeEnv();
  evil.ctx._showDevServerCard({ pid: 8, url: 'http://localhost.evil.com:80' }, 'tab-1');
  assert.strictEqual(titleOf(evil), 'Running (pid 8)');
  assert.strictEqual(linkOf(evil), undefined);
  const bare = makeEnv();
  bare.ctx._showDevServerCard({ pid: 9, url: null }, 'tab-1');
  assert.strictEqual(titleOf(bare), 'Running (pid 9)');
  assert.strictEqual(linkOf(bare), undefined);
  assert.deepStrictEqual(
    buttonsOf(bare).map((b) => b.textContent),
    ['Stop'],
  );

  // Nothing is drawn without a pid, or for a tab the user is not looking at.
  const none = makeEnv();
  none.ctx._showDevServerCard({}, 'tab-1');
  assert.strictEqual(none.messages.children.length, 0);
  const other = makeEnv({ activeTab: 'tab-2' });
  other.ctx._showDevServerCard({ pid: 7, url }, 'tab-1');
  assert.strictEqual(other.messages.children.length, 0);
  assert.strictEqual(other.toasts.length, 1);

  // Stop: CSRF POST for this pid, then the card says Stopped and drops its buttons.
  const s = makeEnv();
  s.ctx._showDevServerCard({ pid: 7, url }, 'tab-1');
  await buttonsOf(s)[0].listeners.click(click);
  assert.strictEqual(s.fetches[0].url, '/api/shell/background-processes/7/stop');
  assert.strictEqual(s.fetches[0].method, 'POST');
  assert.strictEqual(s.fetches[0].headers['X-CSRF-Token'], 'aigator-fake-api-key');
  assert.strictEqual(titleOf(s), 'Stopped');
  assert.strictEqual(buttonsOf(s).length, 0);
  assert.strictEqual(linkOf(s), undefined);
  assert.strictEqual(s.timers[0].cleared, true);

  // A failed Stop keeps the card, re-enables the button and says so. 404 means already gone.
  const f = makeEnv();
  f.state.stopStatus = 500;
  f.ctx._showDevServerCard({ pid: 7, url }, 'tab-1');
  const stop = buttonsOf(f)[0];
  await stop.listeners.click(click);
  assert.strictEqual(stop.disabled, false);
  assert.strictEqual(titleOf(f), `Running at ${url}`);
  assert.strictEqual(f.toasts.length, 1);
  f.state.stopStatus = 404;
  await stop.listeners.click(click);
  assert.strictEqual(titleOf(f), 'Stopped');

  // Polling: a running pid leaves the card alone; a missing or not-running pid ends it.
  const p = makeEnv({ processes: [{ pid: 7, running: true }] });
  p.ctx._showDevServerCard({ pid: 7, url }, 'tab-1');
  await p.timers[0].fn();
  assert.strictEqual(p.fetches[0].url, '/api/shell/background-processes');
  assert.strictEqual(titleOf(p), `Running at ${url}`);
  p.state.processes = [{ pid: 7, running: false }];
  await p.timers[0].fn();
  assert.strictEqual(titleOf(p), 'Stopped');
  assert.strictEqual(p.timers[0].cleared, true);
  const gone = makeEnv({ processes: [] });
  gone.ctx._showDevServerCard({ pid: 7, url }, 'tab-1');
  await gone.timers[0].fn();
  assert.strictEqual(titleOf(gone), 'Stopped');

  // A card that left the page stops polling; a failed poll changes nothing.
  const left = makeEnv();
  left.ctx._showDevServerCard({ pid: 7, url }, 'tab-1');
  left.messages.children[0].remove();
  await left.timers[0].fn();
  assert.strictEqual(left.fetches.length, 0);
  assert.strictEqual(left.timers[0].cleared, true);
  const down = makeEnv();
  down.ctx._showDevServerCard({ pid: 7, url }, 'tab-1');
  down.ctx.fetch = async () => {
    throw new Error('offline');
  };
  await down.timers[0].fn();
  assert.strictEqual(titleOf(down), `Running at ${url}`);

  // A stale CSRF token is refreshed once and the stop is retried with the new one.
  const r = makeEnv();
  const seen = [];
  let posts = 0;
  r.ctx.fetch = async (u, opts = {}) => {
    seen.push({ u, token: opts.headers && opts.headers['X-CSRF-Token'] });
    if (u === '/api/csrf') {
      return { ok: true, status: 200, json: async () => ({ csrf_token: 'fresh-token' }) };
    }
    posts += 1;
    return { ok: posts > 1, status: posts > 1 ? 200 : 403, json: async () => ({}) };
  };
  const res = await r.ctx._postBackgroundStop(7);
  assert.strictEqual(res.status, 200);
  assert.deepStrictEqual(
    seen.map((x) => x.u),
    [
      '/api/shell/background-processes/7/stop',
      '/api/csrf',
      '/api/shell/background-processes/7/stop',
    ],
  );
  assert.strictEqual(seen[0].token, 'aigator-fake-api-key');
  assert.strictEqual(seen[2].token, 'fresh-token');

  // Wiring and safety.
  for (const name of ['_postBackgroundStop', '_devServerUrl', '_showDevServerCard']) {
    assert(!/innerHTML/.test(extract(name)), `${name} must not use innerHTML`);
  }
  assert(source.includes('_showDevServerCard(msg.dev_server, requestTabId)'));
  assert(panes.includes('_postBackgroundStop(proc.pid)'), 'agents pane stops through the helper');
  assert(!/background-processes\/\$\{proc\.pid\}\/stop/.test(panes), 'no bare stop fetch left');

  console.log('dev_server_card: all assertions passed');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
