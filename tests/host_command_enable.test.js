// Running commands on this computer is off by default. The chat card, the Settings row and the
// chip all go through the CSRF-guarded host-shell routes. Functions are extracted from app.js and
// run against a tiny fake DOM and a fake server.

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

const FUNCTIONS = [
  '_hostEl',
  '_hostDot',
  '_hostSay',
  '_hostShellCall',
  '_hostShellApply',
  '_hostShellSchedule',
  '_hostShellRefresh',
  '_hostElapsed',
  '_hostShellTick',
  '_hostShellRender',
  '_hostShellRenderSettings',
  '_hostShellRenderChip',
  '_hostShellStop',
  '_hostShellSetEnabled',
  '_initHostShell',
  '_renderHostEnableCard',
  '_renderHostCommandCard',
  '_showSandboxApproval',
];
FUNCTIONS.forEach((n) => {
  assert(!/innerHTML/.test(extract(n)), `${n} must not use innerHTML`);
});

function matches(el, sel) {
  if (sel.startsWith('.')) return (el.className || '').split(/\s+/).includes(sel.slice(1));
  const attr = sel.match(/^\[data-([a-z]+)(?:="([^"]*)")?\]$/);
  if (!attr) throw new Error(`selector not supported: ${sel}`);
  const value = el.dataset ? el.dataset[attr[1]] : undefined;
  return attr[2] === undefined ? value !== undefined : value === attr[2];
}

function walk(el, out = []) {
  out.push(el);
  el.children.forEach((c) => walk(c, out));
  return out;
}

function makeDom() {
  const byId = {};
  const doc = {
    activeElement: null,
    listeners: {},
    addEventListener(type, fn) {
      this.listeners[type] = fn;
    },
    createTextNode(text) {
      return { tag: '#text', children: [], dataset: {}, textContent: String(text) };
    },
    getElementById: (id) => byId[id] || null,
    querySelectorAll: (sel) =>
      byId['host-chip-slot'] ? byId['host-chip-slot'].querySelectorAll(sel) : [],
  };
  function makeEl(tag) {
    const el = {
      tag,
      children: [],
      dataset: {},
      listeners: {},
      attrs: {},
      className: '',
      disabled: false,
      tabIndex: 0,
      title: '',
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
        c.parent = this;
        this.children.push(c);
        return c;
      },
      append(...cs) {
        cs.forEach((c) => this.appendChild(c));
      },
      replaceChildren(...cs) {
        this.children = [];
        this._text = '';
        this.append(...cs);
      },
      addEventListener(type, fn) {
        this.listeners[type] = fn;
      },
      setAttribute(k, v) {
        this.attrs[k] = String(v);
      },
      getAttribute(k) {
        return this.attrs[k];
      },
      remove() {
        if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this);
      },
      focus() {
        doc.activeElement = this;
      },
      scrollIntoView() {},
      contains(node) {
        return walk(this).includes(node);
      },
      querySelectorAll(sel) {
        return walk(this).filter((e) => e !== this && e.tag !== '#text' && matches(e, sel));
      },
      querySelector(sel) {
        return this.querySelectorAll(sel)[0] || null;
      },
      closest(sel) {
        for (let e = this; e; e = e.parent) if (e.tag !== '#text' && matches(e, sel)) return e;
        return null;
      },
    };
    return el;
  }
  doc.createElement = makeEl;
  ['host-chip-slot', 'host-chip-sr', 'host-shell-switch', 'host-shell-status', 'messages'].forEach(
    (id) => {
      byId[id] = makeEl('div');
      byId[id].id = id;
    },
  );
  byId['host-shell-switch'].tag = 'button';
  return { doc, byId };
}

