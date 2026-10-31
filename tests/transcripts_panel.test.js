// Transcripts panel: rows paint before any per-row work finishes, share links resolve through a
// small pool, failures explain their cause, headers load only for visible rows, and the
// calendar button carries a visible text label.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'third-pane.js'),
  'utf8',
);

function cut(name) {
  const re = new RegExp('^(?:async )?function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?^\\}', 'm');
  const m = source.match(re);
  assert(m, name + ' found in third-pane.js');
  return m[0];
}
function cutConst(name) {
  const m = source.match(new RegExp('^const ' + name + ' = [^\\r\\n]*', 'm'));
  assert(m, name + ' found in third-pane.js');
  return m[0];
}

const code = [
  cutConst('_TX_LIST_TTL'),
  cutConst('_TX_RESOLVE_CONCURRENCY'),
  cutConst('_txListCache'),
  cut('_txRunPool'),
  cut('_txResolveMessage'),
  cut('_txResolveShare'),
  cut('_renderTranscriptsList'),
  cut('_buildRecordingRow'),
  cut('_buildTranscriptRow'),
  cut('_chatIdFromJoinUrl'),
  cut('_renderCalendarTranscriptCard'),
  '({ _renderTranscriptsList, _renderCalendarTranscriptCard, _txListCache });',
].join('\n');

class FakeEl {
  constructor(tag) {
    this.tag = tag;
    this.className = '';
    this.children = [];
    this._text = '';
    this._html = '';
    this.listeners = {};
    this.isConnected = true;
  }
  appendChild(c) {
    this.children.push(c);
    return c;
  }
  setAttribute() {}
  addEventListener(t, fn) {
    this.listeners[t] = fn;
  }
  set textContent(v) {
    this._text = String(v);
    this.children = [];
  }
  get textContent() {
    return this._text + this.children.map((c) => c.textContent).join('');
  }
  set innerHTML(v) {
    this._html = v;
    if (v === '') this.children = [];
  }
  get innerHTML() {
    return this._html;
  }
}

function deferred() {
  let resolve;
  const promise = new Promise((r) => (resolve = r));
  return { promise, resolve };
}
const flush = () => new Promise((r) => setImmediate(r));
const ok = (body) => Promise.resolve({ ok: true, json: async () => body });

function makeEnv({ recs, resolveReply }) {
  const state = {
    calls: [],
    resolveInFlight: 0,
    maxInFlight: 0,
    resolveDone: 0,
    observers: [],
    pending: [],
  };
  const fetch = (url) => {
    state.calls.push(url);
    if (url.startsWith('/api/teams/chats/')) return ok({ recordings: recs });
    if (url.startsWith('/api/recordings/resolve')) {
      const d = deferred();
      state.pending.push(d);
      state.resolveInFlight++;
      state.maxInFlight = Math.max(state.maxInFlight, state.resolveInFlight);
      const shareUrl = decodeURIComponent(url.split('share_url=')[1]);
      return d.promise.then(() => {
        state.resolveInFlight--;
        state.resolveDone++;
        return ok(resolveReply(shareUrl));
      });
    }
    if (url.endsWith('/transcripts')) return ok({ transcripts: [{ id: 't1' }] });
    if (url.endsWith('/header')) return ok({ duration_sec: 600, speakers: { a: 1 } });
    return Promise.resolve({ ok: false, json: async () => ({}) });
  };
  class IntersectionObserver {
    constructor(cb) {
      this.cb = cb;
      state.observers.push(this);
    }
    observe(el) {
      this.el = el;
    }
    disconnect() {
      this.done = true;
    }
  }
  const context = {
    document: { createElement: (t) => new FakeEl(t) },
    fetch,
    IntersectionObserver,
    Date,
    Map,
    Promise,
    encodeURIComponent,
    decodeURIComponent,
    Array,
    Object,
    _createPinBtn: () => new FakeEl('pin'),
    _openTranscriptDetail() {},
    _loadTeamsThread() {},
    openThirdPane() {},
  };
  return { api: vm.runInNewContext(code, context), state };
}

