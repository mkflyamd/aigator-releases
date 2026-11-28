const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { test } = require('node:test');

const STATIC = path.join(__dirname, '..', 'web', 'static');
const pill = require(path.join(STATIC, 'remote-pill.js'));

// ── a small DOM: ids and classes are looked up in the HTML that was set on a node ──
class FakeEl {
  constructor(registry, tag) {
    this.registry = registry;
    this.tagName = tag;
    this.id = '';
    this.className = '';
    this.dataset = {};
    this.style = {};
    this.attrs = {};
    this.listeners = {};
    this.children = [];
    this.scrollTop = 0;
    this.hidden = false;
    this.clears = 0;
    this._html = '';
    this._cache = new Map();
    this.parentElement = null;
  }
  get innerHTML() {
    return this._html;
  }
  set innerHTML(v) {
    this._html = String(v);
    this._cache = new Map();
  }
  set textContent(v) {
    this.children = [];
    this.clears += 1;
    this._text = String(v);
  }
  get textContent() {
    return this._text || '';
  }
  get childNodes() {
    return this.children;
  }
  appendChild(node) {
    this.children.push(node);
    node.parentElement = this;
    if (node.id) this.registry.set(node.id, node);
    return node;
  }
  append(...nodes) {
    nodes.forEach((n) => this.appendChild(n));
  }
  insertBefore(node) {
    return this.appendChild(node);
  }
  insertAdjacentHTML(_where, html) {
    this._html += html;
    this._cache = new Map();
  }
  setAttribute(k, v) {
    this.attrs[k] = String(v);
  }
  getAttribute(k) {
    return k in this.attrs ? this.attrs[k] : null;
  }
  removeAttribute(k) {
    delete this.attrs[k];
  }
  addEventListener(type, fn) {
    (this.listeners[type] = this.listeners[type] || []).push(fn);
  }
  removeEventListener() {}
  focus() {}
  remove() {
    if (this.parent) this.parent._html = '';
  }
  classList = { add() {}, remove() {}, toggle() {}, contains: () => false };
  closest() {
    return null;
  }
  querySelectorAll() {
    return [];
  }
  querySelector(sel) {
    if (this._cache.has(sel)) return this._cache.get(sel);
    let pattern = null;
    if (sel.startsWith('.')) pattern = new RegExp('class="[^"]*\\b' + sel.slice(1) + '\\b');
    else if (sel.startsWith('#')) pattern = new RegExp('id="' + sel.slice(1) + '"');
    else if (sel.startsWith('['))
      pattern = new RegExp(sel.slice(1, -1).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    let found = null;
    if (pattern && pattern.test(this._html)) {
      found = new FakeEl(this.registry, 'x');
      found.parent = this;
    }
    this._cache.set(sel, found);
    return found;
  }
}

function makeDocument() {
  const registry = new Map();
  const selectors = new Map();
  const doc = {
    registry,
    selectors,
    hidden: false,
    activeElement: null,
    listeners: {},
    getElementById: (id) => registry.get(id) || null,
    querySelector: (sel) => selectors.get(sel) || null,
    createElement: (tag) => new FakeEl(registry, tag),
    addEventListener(type, fn) {
      (doc.listeners[type] = doc.listeners[type] || []).push(fn);
    },
    body: new FakeEl(registry, 'body'),
    documentElement: new FakeEl(registry, 'html'),
  };
  return doc;
}

// Builds the left column the way tp-code-agent.js does: from its real template string.
function loadTemplate() {
  const src = fs.readFileSync(path.join(STATIC, 'tp-code-agent.js'), 'utf8');
  const fn = src.match(/function _caSourceControlPanel\(\) \{[\s\S]*?\n\}\n/);
  assert(fn, 'template function found');
  const sandbox = { gatorActionAttrs: () => '' };
  vm.createContext(sandbox);
  vm.runInContext(
    ['_CA_TAB_ICON_FILES', '_CA_TAB_ICON_CHANGES', '_CA_TAB_ICON_HISTORY']
      .map((n) => `const ${n} = '<svg></svg>';`)
      .join('\n') +
      fn[0] +
      '\nthis.panel = _caSourceControlPanel;',
    sandbox,
  );
  return sandbox.panel();
}

function rebuildShell(doc, html) {
  [...html.matchAll(/id="([^"]+)"/g)].forEach((m) => {
    const node = new FakeEl(doc.registry, 'div');
    node.id = m[1];
    doc.registry.set(m[1], node);
  });
  const strip = new FakeEl(doc.registry, 'div');
  doc.selectors.set('.ca-sc-viewtabs', strip);
  return strip;
}

