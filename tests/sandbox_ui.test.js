// Code-runner sandbox UI: approval card follow-up text, Settings notice text,
// and the rule that model-supplied strings are never put through innerHTML.
// Functions are extracted from app.js and run in isolation against a tiny fake DOM.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function extract(name) {
  const match = source.match(new RegExp(`(?:async )?function ${name}\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}`));
  assert(match, `${name} not found in app.js`);
  return match[0];
}

const followUp = vm.runInNewContext(extract('_sandboxFollowUpText') + '; _sandboxFollowUpText;', {});
const notice = vm.runInNewContext(extract('_sandboxNoticeText') + '; _sandboxNoticeText;', {});

assert.match(followUp('approve', 'abc123'), /approved sandbox access request abc123/);
assert.match(followUp('approve', 'abc123'), /exactly the same/);
assert.match(followUp('deny', 'abc123'), /denied sandbox access request abc123/);
assert.match(followUp('deny', 'abc123'), /Do not retry/);

assert.strictEqual(notice({ level: 'enforced', reason: null, opted_out: false, policy: {} }), '');
assert.strictEqual(notice(null), '');
assert.match(
  notice({ level: 'unavailable', reason: 'Install bubblewrap.', opted_out: false, policy: {} }),
  /Install bubblewrap\..*blocked/,
);
assert.match(
  notice({ level: 'unavailable', reason: 'x', opted_out: true, policy: { require_sandbox: false } }),
  /without a sandbox/,
);
assert.match(
  notice({ level: 'unavailable', reason: 'x', opted_out: true, policy: { require_sandbox: true } }),
  /blocked/,
);

