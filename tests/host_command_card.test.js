// run_on_host card: shows the exact command as text, runs only on a click, posts to the
// CSRF-guarded host-shell routes, shows the output and asks the agent to read the result.
// Functions are extracted from app.js and run against a tiny fake DOM.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function extract(name) {
  const match = source.match(
    new RegExp(`(?:async )?function ${name}\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}`),
  );
  assert(match, `${name} not found in app.js`);
  return match[0];
}

assert(!/innerHTML/.test(extract('_renderHostCommandCard')), 'no innerHTML for model text');

function makeEl(tag) {
  return {
    tag,
    children: [],
    dataset: {},
    listeners: {},
    className: '',
    disabled: false,
    hidden: false,
    _text: '',
    set innerHTML(_v) {
      throw new Error('innerHTML must never be used');
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

function makeEnv(fetchImpl) {
  const messages = makeEl('div');
  const fetches = [];
  const followUps = [];
  const toasts = [];
  const ctx = {
    document: {
      createElement: makeEl,
      getElementById: (id) => (id === 'messages' ? messages : null),
      querySelectorAll: () => walk(messages).filter((e) => e.dataset && e.dataset.sandboxRequest),
    },
    window: { __CSRF_TOKEN__: 'aigator-fake-api-key' },
    _activeTabId: 'tab-1',
    _pendingSandboxCards: new Map([['tab-1', new Map([['req1', {}]])]]),
    _tabsWithUpdates: new Set(),
    _showConnectivityToast: (msg, type) => toasts.push({ msg, type }),
    _sendSandboxFollowUp: async (tab, text) => followUps.push({ tab, text }),
    console,
    Map,
    Set,
    Array,
    String,
    JSON,
    Promise,
    encodeURIComponent,
    fetch: async (url, opts) => {
      fetches.push({ url, opts });
      return fetchImpl(url, opts);
    },
  };
  vm.createContext(ctx);
  ['_renderHostCommandCard', '_showSandboxApproval'].forEach((n) =>
    vm.runInContext(extract(n), ctx),
  );
  return { ctx, messages, fetches, followUps, toasts };
}

const evil = '<img src=x onerror=alert(1)> && echo hi';
const data = {
  request_id: 'req1',
  context_id: 'tab-1',
  tool: 'run_on_host',
  command: evil,
  cwd: 'C:/work',
  shell: 'powershell',
  reason: 'Node is not available in the sandbox',
  risks: ['Pushes commits to a remote'],
  timeout: 120,
};
const click = { stopPropagation() {} };
const tick = () => new Promise((r) => setTimeout(r, 0));
const buttonsOf = (env) => walk(env.messages).filter((e) => e.tag === 'button');

(async () => {
  const ok = async (url) =>
    url.endsWith('/run')
      ? {
          ok: true,
          status: 200,
          json: async () => ({ ok: true, result: { stdout: 'built', stderr: '', exit_code: 0 } }),
        }
      : { ok: true, status: 200, json: async () => ({ ok: true }) };

  // Render: command is plain text, nothing runs, only Run and Cancel are offered.
  const env = makeEnv(ok);
  env.ctx._showSandboxApproval(data, 'tab-1');
  assert.strictEqual(env.messages.children.length, 1);
  const all = walk(env.messages);
  assert(
    all.some((e) => e.tag === 'pre' && e.textContent === evil),
    'command rendered as text',
  );
  assert(!all.some((e) => e.tag === 'img'), 'no element created from model text');
  assert(
    all.some((e) => /Pushes commits to a remote/.test(e.textContent)),
    'risk shown',
  );
  assert(
    all.some((e) => /outside the sandbox/.test(e.textContent)),
    'states where it runs',
  );
  assert.deepStrictEqual(
    buttonsOf(env).map((b) => b.textContent),
    ['Run', 'Cancel'],
  );
  assert.strictEqual(env.fetches.length, 0, 'rendering must not run anything');

  // Same request is not drawn twice.
  env.ctx._showSandboxApproval(data, 'tab-1');
  assert.strictEqual(env.messages.children.length, 1);

  // Run: CSRF POST to the run route, output shown, agent told to read the result.
  await buttonsOf(env)[0].listeners.click(click);
  await tick();
  await tick();
  assert.strictEqual(env.fetches.length, 1);
  assert.strictEqual(env.fetches[0].url, '/api/host-shell/req1/run');
  assert.strictEqual(env.fetches[0].opts.method, 'POST');
  assert.strictEqual(env.fetches[0].opts.headers['X-CSRF-Token'], 'aigator-fake-api-key');
  assert.deepStrictEqual(JSON.parse(env.fetches[0].opts.body), { context_id: 'tab-1' });
  assert(walk(env.messages).some((e) => e.tag === 'pre' && e.textContent === 'built'));
  assert.strictEqual(buttonsOf(env).length, 0, 'buttons removed after the run');
  assert.strictEqual(env.followUps.length, 1);
  assert.match(env.followUps[0].text, /host_command_result/);
  assert.match(env.followUps[0].text, /req1/);
  assert(!env.ctx._pendingSandboxCards.get('tab-1').has('req1'), 'card not redrawn later');

  // Cancel: cancel route, agent told not to retry.
  const env2 = makeEnv(ok);
  env2.ctx._showSandboxApproval(data, 'tab-1');
  await buttonsOf(env2)[1].listeners.click(click);
  await tick();
  await tick();
  assert.strictEqual(env2.fetches[0].url, '/api/host-shell/req1/cancel');
  assert.match(env2.followUps[0].text, /Do not retry/);

  // A server refusal re-enables the buttons and does not tell the agent anything.
  const env3 = makeEnv(async () => ({
    ok: false,
    status: 409,
    json: async () => ({ detail: 'already run' }),
  }));
  env3.ctx._showSandboxApproval(data, 'tab-1');
  await buttonsOf(env3)[0].listeners.click(click);
  await tick();
  await tick();
  assert(buttonsOf(env3).every((b) => !b.disabled));
  assert.strictEqual(env3.followUps.length, 0);
  assert(env3.toasts.some((t) => /already run/.test(t.msg)));

  // CSRF 403 refreshes the token once and retries.
  let first = true;
  const env4 = makeEnv(async (url) => {
    if (url === '/api/csrf')
      return { ok: true, status: 200, json: async () => ({ csrf_token: 'aigator-fake-api-key' }) };
    if (first) {
      first = false;
      return { ok: false, status: 403, json: async () => ({}) };
    }
    return ok(url);
  });
  env4.ctx._showSandboxApproval(data, 'tab-1');
  await buttonsOf(env4)[0].listeners.click(click);
  await tick();
  await tick();
  assert.deepStrictEqual(
    env4.fetches.map((f) => f.url),
    ['/api/host-shell/req1/run', '/api/csrf', '/api/host-shell/req1/run'],
  );

  console.log('host_command_card: all assertions passed');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
