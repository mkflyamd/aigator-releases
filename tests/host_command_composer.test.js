// While a host command runs, the composer behaves as busy: the button becomes Stop command (empty box) or Queue plus
// Stop (text typed), Enter queues, the queue waits for the command, and a card that is only waiting for an answer is a
// separate "card open" case that never shows Stop. The real functions are cut out of app.js and run against stubs.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function functionSource(name) {
  let start = source.indexOf(`async function ${name}(`);
  if (start < 0) start = source.indexOf(`function ${name}(`);
  assert(start > 0, `${name} found`);
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i++) {
    if (source[i] === '{') depth++;
    if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`${name} not closed`);
}

function constSource(name) {
  const start = source.indexOf(`const ${name} = {`);
  assert(start > 0, `${name} found`);
  const end = source.indexOf('\n};', start);
  return source.slice(start, end + 3);
}

const FUNCTIONS = [
  '_commandRunning',
  '_tabBusy',
  '_queueCardHold',
  '_composerButtonMode',
  '_composerView',
  '_stopCommands',
  '_runStart',
  '_runEnd',
  '_runsSeed',
  '_runCardRestore',
  '_runsWatchStop',
  '_runsWatchArm',
  '_queueStatus',
  '_queueDrain',
  '_queueBusyStart',
  '_queueBusyEnd',
  '_queueRearm',
  '_queueRearmStop',
  '_submitShouldQueue',
  '_shouldStopFromClick',
  '_onComposerButtonClick',
  '_updatePlaceholder',
  '_queueButton',
  '_queueChip',
];

function world({ heads = [], turn = false } = {}) {
  const calls = [];
  const timers = [];
  const queue = [...heads];
  const events = [];
  const fetches = [];
  const runsBody = { runs: [] };
  const statusBody = { card: null };
  const drawn = [];
  const placeholderBox = { dataset: {}, contentEditable: 'true' };
  const sendBtn = {
    classList: { contains: (c) => c === 'is-streaming' && ctx._streaming },
    contains: () => false,
    getBoundingClientRect: () => ({ left: 0, right: 34, top: 0, bottom: 34 }),
  };
  const stopBtn = { hidden: false, contains: (t) => t === 'stop-btn' };
  const ctx = {
    _streaming: turn,
    _activeTabId: 'tab1',
    _queueBusy: new Set(),
    _queueBusyTimers: new Map(),
    _queueRearms: new Map(),
    _queueDirty: new Set(),
    _queueIdleSince: new Map(),
    _queueByTab: new Map([['tab1', { items: [{ id: 'a', text: 'next' }], paused: false }]]),
    _QUEUE_REARM_MS: [500, 500, 1000],
    _QUEUE_FAILSAFE_MS: 3000,
    _pendingSandboxFollowUps: new Map(),
    _pendingSandboxCards: new Map(),
    _pendingTabCards: new Map(),
    _chatTaskIds: new Map(turn ? [['tab1', 'task1']] : []),
    _runsByTab: new Map(),
    _runsWatch: new Map(),
    _activeStops: new Set(),
    sendBtn,
    document: {
      getElementById: (id) =>
        id === 'chat-input'
          ? placeholderBox
          : id === 'send-btn'
            ? sendBtn
            : id === 'composer-stop-btn'
              ? stopBtn
              : null,
      createElement: () => {
        const el = { children: [], dataset: {}, listeners: {}, className: '' };
        el.appendChild = (c) => el.children.push(c);
        el.append = (...cs) => el.children.push(...cs);
        el.addEventListener = (type, fn) => (el.listeners[type] = fn);
        return el;
      },
    },
    console: { warn() {} },
    Map,
    Set,
    Array,
    Promise,
    JSON,
    encodeURIComponent,
    _syncComposerButton: () => events.push('sync'),
    _renderQueue: () => events.push('render'),
    _queueRefresh: () => calls.push('refresh'),
    _composerCanQueue: () => ctx._canQueue,
    _canQueue: false,
    _requestTypedSubmit: () => events.push('typed-submit'),
    _closeComposerDropdowns: () => {},
    _queueSendNow: () => {},
    setTimeout: (fn, ms) => {
      timers.push({ fn, ms });
      return timers.length;
    },
    clearTimeout: (id) => {
      if (timers[id - 1]) timers[id - 1].fn = null;
    },
    fetch: async (url) => {
      fetches.push(url);
      return {
        ok: true,
        json: async () => (url.startsWith('/api/host-shell/') ? statusBody : runsBody),
      };
    },
    _showSandboxApproval: (card, tab, reload) => drawn.push([card.request_id, tab, reload]),
    _queueCall: async () => {
      calls.push('head');
      const next = queue.shift();
      return next || { item: null };
    },
    _submitQueuedItem: async (item) => calls.push(`submit:${item.id}`),
  };
  vm.createContext(ctx);
  vm.runInContext(
    `${constSource('_COMPOSER_TEXT')}\n${FUNCTIONS.map(functionSource).join('\n')}`,
    ctx,
  );
  const pending = () => timers.filter((t) => t.fn);
  const fireAll = async () => {
    for (const t of pending()) {
      const fn = t.fn;
      t.fn = null;
      await fn();
    }
  };
  const addRun = (id = 'r1', stop = () => events.push(`stop:${id}`)) =>
    ctx._runStart('tab1', id, stop, true);
  const card = (id = 'r1') => ctx._pendingSandboxCards.set('tab1', new Map([[id, {}]]));
  return {
    ctx,
    calls,
    events,
    fetches,
    runsBody,
    statusBody,
    drawn,
    timers,
    pending,
    fireAll,
    addRun,
    card,
    sendBtn,
    placeholderBox,
  };
}

