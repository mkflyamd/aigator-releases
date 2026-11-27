const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const TERMINAL_SRC = path.join(__dirname, '..', 'web', 'static', 'tp-generic-agent-terminal.js');
const HISTORY_SRC = path.join(__dirname, '..', 'web', 'static', 'agent-history.js');

// --- terminal side: _genAgentStart with a stubbed DOM and PTY layer -----------------------
function loadTerminal() {
  const makeEl = () => ({
    style: {},
    className: '',
    appendChild() {},
    remove() {
      this.removed = true;
    },
    querySelectorAll: () => [],
  });
  const sandbox = {
    console,
    clearTimeout,
    setTimeout,
    document: { createElement: makeEl, getElementById: () => makeEl() },
    window: {},
    requestAnimationFrame: (fn) => fn(),
    _caSessionKey: (id) => String(id),
    _caHeadersAsync: async () => ({}),
    _ocSpawnTerm: (sess) => {
      sess.term = { dispose() {}, refresh() {}, focus() {}, cols: 80, rows: 24 };
    },
    _ocFit() {},
    _ocGuardSize() {},
    _ocFetch: async () => ({
      ok: true,
      json: async () => ({ pty_session_id: 'p1', created: true }),
    }),
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(TERMINAL_SRC, 'utf8'), sandbox);
  const stubs = {
    connected: [],
    activated: [],
  };
  sandbox.__stubs = stubs;
  vm.runInContext(
    `
    _genAgentShowLoadingState = () => {};
    _genAgentHideLoadingState = () => {};
    _genAgentHideStartPrompt = () => {};
    _genAgentShowStartPrompt = () => {};
    _genAgentRenderTabs = () => {};
    _genAgentConnect = (s) => __stubs.connected.push(s.ptySessionId);
    _genAgentActivateSession = (t, id) => __stubs.activated.push(id);
    `,
    sandbox,
  );
  return { sandbox, stubs, run: (code) => vm.runInContext(code, sandbox) };
}

