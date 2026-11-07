// Draft approval cards stay where they were drafted when the user switches tabs and back.
// Runs the real draft-storage helpers from app.js against a fake localStorage.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

const NAMES = [
  '_loadTabDrafts',
  '_saveTabDrafts',
  '_draftTurnKey',
  '_draftAnchor',
  '_draftAfterIndex',
  '_storeTabDraft',
  '_removeTabDraft',
  '_placeTabDrafts',
  '_renderDraftItems',
];

function setup({ active = 'a', histories = {} } = {}) {
  const store = {};
  const injected = [];
  const fns = NAMES.map((name) => {
    const m = source.match(new RegExp(`function ${name}\\([^)]*\\) \\{[\\s\\S]*?\\n\\}`));
    assert(m, `${name} found in app.js`);
    return m[0];
  });
  const ctx = {
    localStorage: {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => {
        store[k] = String(v);
      },
    },
    console,
    document: { querySelector: () => null },
    _activeTabId: active,
    history: histories[active] || [],
    _loadTabHistory: (id) => histories[id] || [],
    _injectDraftApprovalCard: (draft, data, opts) => injected.push({ draft, data, opts }),
  };
  vm.createContext(ctx);
  vm.runInContext(fns.join('\n') + `;this.api = { ${NAMES.join(', ')} };`, ctx);
  return { api: ctx.api, ctx, injected };
}

const u = (content) => ({ role: 'user', content });
const a = (content) => ({ role: 'assistant', content });
const draft = (id) => ({ draft_id: id });
const ids = (items) => [...items.map((i) => i.data.draft_id)];

// A draft stored while a turn runs lands after that turn's reply, not at the bottom of the chat.
{
  const hist = [u('one'), a('r1'), u('two'), a('r2'), u('three'), a('r3')];
  const { api, ctx } = setup({ histories: { a: [u('one'), a('r1'), u('two')], b: [u('x')] } });
  api._storeTabDraft('a', 'email-reply', draft('d1'));
  ctx.history.push(a('r2'), u('three'), a('r3'));
  const placed = api._placeTabDrafts('a', hist);
  assert.strictEqual(placed.rest.length, 0);
  assert.deepStrictEqual([...placed.byIndex.keys()], [3], 'card follows the second reply');
  assert.strictEqual(placed.byIndex.get(3)[0].data.draft_id, 'd1');
}

// A draft for a tab the user is not looking at is anchored in that tab's own saved history.
{
  const { api } = setup({
    active: 'a',
    histories: { a: [u('mine')], b: [u('q1'), a('r1'), u('q2')] },
  });
  api._storeTabDraft('b', 'email-reply', draft('d2'));
  const hist = [u('q1'), a('r1'), u('q2'), a('r2')];
  assert.deepStrictEqual([...api._placeTabDrafts('b', hist).byIndex.keys()], [3]);
}

// A turn still waiting for its reply shows the card under the user's message.
{
  const { api } = setup({ histories: { a: [u('one'), a('r1'), u('two')] } });
  api._storeTabDraft('a', 'email-reply', draft('d3'));
  const placed = api._placeTabDrafts('a', [u('one'), a('r1'), u('two')]);
  assert.deepStrictEqual([...placed.byIndex.keys()], [2]);
}

// Two drafts in one turn keep their order; drafts from different turns stay in their own turns.
{
  const { api, ctx } = setup({ histories: { a: [u('one')] } });
  api._storeTabDraft('a', 'email-reply', draft('d4'));
  api._storeTabDraft('a', 'email-reply', draft('d5'));
  ctx.history.push(a('r1'), u('two'));
  api._storeTabDraft('a', 'calendar-event', draft('d6'));
  const placed = api._placeTabDrafts('a', [u('one'), a('r1'), u('two'), a('r2')]);
  assert.deepStrictEqual(ids(placed.byIndex.get(1)), ['d4', 'd5']);
  assert.deepStrictEqual(ids(placed.byIndex.get(3)), ['d6']);
}

// Once old messages roll off the saved history, the card still finds its turn.
{
  const { api, ctx } = setup({ histories: { a: [u('one'), a('r1'), u('target')] } });
  api._storeTabDraft('a', 'email-reply', draft('d7'));
  ctx.history.length = 0;
  const trimmed = [u('target'), a('r'), u('later'), a('r')];
  assert.deepStrictEqual([...api._placeTabDrafts('a', trimmed).byIndex.keys()], [1]);
}

// A draft whose turn is gone, or that predates positions, is shown after the last message.
{
  const { api } = setup({ histories: { a: [u('one')] } });
  api._storeTabDraft('a', 'email-reply', draft('d8'));
  assert.strictEqual(api._placeTabDrafts('a', [u('unrelated')]).rest.length, 1);
  api._saveTabDrafts('a', [{ draft: 'email-reply', data: draft('old'), created_at: 1 }]);
  assert.strictEqual(api._placeTabDrafts('a', [u('one'), a('r1')]).rest.length, 1);
  assert.strictEqual(api._placeTabDrafts('a', []).rest.length, 1);
}

// Storing the same draft again keeps its place; removing it clears it.
{
  const { api, ctx } = setup({ histories: { a: [u('one')] } });
  api._storeTabDraft('a', 'email-reply', draft('d9'));
  ctx.history.push(a('r1'), u('two'), a('r2'));
  api._storeTabDraft('a', 'email-reply', draft('d9'));
  const stored = api._loadTabDrafts('a');
  assert.strictEqual(stored.length, 1);
  assert.strictEqual(stored[0].anchor.index, 1);
  api._removeTabDraft('a', 'd9');
  assert.strictEqual(api._loadTabDrafts('a').length, 0);
}

// Restoring a card renders it without scrolling the chat to it.
{
  const { api, injected } = setup();
  api._renderDraftItems('a', [{ draft: 'email-reply', data: draft('d10') }], false);
  assert.strictEqual(injected.length, 1);
  assert.strictEqual(injected[0].opts.scroll, false);
  assert.strictEqual(injected[0].opts.persist, false);
}

// switchTab renders each card right after its message, and the rest at the end.
{
  const sw = source.match(/function switchTab\([^)]*\) \{[\s\S]*?\n\}/);
  assert(sw, 'switchTab found');
  const body = sw[0];
  const loop = body.indexOf('history.forEach((m, idx) => {');
  const inLoop = body.indexOf('_renderDraftItems(tabId, _tabDrafts.byIndex.get(idx)', loop);
  const rest = body.indexOf('_renderDraftItems(tabId, _tabDrafts.rest', inLoop);
  assert(loop > 0 && inLoop > loop && rest > inLoop, 'cards render inside the history loop');
  assert(!/_renderTabDrafts\(tabId\)/.test(body), 'no append-everything-at-the-end restore');
}

// A draft handed to Outlook is forgotten, for both the email and calendar cards.
{
  const handoffs = source.match(
    /(handedOffUrl = url;|const \{ url \} = await res\.json\(\);\r?\n\s+lockHeader\(\);)\s*\n?\s*_removeTabDraft\(ownerTabId, draftId\);/g,
  );
  assert.strictEqual(
    (handoffs || []).length,
    2,
    'both Open in Outlook paths drop the stored draft',
  );
}

console.log('tab_draft_placement ok');