const view = (w, { streaming = false, canQueue = false } = {}) =>
  w.ctx._composerView(
    streaming,
    canQueue,
    w.ctx._commandRunning('tab1'),
    w.ctx._queueCardHold('tab1'),
  );

(async () => {
  // ── tabBusy: a live turn or a preparing/running run; a card that waits for an answer is not busy ──
  {
    const w = world();
    assert.strictEqual(w.ctx._tabBusy('tab1'), false, 'an idle tab is not busy');
    w.addRun();
    assert.strictEqual(w.ctx._tabBusy('tab1'), true, 'a running command makes the tab busy');
    w.ctx._runEnd('tab1', 'r1');
    assert.strictEqual(w.ctx._tabBusy('tab1'), false, 'the tab is idle once the command ends');
    const t = world({ turn: true });
    assert.strictEqual(t.ctx._tabBusy('tab1'), true, 'a live turn makes the tab busy');
    const c = world();
    c.card();
    assert.strictEqual(c.ctx._tabBusy('tab1'), false, 'an awaiting card is not busy');
    assert.strictEqual(c.ctx._queueCardHold('tab1'), true, 'an awaiting card holds the queue');
  }

  // ── the queue holds for an open card but not for the command that card started ──
  {
    const w = world();
    w.card('r1');
    w.addRun('r1');
    assert.strictEqual(
      w.ctx._queueCardHold('tab1'),
      false,
      'the card whose command is running no longer holds',
    );
    w.card('r2');
    assert.strictEqual(
      w.ctx._queueCardHold('tab1'),
      true,
      'another card still waiting for an answer holds',
    );
  }

  // ── button modes ──
  {
    const w = world();
    const m = (streaming, canQueue, cmd, card) =>
      w.ctx._composerButtonMode(streaming, canQueue, cmd, card);
    assert.strictEqual(
      m(false, false, true, false),
      'stop-command',
      'command running, box empty: Stop command',
    );
    assert.strictEqual(m(false, true, true, false), 'queue', 'command running, text typed: Queue');
    assert.strictEqual(m(false, false, false, true), 'send', 'card open, box empty: idle Send');
    assert.strictEqual(m(false, true, false, true), 'queue', 'card open, text typed: Queue');
    assert.strictEqual(
      m(true, false, false, true),
      'send',
      'card open with a reply still live: never Stop',
    );
    assert.strictEqual(
      m(true, true, false, true),
      'queue',
      'card open with a reply still live and text: Queue',
    );
    assert.strictEqual(
      m(true, false, false, false),
      'stop',
      'a live reply with an empty box: Stop reply',
    );
    assert.strictEqual(m(true, true, false, false), 'queue', 'a live reply with text: Queue');
    assert.strictEqual(m(false, false, false, false), 'send', 'idle: Send');
    assert.strictEqual(
      w.ctx._composerButtonMode(true, true),
      'queue',
      'the reply-only call shape still works',
    );
  }

  // ── what the composer says in each state ──
  {
    const w = world();
    w.addRun();
    const empty = view(w);
    assert.strictEqual(empty.mode, 'stop-command');
    assert.strictEqual(empty.aria, 'Stop command');
    assert.strictEqual(empty.title, 'Stop command');
    assert.strictEqual(empty.placeholder, 'Enter to queue');
    const typed = view(w, { canQueue: true });
    assert.strictEqual(typed.mode, 'queue');
    assert.strictEqual(typed.stopHidden, false, 'Queue comes with its own Stop');
    assert.strictEqual(typed.stopLabel, 'Stop command', 'that Stop stops the command');
    assert.strictEqual(typed.title, 'Queue this message. It sends when the command finishes.');
  }
  {
    const w = world();
    w.card();
    const empty = view(w);
    assert.strictEqual(empty.mode, 'send');
    assert.strictEqual(empty.placeholder, 'Enter to queue', 'a card is waiting: Enter queues');
    const typed = view(w, { canQueue: true });
    assert.strictEqual(typed.title, 'Queue this message. It sends after you answer the card.');
    assert.strictEqual(typed.stopHidden, true, 'never a Stop while a card is open');
    const live = view(w, { streaming: true, canQueue: true });
    assert.strictEqual(live.stopHidden, true, 'not even with a reply still live');
  }
  {
    const w = world({ turn: true });
    const typed = view(w, { streaming: true, canQueue: true });
    assert.strictEqual(typed.stopLabel, 'Stop reply', 'a live reply keeps its own Stop');
    assert.strictEqual(typed.title, 'Queue this message. It sends when the reply finishes.');
    const idle = world();
    assert.strictEqual(view(idle).placeholder, '', 'idle: no queue hint');
  }

  // ── clicking Stop command ──
  {
    const w = world();
    w.addRun();
    let prevented = 0;
    const evt = {
      button: 0,
      target: 'send-btn',
      clientX: 10,
      clientY: 10,
      preventDefault: () => prevented++,
    };
    w.ctx._canQueue = false;
    w.ctx.e = evt;
    vm.runInContext('_onComposerButtonClick(e)', w.ctx);
    assert.deepStrictEqual(
      w.events.filter((e) => e.startsWith('stop')),
      ['stop:r1'],
      'the card stop ran once',
    );
    assert.strictEqual(prevented, 1, 'the click does not also submit the empty form');
  }
  {
    const w = world();
    w.addRun();
    w.ctx._canQueue = true;
    w.ctx.e = { button: 0, target: 'stop-btn', clientX: 500, clientY: 500, preventDefault() {} };
    vm.runInContext('_onComposerButtonClick(e)', w.ctx);
    assert.deepStrictEqual(
      w.events.filter((e) => e.startsWith('stop')),
      ['stop:r1'],
      'the outline Stop stops the command',
    );
  }
  {
    const w = world({ turn: true });
    w.addRun();
    let turnStops = 0;
    w.ctx._activeStops.add(() => turnStops++);
    w.ctx._canQueue = true;
    w.ctx.e = { button: 0, target: 'stop-btn', clientX: 500, clientY: 500, preventDefault() {} };
    vm.runInContext('_onComposerButtonClick(e)', w.ctx);
    assert.strictEqual(turnStops, 1, 'with a live reply the Stop stops the reply');
    assert(!w.events.some((e) => e.startsWith('stop:')), 'and leaves the command alone');
  }
  {
    const w = world({ turn: true });
    w.card();
    let turnStops = 0;
    w.ctx._activeStops.add(() => turnStops++);
    w.ctx._canQueue = false;
    w.ctx.e = { button: 0, target: 'send-btn', clientX: 10, clientY: 10, preventDefault() {} };
    vm.runInContext('_onComposerButtonClick(e)', w.ctx);
    assert.strictEqual(
      turnStops,
      0,
      'a click on the button never stops a reply while a card is open',
    );
  }
  {
    const w = world();
    w.addRun('r1');
    w.addRun('r2');
    w.ctx._stopCommands('tab1');
    assert.deepStrictEqual(
      w.events.filter((e) => e.startsWith('stop')),
      ['stop:r1', 'stop:r2'],
      'every command in the tab',
    );
  }

  // ── Enter while a command runs or a card is open queues ──
  {
    const w = world();
    const q = (typed, queuedId = null) => w.ctx._submitShouldQueue('tab1', typed, queuedId);
    assert.strictEqual(q(true), true, 'a typed message lines up behind queued ones');
    w.ctx._queueByTab.set('tab1', { items: [], paused: false });
    assert.strictEqual(q(true), false, 'an idle tab sends');
    w.addRun();
    assert.strictEqual(q(true), true, 'Enter while a command runs queues');
    assert.strictEqual(q(false), false, 'a send nobody typed is not queued');
    w.ctx._runEnd('tab1', 'r1');
    w.card();
    assert.strictEqual(q(true), true, 'Enter while a card is open queues');
    assert.strictEqual(q(false), false, 'a programmatic send (the card follow-up) is not queued');
    assert.strictEqual(q(true, 'a'), false, 'a send the queue itself started goes through');
  }

  // A second Enter handler that dispatches an untyped submit slips past the queue gate and sends straight away.
  {
    const enterSubmitters =
      source.match(
        /e\.key === 'Enter' && !e\.shiftKey\) \{[^}]*?dispatchEvent\(new Event\('submit'/g,
      ) || [];
    assert.strictEqual(enterSubmitters.length, 0, 'Enter submits only through _requestTypedSubmit');
  }

  // ── the queue waits for the command, then drains once; the follow-up goes first ──
  {
    const w = world({ heads: [{ item: { id: 'a' } }] });
    w.addRun();
    await w.ctx._queueDrain('tab1');
    assert.deepStrictEqual(w.calls, [], 'nothing is fetched or sent while the command runs');
    w.ctx._runEnd('tab1', 'r1');
    await w.fireAll();
    await w.ctx._queueDrain('tab1');
    assert.strictEqual(
      w.calls.filter((c) => c.startsWith('submit')).length,
      1,
      'one send once the command ends',
    );
    await w.ctx._queueDrain('tab1');
    assert.strictEqual(w.calls.filter((c) => c.startsWith('submit')).length, 1, 'no double send');
  }
  {
    const w = world({ heads: [{ item: { id: 'a' } }] });
    w.addRun();
    w.ctx._runEnd('tab1', 'r1');
    w.ctx._pendingSandboxFollowUps.set('tab1', 'I ran command request r1.');
    await w.ctx._queueDrain('tab1');
    assert.deepStrictEqual(
      w.calls,
      [],
      'the follow-up that reads the output goes before the queued message',
    );
    w.ctx._pendingSandboxFollowUps.clear();
    await w.ctx._queueDrain('tab1');
    assert.strictEqual(
      w.calls.filter((c) => c.startsWith('submit')).length,
      1,
      'then the queue drains once',
    );
  }
  {
    const w = world({ turn: true, heads: [{ item: { id: 'a' } }] });
    w.addRun();
    w.ctx._runEnd('tab1', 'r1');
    await w.fireAll();
    await w.ctx._queueDrain('tab1');
    assert.deepStrictEqual(
      w.calls,
      [],
      'a Run that ended during a live turn does not race that turn',
    );
  }
  {
    const w = world();
    w.card();
    await w.ctx._queueDrain('tab1');
    assert.deepStrictEqual(w.calls, [], 'an open card holds the queue');
  }

  // ── status line and the pause after a command Stop ──
  {
    const w = world();
    w.addRun();
    const s = w.ctx._queueStatus('tab1', 0);
    assert.strictEqual(s.kind, 'running');
    assert.strictEqual(s.text, 'Next message sends when this command finishes');
    w.ctx._runEnd('tab1', 'r1');
    w.card();
    assert.strictEqual(w.ctx._queueStatus('tab1', 0).text, 'Waiting for your answer on the card');
  }
  {
    const w = world();
    w.ctx._queueByTab.set('tab1', {
      items: [{ id: 'a' }],
      paused: true,
      reason: 'command_stopped',
    });
    const s = w.ctx._queueStatus('tab1', 0);
    assert.strictEqual(s.kind, 'paused');
    assert.strictEqual(s.text, 'Paused: you stopped the command');
    await w.ctx._queueDrain('tab1');
    assert(!w.calls.some((c) => c.startsWith('submit')), 'a paused queue does not send on its own');
  }
  {
    const w = world();
    w.ctx._queueByTab.set('tab1', { items: [{ id: 'a' }], paused: true, reason: 'stopped' });
    assert.strictEqual(
      w.ctx._queueStatus('tab1', 0).text,
      'Paused: you stopped the reply',
      'the reply pause keeps its words',
    );
  }

  // ── the failsafe bar still appears once a command is over and nothing sent the message ──
  {
    const w = world();
    w.addRun();
    assert.strictEqual(w.ctx._queueStatus('tab1', 0).kind, 'running');
    assert.strictEqual(
      w.ctx._queueStatus('tab1', 10000).kind,
      'running',
      'no failsafe while the command runs',
    );
    w.ctx._runEnd('tab1', 'r1');
    assert.strictEqual(
      w.ctx._queueStatus('tab1', 20000).kind,
      'starting',
      'sending, with a recheck',
    );
    assert.strictEqual(
      w.ctx._queueStatus('tab1', 23100).kind,
      'failsafe',
      'after 3 s nothing sent: the failsafe bar',
    );
  }

  // ── row 1 loses "Send now" while a command runs ──
  {
    const labels = (w) => {
      const chip = w.ctx._queueChip('tab1', { id: 'a', text: 'next' }, true);
      return chip.children.map((c) => c.textContent);
    };
    const w = world();
    assert(labels(w).includes('Send now'), 'row 1 offers Send now when no command runs');
    w.addRun();
    assert(!labels(w).includes('Send now'), 'no Stop and send while a command runs');
  }

  // ── reload: the Stop state comes back from the server's run records ──
  {
    const w = world();
    w.runsBody.runs = [
      { id: 'r1', state: 'running' },
      { id: 'r2', state: 'finished' },
      { id: 'r3', state: 'awaiting_approval' },
    ];
    await w.ctx._runsSeed('tab1');
    assert(w.fetches[0].includes('/api/runs?context_id=tab1'));
    assert.strictEqual(w.ctx._commandRunning('tab1'), true, 'a running command is restored');
    assert.deepStrictEqual(
      [...w.ctx._runsByTab.get('tab1').keys()],
      ['r1'],
      'only preparing or running runs count',
    );
    assert.strictEqual(view(w).mode, 'stop-command', 'the composer shows Stop command again');
    assert(w.pending().length > 0, 'a run no card follows is watched until it ends');
    w.runsBody.runs = [{ id: 'r1', state: 'finished' }];
    await w.fireAll();
    assert.strictEqual(
      w.ctx._commandRunning('tab1'),
      false,
      'the watch ends the run when the server says so',
    );
    assert.strictEqual(w.pending().filter((t) => t.ms >= 1000).length, 0, 'and stops watching');
    await w.fireAll();
    assert.strictEqual(
      w.calls.filter((c) => c === 'head').length,
      1,
      'the queue drains once when it ends',
    );
  }
  {
    const w = world();
    w.addRun('r1');
    w.runsBody.runs = [{ id: 'r1', state: 'running' }];
    await w.ctx._runsSeed('tab1');
    assert.strictEqual(w.pending().length, 0, 'a run a card follows needs no watcher');
    w.runsBody.runs = [];
    await w.ctx._runsSeed('tab1');
    assert.strictEqual(
      w.ctx._commandRunning('tab1'),
      true,
      'the card ends its own run, not the seed',
    );
  }

  const settle = () => new Promise((r) => setImmediate(r));
  // ── the placeholder follows the command: queue hint while it runs, empty again once it ends or is stopped ──
  {
    const w = world();
    w.addRun('r1');
    w.ctx._updatePlaceholder();
    assert.strictEqual(w.placeholderBox.dataset.placeholder, 'Enter to queue');
    w.ctx._stopCommands('tab1');
    w.ctx._runEnd('tab1', 'r1');
    w.ctx._updatePlaceholder();
    assert.strictEqual(
      w.placeholderBox.dataset.placeholder,
      '',
      'idle again after Stop: no queue hint',
    );
  }

  // ── a reloaded page draws the running command's card again, as the card's own rejoin ──
  {
    const w = world();
    w.statusBody.card = { request_id: 'r1', command: 'sleep 40' };
    w.runsBody.runs = [
      { id: 'r1', state: 'running', path: 'host' },
      { id: 'py1', state: 'running', path: 'sandbox' },
    ];
    await w.ctx._runsSeed('tab1');
    await settle();
    assert.deepStrictEqual(
      w.drawn,
      [['r1', 'tab1', true]],
      'the host command gets its card back, drawn as a rejoin',
    );
    assert(
      w.fetches.includes('/api/host-shell/r1?context_id=tab1'),
      'from the card the server kept',
    );
    assert(!w.fetches.some((u) => u.includes('py1')), 'a sandbox run has no host card');
    await w.ctx._runsSeed('tab1');
    await settle();
    assert.strictEqual(w.drawn.length, 1, 'the card is drawn once, not on every poll');
  }
  {
    const w = world();
    w.statusBody.card = { request_id: 'r1' };
    w.ctx._pendingSandboxCards.set('tab1', new Map([['r1', {}]]));
    w.runsBody.runs = [{ id: 'r1', state: 'running', path: 'host' }];
    await w.ctx._runsSeed('tab1');
    await settle();
    assert.deepStrictEqual(w.drawn, [], 'a card this page already has is not drawn twice');
  }
  {
    const w = world();
    w.ctx._activeTabId = 'tab2';
    w.statusBody.card = { request_id: 'r1' };
    w.runsBody.runs = [{ id: 'r1', state: 'running', path: 'host' }];
    await w.ctx._runsSeed('tab1');
    await settle();
    assert.deepStrictEqual(
      w.drawn,
      [],
      'a tab nobody is looking at draws its card when it is shown',
    );
    assert.strictEqual(w.ctx._commandRunning('tab1'), true, 'but its command still counts');
  }
  {
    const w = world();
    w.runsBody.runs = [{ id: 'r1', state: 'running', path: 'host' }];
    await w.ctx._runsSeed('tab1');
    await settle();
    assert.deepStrictEqual(w.drawn, [], 'no card from the server draws nothing');
    assert.strictEqual(view(w).mode, 'stop-command', 'and the Stop command button still works');
  }

  console.log('host_command_composer: ok');
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