function loadHistory(doc) {
  const sandbox = {
    document: doc,
    fetch: () => Promise.reject(new Error('offline')),
    setInterval: () => 0,
    clearInterval: () => {},
    setTimeout: () => 0,
    clearTimeout: () => {},
    console,
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(STATIC, 'agent-history.js'), 'utf8'), sandbox);
  return sandbox.agentHistory;
}

function makeEnv(doc, script) {
  const calls = [];
  const clock = { t: 0 };
  const storage = new Map();
  const timers = [];
  const queue = Array.isArray(script) ? script : [script];
  let last = queue[0];
  const env = {
    document: doc,
    calls,
    clock,
    timers,
    storage: { getItem: (k) => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, v) },
    csrf: () => 'aigator-fake-api-key',
    now: () => clock.t,
    every: (fn) => {
      timers.push(fn);
      return timers.length;
    },
    later: (fn) => fn(),
    notify: (name) => calls.push(['event', name]),
    openSettings: (tab) => calls.push(['settings', tab]),
    fetch: async (url, init = {}) => {
      const method = init.method || 'GET';
      calls.push([method, url, init.headers && init.headers['X-CSRF-Token']]);
      if (url === '/api/remote/status') {
        last = queue.length > 1 ? queue.shift() : last;
        return { ok: true, status: 200, json: async () => last };
      }
      if (env.refuse && (url === '/api/remote/arm' || url === '/api/remote/restart')) {
        return { ok: false, status: 409, json: async () => ({ detail: env.refuse }) };
      }
      if (url === '/api/remote/restart') {
        last = {
          ...last,
          state: 'on',
          reason: null,
          armed_at: last.now,
          expires_at: last.now + 43200,
        };
        return { ok: true, status: 200, json: async () => last };
      }
      if (url === '/api/remote/arm') {
        last = {
          ...last,
          state: 'on',
          reason: null,
          armed_at: 100,
          expires_at: last.now + 12 * 3600,
        };
        return { ok: true, status: 200, json: async () => last };
      }
      if (url === '/api/remote/disarm') {
        last = { ...last, state: 'off', reason: null, armed_at: null };
        return { ok: true, status: 200, json: async () => last };
      }
      return { ok: true, status: 200, json: async () => ({ enabled: true }) };
    },
  };
  return env;
}

const base = (over) => ({
  state: 'off',
  reason: null,
  channels: [
    { name: 'teams', enabled: true, armed: false },
    { name: 'slack', enabled: true, armed: false },
  ],
  armed_at: null,
  expires_at: null,
  now: 1000,
  ...over,
});
const running = (secondsLeft, over) =>
  base({ state: 'on', armed_at: 1000 - 60, expires_at: 1000 + secondsLeft, ...over });
const click = (doc, name) => {
  const target = { closest: () => ({ getAttribute: (k) => (k === 'data-rcp' ? name : null) }) };
  return Promise.all(doc.listeners.click.map((fn) => fn({ target })));
};
const clickSwitch = (doc, checked, disabled) => {
  const attrs = {
    'data-rcp': 'switch',
    'aria-checked': String(checked),
    'aria-disabled': disabled ? 'true' : null,
  };
  const target = { closest: () => ({ getAttribute: (k) => attrs[k] ?? null }) };
  return Promise.all(doc.listeners.click.map((fn) => fn({ target })));
};
const settle = () => new Promise((r) => setImmediate(r));

test('the countdown is the server deadline minus the server now, not the browser clock', () => {
  const s = running(7200);
  assert.strictEqual(pill.remainingSeconds(s, 5000, 5000), 7200);
  assert.strictEqual(pill.remainingSeconds(s, 5000, 65000), 7140);
  assert.strictEqual(pill.remainingSeconds(base(), 0, 0), 0);
});

