// A queued message always leaves on its own: the drain asks again when the server says "not yet" or a send
// fails, never double-sends, shows the "Send now" failsafe, and the composer button never stops a reply
// when the user meant to queue. The real functions are cut out of app.js and run against stubs.

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

const FUNCTIONS = [
  '_queueDrain',
  '_queueCardHold',
  '_queueBusyStart',
  '_queueBusyEnd',
  '_queueRearm',
  '_queueRearmStop',
  '_queueStatus',
  '_composerButtonMode',
];

function world({ heads = [], submit } = {}) {
  const calls = [];
  const timers = [];
  const queue = [...heads];
  const ctx = {
    _activeTabId: 'tab1',
    _queueBusy: new Set(),
    _queueBusyTimers: new Map(),
    _queueRearms: new Map(),
    _queueDirty: new Set(),
    _queueIdleSince: new Map(),
    _queueByTab: new Map([['tab1', { items: [{ id: 'a' }], paused: false }]]),
    _QUEUE_REARM_MS: [500, 500, 1000],
    _QUEUE_FAILSAFE_MS: 3000,
    _pendingSandboxFollowUps: new Set(),
    _pendingSandboxCards: new Map(),
    _pendingTabCards: new Map(),
    _chatTaskIds: new Map(),
    console: { warn() {} },
    _renderQueue: () => {},
    _queueRefresh: () => calls.push('refresh'),
    setTimeout: (fn, ms) => {
      timers.push({ fn, ms });
      return timers.length;
    },
    clearTimeout: (id) => {
      if (timers[id - 1]) timers[id - 1].fn = null;
    },
    _queueCall: async () => {
      calls.push('head');
      const next = queue.shift();
      if (next instanceof Error) throw next;
      return next || { item: null };
    },
    _submitQueuedItem: async (item) => {
      calls.push(`submit:${item.id}`);
      if (submit) await submit();
    },
  };
  vm.createContext(ctx);
  vm.runInContext(FUNCTIONS.map(functionSource).join('\n'), ctx);
  // Timers still waiting to fire (a cleared timer, such as the busy expiry, is not one).
  const pending = () => timers.filter((t) => t.fn);
  const fire = async (index) => {
    const t = pending()[index];
    const fn = t.fn;
    t.fn = null;
    fn();
    await new Promise((resolve) => setImmediate(resolve));
  };
  return { ctx, calls, timers: { get length() { return pending().length; }, get 0() { return pending()[0]; } }, fire, pending };
}

const count = (calls, what) => calls.filter((c) => c === what).length;

