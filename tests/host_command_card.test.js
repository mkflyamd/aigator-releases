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
    attrs: {},
    setAttribute(k, v) {
      this.attrs[k] = v;
    },
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
  const clock = { ms: 1_000_000_000 };
  const timers = [];
  const ctx = {
    Date: { now: () => clock.ms },
    Math,
    Number,
    setTimeout: (fn) => setTimeout(fn, 0),
    setInterval: (fn) => timers.push({ fn, live: true }) && timers.length,
    clearInterval: (id) => {
      if (timers[id - 1]) timers[id - 1].live = false;
    },
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
  const tickClock = (seconds) => {
    clock.ms += seconds * 1000;
    timers.filter((t) => t.live).forEach((t) => t.fn());
  };
  return { ctx, messages, fetches, followUps, toasts, clock, tickClock };
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
  const reply = (body) => ({ ok: true, status: 200, json: async () => body });
  const finished = (result, state = 'finished') =>
    reply({ ok: true, run: { id: 'req1', state }, result });
  const ok = async (url, opts) =>
    opts && opts.method === 'POST'
      ? reply({ ok: true, run: { id: 'req1', state: url.endsWith('/run') ? 'running' : 'denied' } })
      : finished({ stdout: 'built', stderr: '', exit_code: 0 });

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
  assert.strictEqual(env.fetches.length, 2);
  assert.strictEqual(env.fetches[1].url, '/api/host-shell/req1?context_id=tab-1');
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
    [
      '/api/host-shell/req1/run',
      '/api/csrf',
      '/api/host-shell/req1/run',
      '/api/host-shell/req1?context_id=tab-1',
    ],
  );

  // Several lines, the AI's own folder and removed variables are all called out on the card.
  const nl = String.fromCharCode(10);
  const env5 = makeEnv(ok);
  env5.ctx._showSandboxApproval(
    {
      ...data,
      request_id: 'req5',
      command: ['echo a', 'echo b', 'echo c'].join(nl),
      cwd_is_ai_workspace: true,
      env_removed: 3,
    },
    'tab-1',
  );
  const text5 = walk(env5.messages)
    .map((e) => e.textContent)
    .join(nl);
  assert.match(text5, /3 lines/);
  assert.match(text5, /AI Gator's own working folder/);
  assert.match(text5, /3 environment variables removed/);
  assert(
    walk(env5.messages).some((e) => e.tag === 'pre' && /gcc-field-val--wrap/.test(e.className)),
    'command wraps',
  );
  const plain = walk(env.messages)
    .map((e) => e.textContent)
    .join(nl);
  assert(!/lines\./.test(plain) && !/working folder/.test(plain) && !/removed/.test(plain));

  const textOf = (e) =>
    walk(e.messages)
      .map((x) => x.textContent)
      .join(nl);

  // While a command runs, Cancel becomes Stop and calls the cancel route.
  let stopped = false;
  const env6 = makeEnv(async (url, opts) => {
    if (opts && opts.method === 'POST') {
      if (url.endsWith('/cancel')) stopped = true;
      return reply({ ok: true, run: { id: 'req1', state: stopped ? 'cancelled' : 'running' } });
    }
    return stopped
      ? finished(
          { stdout: '', stderr: '', error: 'You stopped this command', exit_code: -1 },
          'cancelled',
        )
      : reply({ ok: true, run: { id: 'req1', state: 'running' } });
  });
  env6.ctx._showSandboxApproval(data, 'tab-1');
  buttonsOf(env6)[0].listeners.click(click);
  await tick();
  await tick();
  const stopBtn = buttonsOf(env6)[1];
  assert.strictEqual(stopBtn.textContent, 'Stop');
  assert(!stopBtn.disabled, 'Stop is clickable while running');
  await stopBtn.listeners.click(click);
  for (let i = 0; i < 6; i += 1) await tick();
  assert.strictEqual(env6.fetches[0].url, '/api/host-shell/req1/run');
  assert(
    env6.fetches.some((f) => f.url === '/api/host-shell/req1/cancel'),
    'Stop posts to the cancel route',
  );
  assert(walk(env6.messages).some((e) => e.tag === 'pre' && /You stopped/.test(e.textContent)));
  assert.match(textOf(env6), /You stopped this command\./);

  // The card says when it will expire, and what happened, in plain words.
  const withExpiry = (env) => ({ ...data, expires_at: env.clock.ms / 1000 + 600 });

  // Only the last minute is counted down, and the countdown is hidden from screen readers.
  const env7 = makeEnv(ok);
  env7.ctx._showSandboxApproval(withExpiry(env7), 'tab-1');
  env7.tickClock(300);
  assert(!/Expires in/.test(textOf(env7)), 'no countdown until the last minute');
  env7.tickClock(245);
  assert.match(textOf(env7), /Expires in 0:55/);
  assert(
    walk(env7.messages).some(
      (e) => /Expires in/.test(e.textContent) && e.attrs['aria-hidden'] === 'true',
    ),
    'countdown is aria-hidden',
  );

  // When the time runs out the card says nothing was run and offers Ask again.
  env7.tickClock(60);
  assert.match(textOf(env7), /Timed out before you answered. Nothing was run./);
  assert(!/Expires in/.test(textOf(env7)));
  assert.deepStrictEqual(
    buttonsOf(env7).map((b) => b.textContent),
    ['Ask again'],
  );
  assert.strictEqual(env7.fetches.length, 0, 'expiring calls nothing');
  assert.strictEqual(env7.followUps.length, 0, 'expiring tells the agent nothing');
  assert(
    walk(env7.messages).some((e) => e.attrs.role === 'status' && /Timed out/.test(e.textContent)),
    'expiry is announced once',
  );
  assert(!env7.ctx._pendingSandboxCards.get('tab-1').has('req1'), 'expired card not redrawn');
  await buttonsOf(env7)[0].listeners.click(click);
  await tick();
  assert.deepStrictEqual(
    env7.followUps.map((f) => f.text),
    ['Please propose that command again.'],
  );
  assert(buttonsOf(env7)[0].disabled, 'Ask again is sent once');
  await buttonsOf(env7)[0].listeners.click(click);
  assert.strictEqual(env7.followUps.length, 1);

  // A Run that arrives too late (404 or 410) lands in the same expired state.
  for (const status of [404, 410]) {
    const late = makeEnv(async () => ({
      ok: false,
      status,
      json: async () => ({ detail: 'This command request expired.' }),
    }));
    late.ctx._showSandboxApproval(data, 'tab-1');
    await buttonsOf(late)[0].listeners.click(click);
    await tick();
    await tick();
    assert.match(textOf(late), /Timed out before you answered/);
    assert.deepStrictEqual(
      buttonsOf(late).map((b) => b.textContent),
      ['Ask again'],
    );
    assert.strictEqual(late.followUps.length, 0);
  }

  // If AI Gator cannot be reached, Run and Cancel stay and the card says so.
  for (const failure of [
    async () => {
      throw new TypeError('Failed to fetch');
    },
    async () => ({ ok: false, status: 503, json: async () => ({}) }),
  ]) {
    const down = makeEnv(failure);
    down.ctx._showSandboxApproval(data, 'tab-1');
    await buttonsOf(down)[0].listeners.click(click);
    await tick();
    await tick();
    assert.match(textOf(down), /Couldn't reach AI Gator. Try again./);
    assert.deepStrictEqual(
      buttonsOf(down).map((b) => b.textContent),
      ['Run', 'Cancel'],
    );
    assert(buttonsOf(down).every((b) => !b.disabled));
    assert.strictEqual(down.followUps.length, 0);
  }

  // The buttons are off while a request is in flight.
  let settle = () => {};
  const slow = makeEnv(
    () =>
      new Promise((resolve) => {
        settle = () => resolve({ ok: true, status: 200, json: async () => ({ ok: true }) });
      }),
  );
  slow.ctx._showSandboxApproval(data, 'tab-1');
  const slowCancel = buttonsOf(slow)[1].listeners.click(click);
  await tick();
  assert(
    buttonsOf(slow).every((b) => b.disabled),
    'both buttons off while cancelling',
  );
  settle();
  await slowCancel;
  await tick();
  assert.match(textOf(slow), /You cancelled this. Nothing was run./);

  // A non-zero exit code reads as a failure, zero as finished.
  const failed = makeEnv(async (url, opts) =>
    opts && opts.method === 'POST'
      ? reply({ ok: true, run: { id: 'req1', state: 'running' } })
      : finished({ stdout: '', stderr: 'boom', exit_code: 2 }),
  );
  failed.ctx._showSandboxApproval(data, 'tab-1');
  await buttonsOf(failed)[0].listeners.click(click);
  await tick();
  await tick();
  assert.match(textOf(failed), /Failed · exit code 2/);
  assert.match(textOf(env), /Finished · exit code 0/);

  // The card polls a running command until its record ends, then says how it ended.
  let polls = 0;
  const slowRun = makeEnv(async (url, opts) => {
    if (opts && opts.method === 'POST')
      return reply({ ok: true, run: { id: 'req1', state: 'running' } });
    polls += 1;
    return polls < 3
      ? reply({ ok: true, run: { id: 'req1', state: 'running' } })
      : finished({ stdout: 'late output', stderr: '', exit_code: 0 });
  });
  slowRun.ctx._showSandboxApproval(data, 'tab-1');
  buttonsOf(slowRun)[0].listeners.click(click);
  for (let i = 0; i < 12; i += 1) await tick();
  assert(polls >= 3, 'kept polling while the record was running');
  assert.match(textOf(slowRun), /Finished · exit code 0/);
  assert.strictEqual(slowRun.followUps.length, 1);

  // Each end state is described plainly and the output captured so far is kept.
  const endings = [
    ['timed_out', /Timed out/],
    ['cancelled', /You stopped this command\./],
    ['policy_blocked', /administrator/],
    ['interrupted', /restarted/],
  ];
  for (const [state, pattern] of endings) {
    const ended = makeEnv(async (url, opts) =>
      opts && opts.method === 'POST'
        ? reply({ ok: true, run: { id: 'req1', state: 'running' } })
        : finished({ stdout: 'partial', stderr: '', exit_code: -1 }, state),
    );
    ended.ctx._showSandboxApproval(data, 'tab-1');
    await buttonsOf(ended)[0].listeners.click(click);
    await tick();
    await tick();
    assert.match(textOf(ended), pattern, state);
    assert(walk(ended.messages).some((e) => e.tag === 'pre' && e.textContent === 'partial'));
  }

  // A refused start says why.
  const refused = { id: 'req1', state: 'failed_to_start', reason: 'concurrency_cap' };
  const capped = makeEnv(async (url, opts) =>
    opts && opts.method === 'POST'
      ? reply({ ok: true, run: refused })
      : reply({
          ok: true,
          run: refused,
          result: { error: 'concurrency_cap', stdout: '', stderr: '', exit_code: -1 },
        }),
  );
  capped.ctx._showSandboxApproval(data, 'tab-1');
  await buttonsOf(capped)[0].listeners.click(click);
  await tick();
  await tick();
  assert.match(textOf(capped), /too many commands are already running/);

  // A card drawn again after a tab switch asks which run it belongs to, instead of offering a fresh Run.
  const listing = (state) => (url) =>
    url.startsWith('/api/runs?')
      ? reply({
          ok: true,
          runs: [
            { id: 'other', state: 'finished' },
            { id: 'req1', state },
          ],
        })
      : null;

  let polled = 0;
  const rejoin = makeEnv(async (url, opts) => {
    const listed = listing('running')(url);
    if (listed) return listed;
    polled += 1;
    return polled < 2
      ? reply({ ok: true, run: { id: 'req1', state: 'running' } })
      : finished({ stdout: 'done while away', stderr: '', exit_code: 0 });
  });
  rejoin.ctx._showSandboxApproval(data, 'tab-1', true);
  await tick();
  assert.strictEqual(rejoin.fetches[0].url, '/api/runs?context_id=tab-1');
  assert.deepStrictEqual(
    buttonsOf(rejoin).map((b) => [b.textContent, b.disabled]),
    [
      ['Run', true],
      ['Stop', false],
    ],
    'a running command offers Stop, not a second Run',
  );
  for (let i = 0; i < 12; i += 1) await tick();
  assert(
    !rejoin.fetches.some((f) => f.opts && f.opts.method === 'POST'),
    'rejoining posts nothing',
  );
  assert.match(textOf(rejoin), /Finished · exit code 0/);
  assert(walk(rejoin.messages).some((e) => e.tag === 'pre' && e.textContent === 'done while away'));
  assert.strictEqual(rejoin.followUps.length, 0, 'the first card already tells the agent');

  const over = makeEnv(
    async (url) =>
      listing('timed_out')(url) ||
      finished({ stdout: 'partial', stderr: '', exit_code: -1 }, 'timed_out'),
  );
  over.ctx._showSandboxApproval(data, 'tab-1', true);
  for (let i = 0; i < 4; i += 1) await tick();
  assert.strictEqual(buttonsOf(over).length, 0);
  assert.match(textOf(over), /Timed out/);

  const declined = makeEnv(async (url) => listing('denied')(url));
  declined.ctx._showSandboxApproval(data, 'tab-1', true);
  for (let i = 0; i < 4; i += 1) await tick();
  assert.strictEqual(buttonsOf(declined).length, 0);
  assert.match(textOf(declined), /You cancelled this. Nothing was run./);

  const waiting = makeEnv(async (url) => listing('awaiting_approval')(url));
  waiting.ctx._showSandboxApproval(data, 'tab-1', true);
  for (let i = 0; i < 4; i += 1) await tick();
  assert.deepStrictEqual(
    buttonsOf(waiting).map((b) => [b.textContent, b.disabled]),
    [
      ['Run', false],
      ['Cancel', false],
    ],
  );

  console.log('host_command_card: all assertions passed');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