test('every server state maps to the card the design shows', () => {
  const vmOf = (state, extra, left) => pill.viewModel(base({ state, ...extra }), left);
  assert.strictEqual(vmOf('off').title, 'Remote control');
  assert(/Turns itself off after 12 hours/.test(vmOf('off').sub));
  assert(/Gator/.test(vmOf('off').sub));
  assert.strictEqual(vmOf('off').sw.on, false);

  assert.strictEqual(vmOf('not_set_up').acts[0].act, 'setup');
  assert.strictEqual(vmOf('not_set_up').sw.show, false);

  const noReply = vmOf('replies_off');
  assert.strictEqual(noReply.acts[0].act, 'repliesOn');
  assert.strictEqual(noReply.sw.show, false);
  const mute = vmOf('replies_off', { armed_at: 5, expires_at: 9999 });
  assert.strictEqual(mute.title, "Remote control can't reply");
  assert.strictEqual(mute.acts[0].act, 'replies');
  assert.strictEqual(mute.sw.on, true);

  const admin = vmOf('replies_blocked_admin', {
    reason: 'Your administrator has switched off replies.',
  });
  assert.strictEqual(admin.eye, 'blocked');
  assert.strictEqual(admin.sw.disabled, true);
  assert.strictEqual(admin.sub, 'Your administrator has switched off replies.');

  ['expired', 'stopped_from_chat'].forEach((state) => {
    const v = vmOf(state, { reason: 'because ' + state });
    assert.strictEqual(v.eye, 'expired', state);
    assert.strictEqual(v.sub, 'because ' + state, 'the server reason is shown');
  });
  const expiring = vmOf('expiring', { reason: 'x' });
  assert.strictEqual(expiring.eye, 'expired');
  assert.strictEqual(expiring.title, 'Turning off');
  assert.strictEqual(expiring.sub, 'Finishing up.');
  assert.strictEqual(expiring.sw.disabled, true);

  const on = vmOf('on', {}, 702 * 60);
  assert.strictEqual(on.tone, 'on');
  assert.strictEqual(on.title, 'Remote control on');
  assert.strictEqual(on.timer.text, '11 h 42 min left');
  assert.strictEqual(on.timer.spoken, '11 hours 42 minutes left');
  assert.strictEqual(on.acts.length, 0);

  const hour = vmOf('warn_1h', {}, 55 * 60);
  assert.strictEqual(hour.tone, 'warn');
  assert.strictEqual(hour.eye, 'warn');
  assert.strictEqual(hour.note, 'Turns off soon. Restart to keep it on.');
  assert.strictEqual(hour.acts[0].label, 'Restart 12 hours');
  assert(!hour.acts[0].primary, 'secondary at 1 hour');

  const quarter = vmOf('warn_15m', {}, 14 * 60);
  assert.strictEqual(quarter.timer.text, 'Turns off in 14 min');
  assert.strictEqual(quarter.timer.spoken, 'Turns off in 14 minutes');
  assert(/Sessions stop when the 12 hours end/.test(quarter.note));
  assert.strictEqual(quarter.acts[0].primary, true, 'primary at 15 minutes');
  assert(/class="rcp-btn is-primary" data-rcp="restart"/.test(pill.cardHtml(quarter)));
});

test('time copy drops zero parts and never splits across lines', () => {
  const left = (min) => pill.viewModel(running(min * 60), min * 60).timer;
  assert.strictEqual(left(660).text, '11 h left');
  assert.strictEqual(left(665).text, '11 h 5 min left');
  assert.strictEqual(left(50).text, '50 min left');
  assert.strictEqual(left(660).spoken, '11 hours left');
  const html = pill.cardHtml(pill.viewModel(running(665 * 60), 665 * 60));
  assert(/<span role="timer" class="rcp-nw">/.test(html));
});

test('the sheet names Gator in the reply promise', () => {
  assert(
    /Gator only replies in your own chat\. It sends nothing to other people from here\./.test(
      pill.sheetHtml(base()),
    ),
  );
});

test('the card is accessible markup: switch, timer with spoken form, decorative eye', () => {
  const html = pill.cardHtml(pill.viewModel(running(702 * 60), 702 * 60));
  assert(
    /role="switch"[^>]*aria-checked="true"|aria-checked="true"[^>]*role="switch"/.test(html) ||
      /data-rcp="switch" aria-checked="true"/.test(html),
  );
  assert(/role="timer"/.test(html));
  assert(/<span class="rcp-sr">11 hours 42 minutes left<\/span>/.test(html));
  assert(
    /<svg class="gator-eye" data-state="on" width="24" height="24" viewBox="2 4 20 20" aria-hidden="true"/.test(
      html,
    ),
  );
  assert(/aria-label="Remote control"/.test(html));
  const sheet = pill.sheetHtml(base({ state: 'replies_off' }));
  assert(
    !/awake/i.test(sheet) && !/awake/i.test(pill.cardHtml(pill.viewModel(base(), 0))),
    'no keep-awake',
  );
  assert(/Turn on replies and Remote control/.test(sheet));
});