(async () => {
  // The server says a turn is still finishing: nothing is sent yet, then the re-arm sends the item once.
  {
    const w = world({ heads: [{ item: null, live: true }, { item: { id: 'a' } }] });
    await w.ctx._queueDrain('tab1');
    assert.strictEqual(count(w.calls, 'submit:a'), 0, 'a live turn sends nothing yet');
    assert.strictEqual(w.timers.length, 1, 'a re-arm is scheduled');
    assert.strictEqual(w.timers[0].ms, 500);
    assert(!w.ctx._queueBusy.has('tab1'), 'the busy mark is released while waiting');
    await w.fire(0);
    assert.strictEqual(count(w.calls, 'submit:a'), 1, 'the re-armed drain sends the head once');
  }

  // A send that throws (a thrown fetch, a refused POST) frees the tab and asks again.
  {
    let first = true;
    const w = world({
      heads: [{ item: { id: 'a' } }, { item: { id: 'a' } }],
      submit: async () => {
        if (first) {
          first = false;
          throw new Error('network down');
        }
      },
    });
    await w.ctx._queueDrain('tab1');
    assert(!w.ctx._queueBusy.has('tab1'), 'a failed send does not leave the tab busy');
    assert.strictEqual(w.timers.length, 1, 'a failed send re-arms');
    await w.fire(0);
    assert.strictEqual(count(w.calls, 'submit:a'), 2, 'the retry sends again');
  }

  // Re-arming is bounded: it never loops forever against a server that keeps saying "not yet".
  {
    const w = world({ heads: Array(10).fill({ item: null, live: true }) });
    await w.ctx._queueDrain('tab1');
    let fired = 0;
    while (w.pending().length && fired < 10) {
      await w.fire(0);
      fired++;
    }
    assert.strictEqual(fired, 3, 'one re-arm per entry in the schedule, then stop');
    assert.strictEqual(count(w.calls, 'head'), 4, 'the first ask plus three re-arms');
  }

  // A paused queue is left alone.
  {
    const w = world({ heads: [{ item: null, live: true }] });
    w.ctx._queueByTab.set('tab1', { items: [{ id: 'a' }], paused: true });
    await w.ctx._queueDrain('tab1');
    assert.strictEqual(w.timers.length, 0, 'a paused queue is not re-armed');
  }

  // A drain asked for while the head request is in flight is remembered and run after it settles.
  {
    let release;
    const w = world();
    w.ctx._queueCall = () =>
      new Promise((resolve) => {
        w.calls.push('head');
        release = () => resolve({ item: null });
      });
    const first = w.ctx._queueDrain('tab1');
    await w.ctx._queueDrain('tab1');
    assert.strictEqual(count(w.calls, 'head'), 1, 'a drain during an in-flight one does not start a second');
    assert(w.ctx._queueDirty.has('tab1'), 'it is remembered');
    release();
    await first;
    assert.strictEqual(w.timers.length, 1, 'the remembered drain runs after the first settles');
    assert.strictEqual(w.timers[0].ms, 0);
  }

  // Several signals at once (chat_done, focus, re-arm) still give exactly one submit.
  {
    const w = world({ heads: [{ item: { id: 'a' } }, { item: { id: 'a' } }] });
    let release;
    w.ctx._submitQueuedItem = (item) =>
      new Promise((resolve) => {
        w.calls.push(`submit:${item.id}`);
        release = resolve;
      });
    const first = w.ctx._queueDrain('tab1');
    await new Promise((r) => setImmediate(r));
    await w.ctx._queueDrain('tab1');
    await w.ctx._queueDrain('tab1', true);
    release();
    await first;
    assert.strictEqual(count(w.calls, 'submit:a'), 1, 'one turn end gives one submit');
  }

  // The failsafe: "Sending next message" first, "Didn't send automatically" only after about 3 s.
  {
    const w = world();
    const early = w.ctx._queueStatus('tab1', 1000);
    assert.strictEqual(early.kind, 'starting');
    assert.strictEqual(early.recheckMs, 3000);
    assert.strictEqual(w.ctx._queueStatus('tab1', 3900).kind, 'starting', 'not before the window ends');
    const late = w.ctx._queueStatus('tab1', 4000);
    assert.strictEqual(late.kind, 'failsafe');
    assert.strictEqual(late.tone, 'danger');
    w.ctx._chatTaskIds.set('tab1', 'task');
    assert.strictEqual(w.ctx._queueStatus('tab1', 9000).kind, 'running', 'a running reply is not a failure');
    assert.strictEqual(w.ctx._queueStatus('tab1', 9500).tone, 'neutral');
    w.ctx._queueByTab.set('tab1', { items: [], paused: false });
    assert.strictEqual(w.ctx._queueStatus('tab1', 9500), null, 'an empty queue shows nothing');
  }

  // The composer button: Stop only when nothing is typed; Queue when something is.
  {
    const mode = world().ctx._composerButtonMode;
    assert.strictEqual(mode(false, false), 'send');
    assert.strictEqual(mode(false, true), 'send');
    assert.strictEqual(mode(true, false), 'stop');
    assert.strictEqual(mode(true, true), 'queue');
  }

  // The click handler: with text typed, a click on the send button queues (never stops); empty, it stops;
  // the separate Stop button always stops.
  {
    const marker = "document.addEventListener(\n  'click',\n  (e) => {\n    if (!_activeStops.size) return;";
    const start = source.indexOf(marker);
    assert(start > 0, 'stop click handler found');
    const tail = '  true,\n);';
    const end = source.indexOf(tail, start) + tail.length;
    const modeFn = functionSource('_composerButtonMode');
    const run = (hasText, onStopBtn) => {
      let handler;
      let stops = 0;
      const sendBtn = {
        classList: { contains: () => true },
        getBoundingClientRect: () => ({ left: 0, right: 10, top: 0, bottom: 10 }),
      };
      const stopBtn = { hidden: !hasText, contains: (t) => t === 'stop' };
      const ctx = {
        _activeStops: new Set([() => stops++]),
        sendBtn,
        document: {
          addEventListener: (_type, fn) => (handler = fn),
          getElementById: (id) => (id === 'composer-stop-btn' ? stopBtn : null),
        },
        _composerHasContent: () => hasText,
        _shouldStopFromClick: (e, _btn, _rect, streaming) => streaming && e.inside,
      };
      vm.createContext(ctx);
      vm.runInContext(`${modeFn}\n${source.slice(start, end)}`, ctx);
      handler({ target: onStopBtn ? 'stop' : 'send', inside: !onStopBtn, preventDefault() {} });
      return stops === 1;
    };
    assert.strictEqual(run(true, false), false, 'a click on Queue does not stop the reply');
    assert.strictEqual(run(false, false), true, 'a click on Stop (empty composer) stops');
    assert.strictEqual(run(true, true), true, 'the separate Stop button stops');
  }

  // Attachments and chips count as content: with a file attached and an empty box the button is Queue, not Stop.
  {
    const hasContent = (box) => {
      const ctx = {
        _aigatorImages: box.images || [],
        document: {
          getElementById: () => ({
            textContent: box.text || '',
            querySelector: (selector) =>
              (box.chips || []).some((c) => selector.split(',').map((x) => x.trim()).includes(c))
                ? {}
                : null,
          }),
        },
      };
      vm.createContext(ctx);
      vm.runInContext(`${functionSource('_composerHasContent')}
${functionSource('_composerButtonMode')}`, ctx);
      return { has: ctx._composerHasContent(), mode: ctx._composerButtonMode(true, ctx._composerHasContent()) };
    };
    assert.strictEqual(hasContent({}).mode, 'stop', 'an empty composer while a reply runs is Stop');
    assert.strictEqual(hasContent({ text: '  ' }).mode, 'stop', 'whitespace is empty');
    assert.strictEqual(hasContent({ text: 'hi' }).mode, 'queue');
    assert.strictEqual(hasContent({ images: [{ name: 'a.png' }] }).mode, 'queue', 'an attached file is content');
    assert.strictEqual(hasContent({ chips: ['[data-file-path]'] }).mode, 'queue', 'a file chip is content');
    assert.strictEqual(hasContent({ chips: ['.inline-chip'] }).mode, 'queue', 'an inline chip is content');
    assert.strictEqual(hasContent({ chips: ['.pin-ref-chip'] }).mode, 'queue', 'a pin reference chip is content');
  }

  // Markup: Stop has its label, Queue has its own icon and word, idle Send stays a plain arrow.
  {
    const html = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'index.html'), 'utf8');
    assert.strictEqual(
      (html.match(/id="composer-stop-btn"/g) || []).length,
      1,
      'the id is unique (the server panel has its own stop-btn)',
    );
    const stop = html.match(/<button[^>]*id="composer-stop-btn"[^>]*>/);
    assert(stop, 'separate Stop button found');
    assert.match(stop[0], /title="Stop reply"/, 'the separate Stop button has a title');
    assert.match(stop[0], /aria-label="Stop reply"/, 'the separate Stop button has an aria-label');
    const send = html.slice(html.indexOf('id="send-btn"'), html.indexOf('<!-- /#chat-send-slot -->'));
    assert.match(send, /class="queue-icon"/, 'the send button carries a queue icon');
    assert.match(send, /class="queue-label"[^>]*>\s*Queue\s*</, 'the send button carries the word Queue');
    assert.match(send, /class="send-icon/, 'idle Send keeps its arrow');
  }

  console.log('queue reliability: ok');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