(async () => {
  // a fresh PTY id is attached once, returns the id, and fires onFirstPaint once on reveal
  {
    const t = loadTerminal();
    const id = await t.run(`_genAgentStart('t', 'claude', 'proj', '/repo', { forceNew: true })`);
    assert.strictEqual(id, 'p1');
    const state = t.run(`_genAgentTerminals['t']`);
    assert.deepStrictEqual(Array.from(state.order), ['p1']);
    assert.strictEqual(state.sessions.p1.ptySessionId, 'p1');
    let fired = 0;
    state.sessions.p1._onFirstPaint = () => {
      fired += 1;
    };
    t.run(`_genAgentRevealSession(_genAgentTerminals['t'].sessions.p1)`);
    t.run(`_genAgentRevealSession(_genAgentTerminals['t'].sessions.p1)`);
    assert.strictEqual(fired, 1, 'first paint hook fires once');
  }

  // the server returning an id this tab already shows activates it instead of duplicating
  {
    const t = loadTerminal();
    await t.run(`_genAgentStart('t', 'claude', 'proj', '/repo', { forceNew: true })`);
    const state = t.run(`_genAgentTerminals['t']`);
    const first = state.sessions.p1;
    first._revealed = true;
    const id = await t.run(
      `_genAgentStart('t', 'claude', 'proj', '/repo', { forceNew: true, onFirstPaint: () => { globalThis.__again = true; } })`,
    );
    assert.strictEqual(id, 'p1', 'returns the existing id');
    assert.deepStrictEqual(Array.from(state.order), ['p1'], 'no duplicate order entry');
    assert.strictEqual(state.sessions.p1, first, 'the original session is kept');
    assert.strictEqual(t.stubs.connected.length, 1, 'no second websocket');
    assert.strictEqual(t.stubs.activated.slice(-1)[0], 'p1', 'the existing terminal is activated');
    assert.strictEqual(t.sandbox.__again, true, 'an already painted terminal reports at once');
  }

  // a failed start returns nothing
  {
    const t = loadTerminal();
    t.sandbox._ocFetch = async () => ({ ok: false, json: async () => ({ detail: 'nope' }) });
    t.sandbox.addMessage = () => {};
    const id = await t.run(`_genAgentStart('t', 'claude', 'proj', '/repo', { forceNew: true })`);
    assert.strictEqual(id, undefined);
  }

  // --- history side -------------------------------------------------------------------
  const timers = [];
  globalThis.setInterval = () => 0;
  globalThis.setTimeout = (fn, ms) => {
    timers.push({ fn, ms });
    return timers.length;
  };
  globalThis.clearTimeout = (n) => {
    if (timers[n - 1]) timers[n - 1].dead = true;
  };
  globalThis.document = { getElementById: () => null };
  globalThis._activeTabId = 7;
  globalThis._caActiveProject = 'proj';
  globalThis._caProjects = [{ name: 'proj', repo_path: '/repo' }];
  globalThis._caSessionKey = (id) => String(id);
  globalThis._genAgentTerminals = {};

  const h = require(HISTORY_SRC);
  const target = { pid: 4242, created: 1700000000.5 };
  const row = (id) => ({ key: id, id, agent: 'claude' });
  const notices = () => timers.filter((t) => t.ms === 3000 && !t.dead);

  function fakeStart() {
    const calls = [];
    globalThis._genAgentStartInFlight = () => calls.some((c) => !c.done);
    globalThis._genAgentStart = (tab, agent, name, repo, opts) =>
      new Promise((resolve) => {
        const c = {
          opts,
          done: false,
          finish: (v) => {
            c.done = true;
            resolve(v);
          },
        };
        calls.push(c);
      });
    return calls;
  }

  // different rows: the second click is not silently dropped and the first row stays busy
  {
    const calls = fakeStart();
    const p = h.resume(row('a'));
    assert.strictEqual(h.isRowBusy(row('a')), true, 'busy is set before any await');
    await h.resume(row('b'));
    assert.strictEqual(calls.length, 1, 'only one start is in flight');
    assert.strictEqual(h.isRowBusy(row('b')), false, 'the rejected row is not busy');
    assert.strictEqual(notices().length >= 1, true, 'the second click gets feedback');
    calls[0].opts.onFirstPaint();
    assert.strictEqual(h.isRowBusy(row('a')), false, 'busy clears when the terminal paints');
    calls[0].finish('p1');
    await p;
    calls.length = 0;
  }

  // same row twice: the second click is refused with feedback, one start only
  {
    const calls = fakeStart();
    const p = h.resume(row('c'));
    await h.resume(row('c'));
    assert.strictEqual(calls.length, 1, 'one start for two clicks on one row');
    calls[0].finish('p2');
    await p;
    assert.strictEqual(h.isRowBusy(row('c')), true, 'still busy until the first paint');
    calls[0].opts.onFirstPaint();
    assert.strictEqual(h.isRowBusy(row('c')), false);
  }

  // a failed start clears busy
  {
    const calls = fakeStart();
    const p = h.resume(row('d'));
    calls[0].finish(undefined);
    await p;
    assert.strictEqual(h.isRowBusy(row('d')), false, 'failure clears busy');
  }

  // a start that never paints is released by the safety timer
  {
    const calls = fakeStart();
    const p = h.resume(row('e'));
    calls[0].finish('p3');
    await p;
    const safety = timers.filter((t) => t.ms === 35000 && !t.dead).pop();
    assert.ok(safety, 'a safety timer is armed');
    safety.fn();
    assert.strictEqual(h.isRowBusy(row('e')), false);
  }

  // takeover: two confirms never run two POSTs, and a failure frees the guard
  {
    fakeStart();
    let posts = 0;
    let release;
    globalThis._ocFetch = () => {
      posts += 1;
      return new Promise((resolve) => {
        release = resolve;
      });
    };
    const a = h.takeover({ ...row('f'), liveElsewhere: true }, target);
    const b = h.takeover({ ...row('g'), liveElsewhere: true }, target);
    assert.strictEqual(h.isRowBusy(row('f')), true);
    assert.strictEqual(h.isRowBusy(row('g')), false, 'the second takeover is ignored');
    await Promise.resolve();
    await Promise.resolve();
    assert.strictEqual(posts, 1, 'one takeover POST at a time');
    release({ ok: false, json: async () => ({ detail: 'busy' }) });
    await Promise.all([a, b]);
    assert.strictEqual(h.isRowBusy(row('f')), false, 'failed takeover frees the row');
    posts = 0;
    const c = h.takeover({ ...row('h'), liveElsewhere: true }, target);
    await Promise.resolve();
    await Promise.resolve();
    assert.strictEqual(posts, 1, 'the guard is released after a failure');
    release({ ok: false, json: async () => ({}) });
    await c;
  }

  // takeover success hands the row to resume without tripping the row-busy guard
  {
    const calls = fakeStart();
    globalThis._ocFetch = async () => ({ ok: true, json: async () => ({}) });
    await h.takeover({ ...row('i'), liveElsewhere: true }, target);
    await Promise.resolve();
    assert.strictEqual(calls.length, 1, 'resume starts after a successful takeover');
    assert.strictEqual(h.isRowBusy(row('i')), true);
    calls[0].finish('p4');
  }

  console.log('agent_history_rapid_click: ok');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