test('one poller; the pill survives a History re-render and a shell rebuild', async () => {
  const doc = makeDocument();
  const html = loadTemplate();
  assert(
    /id="ca-hist-view"[\s\S]*?id="ca-hist-list"[^>]*><\/div>\s*<div id="remote-pill-slot"><\/div>\s*<\/div>/.test(
      html,
    ),
    'the mount point is inside History, after the list',
  );
  let strip = rebuildShell(doc, html);
  const tabEye = new FakeEl(doc.registry, 'svg');
  tabEye.attrs['data-state'] = 'off';
  doc.selectors.set('.smodal-tab[data-tab="remote"] .gator-eye', tabEye);

  const env = makeEnv(doc, running(41945));
  const rp = pill.create(env);
  rp.start();
  rp.start();
  assert.strictEqual(env.timers.length, 1, 'start() twice still runs one poller');

  await settle();
  assert.strictEqual(rp.fetches, 1, 'first tick fetched once');
  let slot = doc.getElementById('remote-pill-slot');
  assert(/data-remote-pill/.test(slot.innerHTML), 'card painted');
  assert(/11 h 40 min left/.test(slot.innerHTML));
  assert(/rcp-badge/.test(strip.innerHTML), 'header badge while on');
  assert.strictEqual(tabEye.getAttribute('data-state'), 'on');

  // the local clock advances; nothing is refetched, the countdown moves
  env.clock.t += 29000;
  env.timers[0]();
  await settle();
  assert.strictEqual(rp.fetches, 1);
  assert(/11 h 39 min left/.test(slot.innerHTML));

  // the real History render runs and clears only its list
  const history = loadHistory(doc);
  const list = doc.getElementById('ca-hist-list');
  history.show();
  history.show();
  assert(list.clears >= 1, 'agent-history cleared #ca-hist-list');
  assert(/data-remote-pill/.test(slot.innerHTML), 'pill survives the History re-render');
  assert.strictEqual(doc.getElementById('remote-pill-slot'), slot);

  // the shell is rebuilt from the template: a new, empty slot
  strip = rebuildShell(doc, html);
  slot = doc.getElementById('remote-pill-slot');
  assert.strictEqual(slot.innerHTML, '');
  rp.mount();
  assert(/data-remote-pill/.test(slot.innerHTML), 'mount() repaints the new slot at once');
  assert(/rcp-badge/.test(strip.innerHTML), 'badge restored in the new header');

  const before = rp.fetches;
  rebuildShell(doc, html);
  slot = doc.getElementById('remote-pill-slot');
  env.clock.t += 500;
  env.timers[0]();
  await settle();
  assert(/data-remote-pill/.test(slot.innerHTML), 'the next tick also repaints a rebuilt shell');
  assert.strictEqual(rp.fetches, before, 'a rebuild does not add a poller or an extra fetch');
  assert.strictEqual(env.timers.length, 1);

  // status refreshes by itself after the interval, still through the one poller
  env.clock.t += 31000;
  env.timers[0]();
  await settle();
  assert.strictEqual(rp.fetches, before + 1);
  assert.strictEqual(env.timers.length, 1);
});

test('turning on opens the sheet once, then arms with the CSRF header; restart is disarm then arm', async () => {
  const doc = makeDocument();
  rebuildShell(doc, loadTemplate());
  const env = makeEnv(doc, base());
  const rp = pill.create(env);
  rp.start();
  await settle();

  await clickSwitch(doc, false);
  assert(!env.calls.some((c) => c[1] === '/api/remote/arm'), 'sheet first, no arm yet');
  const sheetHost = doc.getElementById('remote-pill-sheet');
  assert.strictEqual(sheetHost.hidden, false);
  assert(/Turn on for 12 hours/.test(sheetHost.querySelector('.rcp-sheet').innerHTML));

  await click(doc, 'sheet-ok');
  await settle();
  const arm = env.calls.find((c) => c[1] === '/api/remote/arm');
  assert(arm, 'armed');
  assert.deepStrictEqual(arm, ['POST', '/api/remote/arm', 'aigator-fake-api-key']);
  assert.strictEqual(sheetHost.hidden, true);
  assert.strictEqual(rp.status.state, 'on');
  assert(/Remote control on/.test(doc.getElementById('remote-pill-slot').innerHTML));

  await clickSwitch(doc, true);
  await settle();
  assert.strictEqual(rp.status.state, 'off');
  await clickSwitch(doc, false);
  await settle();
  assert.strictEqual(rp.status.state, 'on', 'second turn-on skips the sheet');

  env.calls.length = 0;
  await click(doc, 'restart');
  await settle();
  const writes = env.calls.filter((c) => c[0] === 'POST').map((c) => c[1]);
  assert.deepStrictEqual(writes, ['/api/remote/restart']);
  const restart = env.calls.find((c) => c[1] === '/api/remote/restart');
  assert.strictEqual(restart[2], 'aigator-fake-api-key');
  assert.strictEqual(rp.status.state, 'on');
});