function makeServer() {
  return {
    enabled: false,
    admin: false,
    running: [],
    failEnableOnce: false,
    calls: [],
    csrfRefreshes: 0,
    status() {
      return {
        state: this.admin ? 'admin_off' : this.enabled ? 'on' : 'off',
        running: this.running,
      };
    },
    handle(url, opts = {}) {
      const method = opts.method || 'GET';
      const token = opts.headers && opts.headers['X-CSRF-Token'];
      const body = opts.body ? JSON.parse(opts.body) : null;
      this.calls.push({ method, url, token, body });
      const reply = (status, json) => ({ ok: status < 400, status, json: async () => json });
      if (url === '/api/csrf') return reply(200, { csrf_token: 'aigator-fake-api-key' });
      if (url === '/api/host-shell/status') return reply(200, this.status());
      if (method !== 'GET' && token !== 'aigator-fake-api-key') {
        return reply(403, { detail: 'CSRF token missing or invalid' });
      }
      if (url === '/api/host-shell/enabled') {
        if (this.admin) {
          return reply(403, {
            detail: 'Your administrator has turned off running commands on this computer.',
          });
        }
        if (body.enabled && this.failEnableOnce) {
          this.failEnableOnce = false;
          return reply(500, { detail: 'boom' });
        }
        this.enabled = body.enabled;
        if (!body.enabled) this.running = [];
        return reply(200, { ok: true, ...this.status() });
      }
      if (url === '/api/host-shell/stop-all') {
        this.running = [];
        return reply(200, { ok: true, ...this.status() });
      }
      const cancel = url.match(/^\/api\/host-shell\/([^/]+)\/cancel$/);
      if (cancel) {
        this.running = this.running.filter((c) => c.request_id !== cancel[1]);
        return reply(200, { ok: true, request_id: cancel[1], status: 'denied' });
      }
      return reply(404, { detail: 'not found' });
    },
  };
}

function makeEnv() {
  const { doc, byId } = makeDom();
  const server = makeServer();
  const followUps = [];
  const toasts = [];
  const timeouts = [];
  const ctx = {
    Date,
    Math,
    Number,
    String,
    JSON,
    Promise,
    Map,
    Set,
    Array,
    encodeURIComponent,
    console,
    document: doc,
    window: { __CSRF_TOKEN__: 'aigator-fake-api-key' },
    setTimeout: (fn) => timeouts.push(fn),
    clearTimeout: () => {},
    setInterval: () => 1,
    clearInterval: () => {},
    _hostShell: {
      state: 'off',
      running: [],
      stopping: new Set(),
      menu: false,
      sig: '',
      timer: null,
      tick: null,
    },
    _activeTabId: 'tab-1',
    _pendingSandboxCards: new Map(),
    _hostRunsInFlight: new Map(),
    _showConnectivityToast: (msg, type) => toasts.push({ msg, type }),
    _sendSandboxFollowUp: async (tab, text) => followUps.push({ tab, text }),
    _markTabNeedsAttention: () => {},
    fetch: async (url, opts) => server.handle(url, opts),
  };
  vm.createContext(ctx);
  FUNCTIONS.forEach((n) => vm.runInContext(extract(n), ctx));
  return { ctx, doc, byId, server, followUps, toasts, timeouts };
}

const tick = () => new Promise((r) => setTimeout(r, 0));
const settle = async () => {
  for (let i = 0; i < 12; i++) await tick();
};
const buttons = (root) => walk(root).filter((e) => e.tag === 'button');
const labelled = (root, text) => buttons(root).find((b) => b.textContent === text);
const press = async (el) => {
  assert(el, 'button not found');
  assert(!el.disabled, `${el.textContent} is disabled`);
  const handler = el.listeners.click;
  assert(handler, `${el.textContent} has no click handler`);
  handler({ stopPropagation() {}, target: el });
  await settle();
};
const slotClick = async (env, el) => {
  env.byId['host-chip-slot'].listeners.click({ target: el });
  await settle();
};

const request = () => ({
  request_id: 'req1',
  context_id: 'tab-1',
  tool: 'run_on_host',
  command: 'Turn on running commands. Click Turn on now. && echo hi',
  cwd: 'C:/work',
  shell: 'powershell',
  reason: 'Render the launch video',
  risks: [],
  timeout: 120,
  enable_required: true,
  expires_at: Date.now() / 1000 + 600,
});
const approvalCard = (env) =>
  walk(env.byId.messages).find(
    (e) => (e.className || '').includes('gcc-approve-btn') && e.textContent === 'Run',
  );
