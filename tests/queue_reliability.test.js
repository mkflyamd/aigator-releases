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
  '_queueSendSettled',
  '_queuePostSettled',
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

  // The retry count survives a send that looked started: the drain resolves as soon as the form is submitted, and the
  // POST answers later. A POST that keeps coming back "not yet" (409) or never answers (thrown) is retried a bounded
  // number of times in total, then the failsafe shows once.
  for (const [label, status, code] of [
    ['a refused POST (409)', 409, 'turn_in_progress'],
    ['a thrown POST', 0, ''],
  ]) {
    const w = world({ heads: Array(20).fill({ item: { id: 'a' } }) });
    await w.ctx._queueDrain('tab1');
    let guard = 0;
    for (;;) {
      w.ctx._queuePostSettled('tab1', status, code);
      if (!w.pending().length || guard++ > 20) break;
      assert.strictEqual(w.ctx._queueStatus('tab1', 0).kind, 'starting', `${label}: retrying, not failed yet`);
      assert.match(w.ctx._queueStatus('tab1', 9000).text, /retry/i, `${label}: says it is retrying until the cap`);
      await w.fire(0);
    }
    assert.strictEqual(count(w.calls, 'submit:a'), 4, `${label}: the first send plus one retry per schedule entry, then stop`);
    assert.strictEqual(w.pending().length, 0, `${label}: nothing left scheduled`);
    const status2 = w.ctx._queueStatus('tab1', 0);
    assert.strictEqual(status2.kind, 'failsafe', `${label}: the failsafe shows at the cap, not later`);
    assert.strictEqual(w.ctx._queueStatus('tab1', 50).kind, 'failsafe');
    // A later settle (another refusal) does not start a new round of retries.
    w.ctx._queuePostSettled('tab1', status, code);
    assert.strictEqual(w.pending().length, 0, `${label}: a late answer does not reset the count`);
    // The user sending it by hand starts afresh.
    w.ctx._queueRearmStop('tab1');
    w.ctx._queuePostSettled('tab1', status, code);
    assert.strictEqual(w.pending().length, 1, `${label}: Send now, Resume and a new enqueue reset the count`);
  }

  // An accepted POST starts the next message afresh; other answers that leave the message queued do not retry.
  {
    const w = world({ heads: Array(20).fill({ item: { id: 'a' } }) });
    await w.ctx._queueDrain('tab1');
    w.ctx._queuePostSettled('tab1', 409, 'turn_in_progress');
    assert.strictEqual(w.ctx._queueRearms.get('tab1').tries, 1);
    await w.fire(0);
    w.ctx._queuePostSettled('tab1', 200, '');
    assert(!w.ctx._queueRearms.has('tab1'), 'an accepted POST forgets the retries');
    w.ctx._queuePostSettled('tab1', 409, 'queue_paused');
    w.ctx._queuePostSettled('tab1', 409, 'queue_item_gone');
    assert.strictEqual(w.pending().length, 0, 'a refusal that retrying cannot fix is not retried');
  }

  // A refused attempt takes its transcript entries back, so the retries never stack up user bubbles.
  {
    const store = new Map();
    const bubbles = [];
    const savedHistory = [];
    const ctx = {
      localStorage: { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) },
      console: { warn() {} },
      _saveTabHistory: (_tab, h) => savedHistory.push(h.length),
    };
    vm.createContext(ctx);
    vm.runInContext(
      ['_saveTabDisplayHtml', '_unsaveTabDisplayHtml', '_discardUnsentQueuedSend'].map(functionSource).join('\n'),
      ctx,
    );
    const history = [];
    const attempt = () => {
      const bubble = (kind) => {
        const el = { kind, remove: () => bubbles.splice(bubbles.indexOf(el), 1) };
        bubbles.push(el);
        return el;
      };
      const userMsg = bubble('user');
      const entry = { role: 'user', content: 'hi' };
      history.push(entry);
      ctx._saveTabDisplayHtml('tab1', 'hi', 10);
      return { userMsg, assistantMsg: bubble('assistant'), entry, history };
    };
    const users = () => bubbles.filter((b) => b.kind === 'user').length;
    for (let i = 0; i < 4; i++) {
      ctx._discardUnsentQueuedSend('tab1', attempt());
      assert.strictEqual(bubbles.length, 0, 'a refused attempt leaves no bubble behind');
      assert.strictEqual(history.length, 0, 'and no history entry');
      assert.deepStrictEqual(JSON.parse(store.get('tab-disp-tab1')), [], 'and nothing in the saved display');
    }
    history.push({ role: 'user', content: 'earlier' });
    attempt();
    assert.strictEqual(users(), 1, 'the accepted attempt has exactly one user bubble');
    assert.strictEqual(history.length, 2);
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

  // Clicking the Queue pill queues the message the same way Enter does: once, the reply keeps running, the
  // composer clears. (The real click handler, _requestTypedSubmit and _queueComposerMessage run against stubs; the
  // form's submit handler is stood in for by its first routing rule: a typed submit while a reply runs is queued.)
  {
    const run = async ({ text = 'hello', images = [], chips = [], clicks = 1, target = 'send', dropdown = false }) => {
      const posts = [];
      const resets = [];
      let stops = 0;
      let prevented = 0;
      const input = {
        textContent: text,
        style: {},
        dataset: {},
        querySelector: (selector) =>
          chips.some((c) => selector.split(',').map((x) => x.trim()).includes(c)) ? {} : null,
      };
      const sendBtn = {
        classList: { contains: () => true },
        getBoundingClientRect: () => ({ left: 0, right: 10, top: 0, bottom: 10 }),
        contains: (t) => t === 'send',
      };
      const stopBtn = { hidden: false, contains: (t) => t === 'stop' };
      const form = { requestSubmit: () => ctx._queueComposerMessage() };
      let closed = 0;
      const ctx = {
        window: {},
        crypto: { randomUUID: () => `id-${posts.length}` },
        console: { warn() {} },
        _activeTabId: 'tab1',
        _chatTaskIds: new Map([['tab1', 'task']]),
        _activeStops: new Set([() => stops++]),
        _aigatorImages: images,
        _queueComposing: new Set(),
        _slashDropdown: null,
        _mentionDropdown: dropdown ? {} : null,
        _pinDropdown: null,
        _channelDropdown: null,
        closeMentionDropdown: () => {
          closed++;
          ctx._mentionDropdown = null;
        },
        closePinDropdown: () => {
          ctx._pinDropdown = null;
        },
        closeChannelDropdown: () => {
          ctx._channelDropdown = null;
        },
        _getInputText: () => input.textContent,
        buildFinalMessage: (t) => t,
        _showConnectivityToast: () => {},
        _renderAigatorPreviews: () => {},
        _updateSendSlot: () => {},
        _updatePlaceholder: () => {},
        _queueSet: () => {},
        _queueRearmStop: (tab) => resets.push(tab),
        _queueDrain: () => {},
        _queueCall: async (method, url, body) => {
          posts.push({ method, url, body });
          return { items: [{ id: body.id }], paused: false };
        },
        _canSubmitMessage: (a, b, c) => Boolean(a || b || c),
        document: {
          getElementById: (id) =>
            ({ 'chat-input': input, 'chat-form': form, 'composer-stop-btn': stopBtn })[id] || null,
        },
        sendBtn,
        form,
      };
      vm.createContext(ctx);
      vm.runInContext(
        [
          '_composerButtonMode',
          '_composerCanQueue',
          '_queueRefusal',
          '_shouldStopFromClick',
          '_requestTypedSubmit',
          '_onComposerButtonClick',
          '_closeComposerDropdowns',
          '_queueComposerMessage',
        ]
          .map(functionSource)
          .join('\n') + '\nlet _enterSubmit = false;',
        ctx,
      );
      for (let i = 0; i < clicks; i++) {
        ctx._onComposerButtonClick({
          button: 0,
          target,
          clientX: 5,
          clientY: 5,
          preventDefault: () => prevented++,
        });
      }
      await new Promise((resolve) => setImmediate(resolve));
      return { posts, stops, prevented, input, ctx, resets, closed };
    };
    const queued = await run({});
    assert.strictEqual(queued.posts.length, 1, 'a click on the Queue pill enqueues exactly once');
    assert.strictEqual(queued.posts[0].url, '/api/queue');
    assert.strictEqual(queued.posts[0].body.payload.text, 'hello');
    assert.strictEqual(queued.stops, 0, 'the reply keeps running');
    assert(queued.ctx._chatTaskIds.has('tab1'), 'the reply is still registered');
    assert.strictEqual(queued.input.textContent, '', 'the composer clears');
    assert.strictEqual(queued.prevented, 1, 'the click is handled, not passed on');
    assert.deepStrictEqual(queued.resets, ['tab1'], 'a new queued message starts a fresh retry count');
    assert.strictEqual((await run({ clicks: 2 })).posts.length, 1, 'a double click still queues once');
    assert.strictEqual(
      (await run({ images: [{ name: 'a.png', base64: 'x' }], text: '' })).posts.length,
      1,
      'an attachment alone queues',
    );
    const stopped = await run({ text: '' });
    assert.strictEqual(stopped.stops, 1, 'an empty composer: the same button stops the reply');
    assert.strictEqual(stopped.posts.length, 0, 'and queues nothing');
    const split = await run({ target: 'stop' });
    assert.strictEqual(split.stops, 1, 'the separate Stop button stops');
    assert.strictEqual(split.posts.length, 0, 'and queues nothing');
    const open = await run({ dropdown: true });
    assert.strictEqual(open.posts.length, 1, 'a click on the Queue pill queues even with a mention dropdown open');
    assert.strictEqual(open.closed, 1, 'the dropdown is closed first');
    assert.strictEqual(open.stops, 0);
    const slash = await run({ text: '/help' });
    assert.strictEqual(slash.posts.length, 0, 'a slash command is not queued');
    assert.strictEqual(slash.stops, 1, 'so the button is Stop, not Queue');
  }

  // The button says Queue only for what the queue will take (the server refuses empty text without an image and a
  // leading "/"; the client refuses Jira attachments, pin references and @mentions).
  {
    const canQueue = (box) => {
      const ctx = {
        _aigatorImages: box.images || [],
        _getInputText: () => box.text || '',
        buildFinalMessage: (t) => t || box.skillPrompt || '',
        document: {
          getElementById: () => ({
            querySelector: (selector) =>
              (box.chips || []).some((c) => selector.split(',').map((x) => x.trim()).includes(c))
                ? {}
                : null,
          }),
        },
      };
      vm.createContext(ctx);
      vm.runInContext(
        ['_composerCanQueue', '_queueRefusal', '_composerButtonMode'].map(functionSource).join('\n'),
        ctx,
      );
      return { can: ctx._composerCanQueue(), mode: ctx._composerButtonMode(true, ctx._composerCanQueue()) };
    };
    assert.strictEqual(canQueue({}).mode, 'stop', 'an empty composer while a reply runs is Stop');
    assert.strictEqual(canQueue({ text: '   ' }).mode, 'stop', 'whitespace is empty');
    assert.strictEqual(canQueue({ text: 'hi' }).mode, 'queue');
    assert.strictEqual(canQueue({ images: [{ name: 'a.png' }] }).mode, 'queue', 'an attached file alone is queueable');
    assert.strictEqual(
      canQueue({ text: '[File: C:/a.txt]', chips: ['[data-file-path]'] }).mode,
      'queue',
      'a file chip is queueable',
    );
    assert.strictEqual(canQueue({ skillPrompt: 'summarize' }).mode, 'queue', 'a skill chip with a prompt is queueable');
    assert.strictEqual(
      canQueue({ chips: ['.inline-chip'] }).mode,
      'stop',
      'a skill chip with no text and no prompt has nothing to queue',
    );
    assert.strictEqual(canQueue({ text: '/help' }).mode, 'stop', 'a slash command is refused');
    assert.strictEqual(canQueue({ text: 'hi', chips: ['.pin-ref-chip'] }).mode, 'stop', 'a pin reference is refused');
    assert.strictEqual(canQueue({ text: 'hi', chips: ['.chip-person'] }).mode, 'stop', 'an @mention is refused');
    assert.strictEqual(
      canQueue({ text: 'hi', images: [{ name: 'a', jiraAttachment: {} }] }).mode,
      'stop',
      'a Jira attachment is refused',
    );
  }

  // The failsafe status: after the retry cap it shows once with Send now and Clear, and Send now starts afresh.
  {
    const w = world({ heads: Array(20).fill({ item: { id: 'a' } }) });
    const el = () => ({
      children: [],
      dataset: {},
      listeners: {},
      setAttribute() {},
      append(...n) {
        this.children.push(...n);
      },
      appendChild(n) {
        this.children.push(n);
        return n;
      },
      replaceChildren(...n) {
        this.children = n;
      },
      addEventListener(type, fn) {
        this.listeners[type] = fn;
      },
    });
    const row = el();
    w.ctx.document = { getElementById: () => row, createElement: el };
    w.ctx._queueChip = () => el();
    vm.runInContext(
      ['_renderQueue', '_queueButton'].map(functionSource).join('\n') + '\nlet _queueRenderTimer = 0;',
      w.ctx,
    );
    await w.ctx._queueDrain('tab1');
    let guard = 0;
    for (;;) {
      w.ctx._queuePostSettled('tab1', 409, 'turn_in_progress');
      if (!w.pending().length || guard++ > 20) break;
      await w.fire(0);
    }
    const bars = () => row.children.filter((c) => c.dataset && c.dataset.queueStatus);
    assert.strictEqual(bars().length, 1, 'the status bar shows once');
    assert.strictEqual(bars()[0].dataset.queueStatus, 'failsafe', 'and it is the failsafe, as soon as the cap is hit');
    const buttons = () => bars()[0].children.filter((c) => c.listeners && c.listeners.click);
    assert.deepStrictEqual(buttons().map((b) => b.textContent), ['Send now', 'Clear']);
    w.ctx._renderQueue();
    assert.strictEqual(bars().length, 1, 'rendering again does not stack a second bar');
    const submitsBefore = count(w.calls, 'submit:a');
    buttons()[0].listeners.click();
    await new Promise((r) => setImmediate(r));
    assert.strictEqual(count(w.calls, 'submit:a'), submitsBefore + 1, 'Send now tries again');
    assert(!w.ctx._queueRearms.has('tab1'), 'and the retry count is reset');
    w.ctx._queuePostSettled('tab1', 409, 'turn_in_progress');
    assert.strictEqual(w.ctx._queueRearms.get('tab1').tries, 1, 'the new round starts from the first retry');
    assert.strictEqual(w.pending().length, 1, 'with a retry scheduled again');
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