test('the update toast is lifted above the footer card only while the card is on screen', async () => {
  const doc = makeDocument();
  rebuildShell(doc, loadTemplate());
  const props = {};
  doc.documentElement.style = { setProperty: (k, v) => (props[k] = v) };
  const env = makeEnv(doc, running(41945));
  const rp = pill.create(env);
  rp.start();
  await settle();
  const slot = doc.getElementById('remote-pill-slot');
  slot.offsetHeight = 170;
  slot.offsetParent = {};
  rp.paint();
  assert.strictEqual(props['--rcp-toast-lift'], '170px');
  slot.offsetParent = null;
  rp.paint();
  assert.strictEqual(props['--rcp-toast-lift'], '0px');
});

test('a refused restart leaves the window running and shows the reason', async () => {
  const doc = makeDocument();
  rebuildShell(doc, loadTemplate());
  const env = makeEnv(doc, running(41945));
  const rp = pill.create(env);
  rp.start();
  await settle();
  env.refuse = 'Replies to your own chat are off. Turn them on in Settings first.';
  await click(doc, 'restart');
  await settle();
  assert.notStrictEqual(rp.status.state, 'off');
  assert(!env.calls.some((c) => c[1] === '/api/remote/disarm'));
  const err = doc.getElementById('remote-pill-slot').querySelector('[data-rcp-err]');
  assert.strictEqual(err.textContent, env.refuse);
});

test('the sheet makes no promise the server does not keep', () => {
  const sheet = pill.sheetHtml(base());
  assert(!/30-minute|30 minute/.test(sheet));
  assert(/Send <code>@gator<\/code> and what you want in either chat\./.test(sheet));
});

test('a refusal shows the server reason and the switch stays where the server says', async () => {
  const doc = makeDocument();
  rebuildShell(doc, loadTemplate());
  const env = makeEnv(doc, base());
  env.storage.setItem('gator.remote-pill.sheet-seen', '1');
  env.refuse = 'Replies to your own chat are off. Turn them on in Settings first.';
  const rp = pill.create(env);
  rp.start();
  await settle();
  await clickSwitch(doc, false);
  await settle();
  assert.strictEqual(rp.status.state, 'off');
  const err = doc.getElementById('remote-pill-slot').querySelector('[data-rcp-err]');
  assert(err, 'error slot is on the card');
  assert.strictEqual(err.textContent, env.refuse);
});

test('a disabled switch does not call the server; set up opens the Remote control tab', async () => {
  const doc = makeDocument();
  rebuildShell(doc, loadTemplate());
  const env = makeEnv(doc, base({ state: 'replies_blocked_admin', reason: 'Blocked by admin.' }));
  const rp = pill.create(env);
  rp.start();
  await settle();
  await clickSwitch(doc, false, true);
  assert(!env.calls.some((c) => c[0] === 'POST'));
  await click(doc, 'setup');
  assert.deepStrictEqual(
    env.calls.filter((c) => c[0] === 'settings'),
    [['settings', 'remote']],
  );
});

test('off with the server reason shows the invitation, not an error', () => {
  const reason = 'Remote control is not turned on. Arm it in Settings.';
  const view = pill.viewModel(base({ state: 'off', reason, armed_at: null, expires_at: null }), 0);
  assert.strictEqual(view.title, 'Remote control');
  assert.strictEqual(view.sw.on, false);
  assert.ok(!view.sw.disabled);
  assert(/Turns itself off after 12 hours\./.test(view.sub));
  assert(!view.sub.includes(reason));
});