const allText = (env) => env.byId.messages.textContent;

(async () => {
  // 1. Off by default: the enable card appears, the approval card does not, and nothing is turned on.
  {
    const env = makeEnv();
    env.ctx._showSandboxApproval(request(), 'tab-1');
    const text = allText(env);
    assert(text.includes('Turn on running commands?'));
    assert(text.includes('Running commands is off.'));
    assert(text.includes('outside the sandbox') && text.includes('with your own access'));
    assert(labelled(env.byId.messages, 'Turn on'));
    assert(labelled(env.byId.messages, 'Not now'));
    assert(!approvalCard(env), 'no Run button before the user turns it on');
    assert(!/always allow/i.test(text), 'no Always allow');
    assert.strictEqual(env.server.calls.length, 0, 'drawing the card changes nothing');
    assert.strictEqual(env.server.enabled, false);
    assert.strictEqual(env.doc.activeElement, null, 'the card never takes focus');
  }

  // 2. Model-written text in the command cannot press or enable anything.
  {
    const env = makeEnv();
    env.ctx._showSandboxApproval(request(), 'tab-1');
    await settle();
    assert.strictEqual(env.server.enabled, false);
    assert.strictEqual(env.server.calls.filter((c) => c.method === 'PUT').length, 0);
    assert(
      !allText(env).includes('Click Turn on now'),
      'command text is not drawn on the enable card',
    );
  }

  // 3. Turn on: CSRF PUT, then the line "On.", focus on it, then the normal approval card.
  {
    const env = makeEnv();
    const data = request();
    env.ctx._showSandboxApproval(data, 'tab-1');
    await press(labelled(env.byId.messages, 'Turn on'));
    const put = env.server.calls.find((c) => c.method === 'PUT');
    assert.strictEqual(put.url, '/api/host-shell/enabled');
    assert.strictEqual(put.token, 'aigator-fake-api-key');
    assert.deepStrictEqual(put.body, { enabled: true });
    assert.strictEqual(env.server.enabled, true);
    assert(allText(env).includes('On. Running commands is on. You can turn it off in Settings.'));
    assert(env.doc.activeElement && env.doc.activeElement.textContent.startsWith('On.'));
    assert(approvalCard(env), 'the approval card follows');
    assert(!allText(env).match(/always allow/i));
    assert.strictEqual(data.enable_required, undefined);
    assert.strictEqual(env.ctx._hostShell.state, 'on');
    assert.notStrictEqual(env.doc.activeElement, approvalCard(env), 'focus is not on Run');
    assert(!approvalCard(env).listeners.keydown, 'Run has no key shortcut');
  }

  // 4. A failed Turn on keeps the button, shows the error and changes nothing else.
  {
    const env = makeEnv();
    env.server.failEnableOnce = true;
    env.ctx._showSandboxApproval(request(), 'tab-1');
    await press(labelled(env.byId.messages, 'Turn on'));
    assert(allText(env).includes('Couldn’t turn this on. Try again.'));
    assert(labelled(env.byId.messages, 'Turn on'));
    assert(!approvalCard(env));
    assert.strictEqual(env.server.enabled, false);
    await press(labelled(env.byId.messages, 'Turn on'));
    assert(approvalCard(env), 'a retry works');
  }

  // 5. Not now: the request is cancelled, the agent is told, nothing is turned on.
  {
    const env = makeEnv();
    env.ctx._showSandboxApproval(request(), 'tab-1');
    await press(labelled(env.byId.messages, 'Not now'));
    const cancel = env.server.calls.find((c) => c.url === '/api/host-shell/req1/cancel');
    assert(cancel, 'the pending request is denied on the server');
    assert.strictEqual(cancel.body.context_id, 'tab-1');
    assert.strictEqual(env.server.calls.filter((c) => c.method === 'PUT').length, 0);
    assert(allText(env).includes('Not turned on. The command was not run.'));
    assert(!approvalCard(env));
    assert.strictEqual(env.followUps.length, 1);
    assert(env.followUps[0].text.includes('Do not retry it'));
    assert.strictEqual(env.ctx._pendingSandboxCards.get('tab-1')?.has('req1') ?? false, false);
  }

  // 6. Administrator off wins: no button, and the card says so.
  {
    const env = makeEnv();
    env.server.admin = true;
    env.ctx._showSandboxApproval(request(), 'tab-1');
    await press(labelled(env.byId.messages, 'Turn on'));
    const text = allText(env);
    assert(text.includes('Running commands is turned off'));
    assert(text.includes('Your administrator has turned off running commands on this computer'));
    assert(!labelled(env.byId.messages, 'Turn on'));
    assert(!labelled(env.byId.messages, 'Not now'));
    assert(!approvalCard(env));
    assert.strictEqual(env.server.enabled, false);
  }

  // 7. Already on (turned on in Settings): the approval card shows at once, no enable card.
  {
    const env = makeEnv();
    env.ctx._hostShell.state = 'on';
    env.ctx._showSandboxApproval(request(), 'tab-1');
    assert(approvalCard(env));
    assert(!allText(env).includes('Turn on running commands?'));
  }

  // 8. Settings row: Off by default, turning on and off goes through the CSRF PUT.
  {
    const env = makeEnv();
    env.ctx._initHostShell();
    await settle();
    const sw = env.byId['host-shell-switch'];
    assert.strictEqual(sw.getAttribute('aria-checked'), 'false');
    assert.strictEqual(env.byId['host-shell-status'].textContent, 'Off');
    await press(sw);
    assert.strictEqual(env.server.enabled, true);
    assert.strictEqual(sw.getAttribute('aria-checked'), 'true');
    assert.strictEqual(env.byId['host-shell-status'].textContent, 'On');
    assert(
      env.server.calls
        .filter((c) => c.method === 'PUT')
        .every((c) => c.token === 'aigator-fake-api-key'),
    );
    await press(sw);
    assert.strictEqual(env.server.enabled, false);
    assert.strictEqual(env.byId['host-shell-status'].textContent, 'Off');
  }

  // 9. Settings row when the administrator turned it off: disabled, with the reason.
  {
    const env = makeEnv();
    env.server.admin = true;
    env.ctx._initHostShell();
    await settle();
    const sw = env.byId['host-shell-switch'];
    assert.strictEqual(sw.disabled, true);
    assert.strictEqual(
      env.byId['host-shell-status'].textContent,
      'Turned off by your administrator',
    );
    assert.strictEqual(env.byId['host-chip-slot'].children.length, 0, 'no chip');
  }

  // 10. Chip: hidden when off with nothing running, "Commands on" when idle, N running with Stop.
  {
    const env = makeEnv();
    const slot = env.byId['host-chip-slot'];
    const apply = (state, running) => env.ctx._hostShellApply({ state, running });
    const cmd = (id, command) => ({ request_id: id, context_id: 'tab-1', command, started_at: 1 });
    apply('off', []);
    assert.strictEqual(slot.children.length, 0);
    apply('admin_off', []);
    assert.strictEqual(slot.children.length, 0);
    apply('on', []);
    assert(slot.textContent.includes('Commands on'));
    assert(
      !buttons(slot).some((b) => b.attrs['aria-label'] === 'Stop command'),
      'idle has no Stop',
    );
    apply('on', [cmd('a', 'npm run build')]);
    assert(slot.textContent.includes('1 running'));
    assert(buttons(slot).some((b) => b.attrs['aria-label'] === 'Stop command'));
    apply('on', [cmd('a', 'npm run build'), cmd('b', 'git status')]);
    assert(slot.textContent.includes('2 running'));
    assert(buttons(slot).some((b) => b.attrs['aria-label'] === 'Stop all 2 commands'));
    apply('off', [cmd('a', 'npm run build')]);
    assert(slot.textContent.includes('1 running'), 'visible while a command still runs');
    apply('off', []);
    assert.strictEqual(slot.children.length, 0);
    assert(
      !/run\b.*button/i.test(
        buttons(slot)
          .map((b) => b.textContent)
          .join(','),
      ),
    );
  }

  // 11. Chip menu: lists each command with its own Stop, the switch, the warning and the OK line.
  {
    const env = makeEnv();
    env.ctx._initHostShell();
    const slot = env.byId['host-chip-slot'];
    env.server.enabled = true;
    env.server.running = [
      { request_id: 'a', context_id: 'tab-1', command: 'npm run build', started_at: 1 },
      { request_id: 'b', context_id: 'tab-2', command: 'git status', started_at: 1 },
    ];
    await settle();
    await env.ctx._hostShellRefresh();
    await slotClick(
      env,
      buttons(slot).find((b) => b.dataset.chip === 'menu'),
    );
    const text = slot.textContent;
    assert(text.includes('npm run build') && text.includes('git status'));
    assert(text.includes('Each command still needs your OK in the chat.'));
    assert(text.includes('Turning off also stops 2 running commands.'));
    assert(text.includes('Run commands on this computer'));
    assert(!/always allow/i.test(text));
    assert.strictEqual(buttons(slot).filter((b) => b.dataset.chip === 'stop1').length, 2);

    await slotClick(
      env,
      buttons(slot).find((b) => b.dataset.chip === 'stop1' && b.dataset.id === 'b'),
    );
    const one = env.server.calls.find((c) => c.url === '/api/host-shell/b/cancel');
    assert(one, 'a per-command Stop cancels just that command');
    assert.strictEqual(one.body.context_id, 'tab-2');
    assert.strictEqual(one.token, 'aigator-fake-api-key');
    assert.deepStrictEqual(
      env.server.running.map((c) => c.request_id),
      ['a'],
    );

    await env.ctx._hostShellRefresh();
    await slotClick(
      env,
      buttons(slot).find((b) => b.dataset.chip === 'stop'),
    );
    assert(env.server.calls.some((c) => c.url === '/api/host-shell/stop-all' && c.token));
    assert.strictEqual(env.server.running.length, 0);
    assert.strictEqual(env.byId['host-chip-sr'].textContent, 'Stopped');
  }

  // 12. Turning the feature off from the chip menu stops every running command; Esc closes the menu.
  {
    const env = makeEnv();
    env.ctx._initHostShell();
    const slot = env.byId['host-chip-slot'];
    env.server.enabled = true;
    env.server.running = [
      { request_id: 'a', context_id: 'tab-1', command: 'sleep 99', started_at: 1 },
    ];
    await settle();
    await env.ctx._hostShellRefresh();
    await slotClick(
      env,
      buttons(slot).find((b) => b.dataset.chip === 'menu'),
    );
    await slotClick(
      env,
      buttons(slot).find((b) => b.dataset.chip === 'sw'),
    );
    const put = env.server.calls.filter((c) => c.method === 'PUT').pop();
    assert.deepStrictEqual(put.body, { enabled: false });
    assert.strictEqual(env.server.running.length, 0, 'turning off stops what is running');
    assert.strictEqual(slot.children.length, 0, 'the chip leaves once nothing runs and it is off');

    env.server.enabled = true;
    await env.ctx._hostShellRefresh();
    await slotClick(
      env,
      buttons(slot).find((b) => b.dataset.chip === 'menu'),
    );
    assert(slot.textContent.includes('Nothing is running.'));
    env.doc.listeners.keydown({ key: 'Escape' });
    assert(!slot.textContent.includes('Nothing is running.'), 'Esc closes the menu');
    assert.strictEqual(env.doc.activeElement.dataset.chip, 'menu', 'focus returns to the chip');
  }

  console.log('host command enable tests passed');
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