for (const name of ['_showSandboxApproval', '_initSandboxSettings', '_sendSandboxFollowUp']) {
  assert(!/innerHTML/.test(extract(name)), `${name} must not use innerHTML`);
}
assert(source.includes('_showSandboxApproval(msg.sandbox_approval, requestTabId)'));
assert(source.includes('  _initSandboxSettings();'));
assert(!/alert\(/.test(extract('_initSandboxSettings')), 'opt-out failure uses a toast, not alert()');

// ── Behaviour against a fake DOM ─────────────────────────────────────────────
function makeEl(tag) {
  const el = {
    tag,
    children: [],
    dataset: {},
    listeners: {},
    className: '',
    disabled: false,
    _text: '',
    set innerHTML(_v) {
      throw new Error('innerHTML must never be used for sandbox UI');
    },
    set textContent(v) {
      this._text = String(v);
      this.children = [];
    },
    get childNodes() {
      return this.children;
    },
    replaceChildren(...cs) {
      this._text = '';
      this.children = [];
      cs.forEach((c) => this.appendChild(c));
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
  return el;
}

function walk(el, out = []) {
  out.push(el);
  el.children.forEach((c) => walk(c, out));
  return out;
}

function makeEnv(activeTab) {
  const messages = makeEl('div');
  const input = makeEl('div');
  const form = makeEl('form');
  form.submits = 0;
  form.sent = [];
  // Like the real submit handler: read the composer now, clear it one microtask later.
  form.requestSubmit = () => {
    form.submits += 1;
    form.sent.push(input.textContent);
    Promise.resolve().then(() => input.replaceChildren());
  };
  const byId = { messages, 'chat-input': input, 'chat-form': form };
  const toasts = [];
  const fetches = [];
  const ctx = {
    document: {
      createElement: makeEl,
      getElementById: (id) => byId[id] || null,
      querySelectorAll: () => walk(messages).filter((e) => e.dataset && e.dataset.sandboxRequest),
    },
    window: { __CSRF_TOKEN__: 'aigator-fake-api-key' },
    _activeTabId: activeTab,
    _chatTaskIds: new Map(),
    _pendingSandboxFollowUps: new Map(),
    setTimeout,
    Map,
    _showConnectivityToast: (msg, type) => toasts.push({ msg, type }),
    fetch: async (url, opts) => {
      fetches.push({ url, opts });
      return { ok: true, status: 200, json: async () => ({ ok: true }) };
    },
    encodeURIComponent,
    JSON,
    Array,
    String,
    Promise,
  };
  vm.createContext(ctx);
  ['_sandboxFollowUpText', '_sendSandboxFollowUp', '_flushSandboxFollowUp', '_showSandboxApproval'].forEach((n) =>
    vm.runInContext(extract(n), ctx),
  );
  return { ctx, messages, input, form, toasts, fetches };
}

const evilPath = '<img src=x onerror=alert(1)>C:/data';
const evilHost = '<script>evil()</script>.example.com';
const card = {
  request_id: 'req1',
  read_paths: [evilPath],
  write_paths: [],
  network_hosts: [evilHost],
  context_id: 'tab-1',
};

const tick = () => new Promise((r) => setTimeout(r, 0));
const flush = async () => {
  await tick();
  await tick();
};

(async () => {
  // Render: model-chosen text lands in textContent only; nothing is sent until a click.
  const env = makeEnv('tab-1');
  env.ctx._showSandboxApproval(card, 'tab-1');
  assert.strictEqual(env.messages.children.length, 1);
  const all = walk(env.messages);
  assert(all.some((e) => e.tag === 'li' && e.textContent === evilPath), 'path rendered as text');
  assert(all.some((e) => e.tag === 'li' && e.textContent === evilHost), 'host rendered as text');
  assert(!all.some((e) => e.tag === 'img' || e.tag === 'script'), 'no elements created from model text');
  assert.strictEqual(env.fetches.length, 0, 'rendering must not send any decision');
  assert.strictEqual(env.form.submits, 0, 'rendering must not send a chat message');

  // Same request is not drawn twice.
  env.ctx._showSandboxApproval(card, 'tab-1');
  assert.strictEqual(env.messages.children.length, 1);

  // Approve: CSRF POST for the right request, then exactly one ordinary chat turn.
  const buttons = all.filter((e) => e.tag === 'button');
  assert.deepStrictEqual(buttons.map((b) => b.textContent), ['Approve', 'Deny']);
  await buttons[0].listeners.click({ stopPropagation() {} });
  await flush();
  assert.strictEqual(env.fetches.length, 1);
  assert.strictEqual(env.fetches[0].url, '/api/sandbox/requests/req1/approve');
  assert.strictEqual(env.fetches[0].opts.method, 'POST');
  assert.strictEqual(env.fetches[0].opts.headers['X-CSRF-Token'], 'aigator-fake-api-key');
  assert.deepStrictEqual(JSON.parse(env.fetches[0].opts.body), { context_id: 'tab-1' });
  assert.strictEqual(env.form.submits, 1);
  assert.match(env.form.sent[0], /approved sandbox access request req1/);

  // Deny goes to the deny route and tells the model not to retry.
  const env2 = makeEnv('tab-1');
  env2.ctx._showSandboxApproval({ ...card, request_id: 'req2' }, 'tab-1');
  const deny = walk(env2.messages).filter((e) => e.tag === 'button')[1];
  await deny.listeners.click({ stopPropagation() {} });
  await flush();
  assert.strictEqual(env2.fetches[0].url, '/api/sandbox/requests/req2/deny');
  assert.match(env2.form.sent[0], /Do not retry/);

  // A failed decision sends no follow-up and re-enables the buttons.
  const env3 = makeEnv('tab-1');
  env3.ctx.fetch = async () => ({ ok: false, status: 409, json: async () => ({ detail: 'already approved' }) });
  env3.ctx._showSandboxApproval({ ...card, request_id: 'req3' }, 'tab-1');
  const btns3 = walk(env3.messages).filter((e) => e.tag === 'button');
  await btns3[0].listeners.click({ stopPropagation() {} });
  await flush();
  assert.strictEqual(env3.form.submits, 0);
  assert(!btns3[0].disabled && !btns3[1].disabled);
  assert.strictEqual(env3.toasts.length, 1);

  // A card owned by another tab is never drawn in the active tab's chat.
  const env4 = makeEnv('tab-2');
  env4.ctx._showSandboxApproval(card, 'tab-1');
  assert.strictEqual(env4.messages.children.length, 0);
  assert.strictEqual(env4.form.submits, 0);
  assert.match(env4.toasts[0].msg, /run it again in that tab/);

  // The follow-up goes only to its own tab; elsewhere it is a toast, not a chat turn.
  const env5 = makeEnv('tab-2');
  env5.ctx._sendSandboxFollowUp('tab-1', 'hello');
  assert.strictEqual(env5.form.submits, 0);
  assert.strictEqual(env5.toasts.length, 1);

  // The POST uses the server's context id even when it differs from the tab id.
  const env6 = makeEnv('tab-1');
  env6.ctx._showSandboxApproval({ ...card, request_id: 'req6', context_id: 'ctx-from-server' }, 'tab-1');
  await walk(env6.messages).filter((e) => e.tag === 'button')[0].listeners.click({ stopPropagation() {} });
  await flush();
  assert.deepStrictEqual(JSON.parse(env6.fetches[0].opts.body), { context_id: 'ctx-from-server' });

  // A second click while the first is in flight does not send a second POST.
  const env7 = makeEnv('tab-1');
  env7.ctx._showSandboxApproval({ ...card, request_id: 'req7' }, 'tab-1');
  const b7 = walk(env7.messages).filter((e) => e.tag === 'button');
  b7[0].listeners.click({ stopPropagation() {} });
  b7[0].listeners.click({ stopPropagation() {} });
  b7[1].listeners.click({ stopPropagation() {} });
  await flush();
  assert.strictEqual(env7.fetches.length, 1);
  assert.strictEqual(env7.form.submits, 1);

  // Streaming tab: the composer is untouched and nothing is submitted until the
  // stream-finished hook flushes the queued follow-up, exactly once.
  const env8 = makeEnv('tab-1');
  const draft = makeEl('span');
  draft.textContent = 'my unfinished draft';
  env8.input.appendChild(draft);
  env8.ctx._chatTaskIds.set('tab-1', 'task-1');
  env8.ctx._sendSandboxFollowUp('tab-1', 'follow up A');
  await flush();
  assert.strictEqual(env8.form.submits, 0);
  assert.strictEqual(env8.input.textContent, 'my unfinished draft');
  assert.strictEqual(env8.ctx._pendingSandboxFollowUps.get('tab-1'), 'follow up A');
  env8.ctx._flushSandboxFollowUp('tab-1'); // still streaming: stays queued
  await flush();
  assert.strictEqual(env8.form.submits, 0);
  env8.ctx._chatTaskIds.delete('tab-1');
  env8.ctx._flushSandboxFollowUp('tab-1');
  env8.ctx._flushSandboxFollowUp('tab-1');
  await flush();
  assert.strictEqual(env8.form.submits, 1);
  assert.deepStrictEqual(env8.form.sent, ['follow up A']);
  // The user's draft is back in the composer after the send.
  assert.strictEqual(env8.input.textContent, 'my unfinished draft');

  // Queued follow-up for a tab the user is not viewing waits for that tab.
  const env9 = makeEnv('tab-2');
  env9.ctx._pendingSandboxFollowUps.set('tab-1', 'later');
  env9.ctx._flushSandboxFollowUp('tab-1');
  await flush();
  assert.strictEqual(env9.form.submits, 0);
  assert.strictEqual(env9.ctx._pendingSandboxFollowUps.get('tab-1'), 'later');

  // Idle tab: submitted immediately and the draft is preserved.
  const env10 = makeEnv('tab-1');
  const draft10 = makeEl('span');
  draft10.textContent = 'half-typed';
  env10.input.appendChild(draft10);
  env10.ctx._sendSandboxFollowUp('tab-1', 'follow up B');
  await flush();
  assert.deepStrictEqual(env10.form.sent, ['follow up B']);
  assert.strictEqual(env10.input.textContent, 'half-typed');
  assert.strictEqual(env10.ctx._pendingSandboxFollowUps.size, 0);

  console.log('sandbox_ui: all assertions passed');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