function rec(i, extra = {}) {
  return {
    drive_id: '',
    item_id: '',
    title: 'Weekly',
    original_name: 'Weekly.mp4',
    has_transcript: true,
    web_url: `https://amd.sharepoint.com/:v:/r${i}`,
    share_url: `https://amd.sharepoint.com/:v:/r${i}`,
    created_at: `2026-10-${String(20 - i).padStart(2, '0')}T15:00:00Z`,
    ...extra,
  };
}

const chat = { id: '19:meeting_x@thread.v2', topic: 'Weekly' };
const okReply = () => ({ drive_id: 'b!d', item_id: '01I', web_url: 'https://w', error: null });

(async () => {
  // Every row exists before any resolve finishes; at most 4 resolves run at once.
  {
    const recs = [0, 1, 2, 3, 4, 5].map((i) => rec(i));
    const { api, state } = makeEnv({ recs, resolveReply: okReply });
    const body = new FakeEl('div');
    const done = api._renderTranscriptsList(body, chat, {});
    await flush();
    assert.strictEqual(body.children.length, 6, 'all rows painted up front');
    assert.strictEqual(state.resolveDone, 0, 'no resolve finished yet');
    assert.strictEqual(state.resolveInFlight, 4, 'pool runs four at a time');
    while (state.pending.length) {
      state.pending.shift().resolve();
      await flush();
    }
    await done;
    assert.strictEqual(state.maxInFlight, 4, 'never more than four resolves in flight');
    assert.strictEqual(state.resolveDone, 6);
    // Headers wait for visibility.
    assert(
      !state.calls.some((u) => u.endsWith('/header')),
      'no header fetch before a row is visible',
    );
    assert.strictEqual(state.observers.length, 6);
    state.observers[0].cb([{ isIntersecting: true }]);
    await flush();
    assert.strictEqual(state.calls.filter((u) => u.endsWith('/header')).length, 1);
  }

  // Cause-specific messages.
  for (const [error, expect, forbid] of [
    ['expired', /expired/i, /sign in/i],
    ['auth', /sign in/i, /expired/i],
    ['failed', /couldn't load/i, /sign in|expired/i],
  ]) {
    const { api, state } = makeEnv({
      recs: [rec(0)],
      resolveReply: () => ({ drive_id: '', item_id: '', web_url: '', error }),
    });
    api._txListCache.clear();
    const body = new FakeEl('div');
    const done = api._renderTranscriptsList(body, chat, {});
    await flush();
    state.pending.shift().resolve();
    await done;
    const text = body.children[0].textContent;
    assert(expect.test(text), error + ': ' + text);
    assert(!forbid.test(text), error + ' must not say: ' + text);
  }

  // The list is cached per chat, so reopening does not refetch it.
  {
    const { api, state } = makeEnv({
      recs: [rec(0, { has_transcript: false })],
      resolveReply: okReply,
    });
    await api._renderTranscriptsList(new FakeEl('div'), chat, {});
    await api._renderTranscriptsList(new FakeEl('div'), chat, {});
    assert.strictEqual(state.calls.filter((u) => u.startsWith('/api/teams/chats/')).length, 1);
  }

  // A detached panel stops resolving.
  {
    const { api, state } = makeEnv({ recs: [rec(0), rec(1)], resolveReply: okReply });
    const body = new FakeEl('div');
    body.isConnected = false;
    await api._renderTranscriptsList(body, chat, {});
    assert.strictEqual(state.pending.length, 0, 'no resolves for a closed panel');
  }

  // The calendar popover button shows a text label next to the icon.
  {
    const { api } = makeEnv({ recs: [], resolveReply: okReply });
    const mount = new FakeEl('div');
    await api._renderCalendarTranscriptCard(
      mount,
      'evt',
      'Weekly',
      'https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc%40thread.v2/0',
    );
    assert.strictEqual(mount.children.length, 1);
    assert(/Transcripts<\/span>/.test(mount.children[0].innerHTML), mount.children[0].innerHTML);
  }

  // The Teams meeting header action carries the same label.
  assert(/id: 'tp-teams-transcripts'/.test(source));
  const action = source.match(
    /iconHtml:\s*'[^']*speaker_notes[^']*',\s*id: 'tp-teams-transcripts'/,
  );
  assert(action && /Transcripts<\/span>/.test(action[0]), 'Teams header action has a text label');

  console.log('transcripts_panel ok');
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
