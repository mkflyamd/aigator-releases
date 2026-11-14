const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'third-pane.js'), 'utf8');
const m = source.match(/async function _unpinItem\([^)]*\)\s*\{[\s\S]*?\n\}/);
assert(m, '_unpinItem not found in third-pane.js');

function makeCtx(pins, response) {
  const calls = { fetch: [], modal: [], sync: 0 };
  const ctx = {
    _activeTabId: 'tabB',
    _cachedPinsContextId: 'tabB',
    _cachedPins: pins,
    _pinnedItemsCache: new Set(['slack::C1']),
    _syncAllPinUI: () => {
      calls.sync += 1;
    },
    escapeHtml: (s) => String(s).replace(/</g, '&lt;'),
    _showConfirmModal: (title, body, label, onConfirm) => calls.modal.push({ title, body, label, onConfirm }),
    fetch: async (url, opts) => {
      calls.fetch.push({ url, opts });
      return { ok: true, json: async () => response };
    },
  };
  vm.createContext(ctx);
  vm.runInContext(`${m[0]}\nthis._unpinItem = _unpinItem;`, ctx);
  return { ctx, calls };
}

(async () => {
  // global pin: asks first, no fetch and no optimistic change until confirmed
  {
    const { ctx, calls } = makeCtx(
      [{ source: 'slack', id: 'C1', label: '<b>x</b>', scope: 'global' }],
      { unpinned: true },
    );
    await ctx._unpinItem('slack', 'C1');
    assert.strictEqual(calls.fetch.length, 0);
    assert.strictEqual(calls.modal.length, 1);
    assert.strictEqual(calls.modal[0].title, 'Remove global pin');
    assert(calls.modal[0].body.includes('&lt;b>x&lt;/b>'), 'label must be escaped');
    assert(ctx._pinnedItemsCache.has('slack::C1'));
    await calls.modal[0].onConfirm();
    assert.strictEqual(calls.fetch.length, 1);
    assert(calls.fetch[0].url.endsWith('?context_id=tabB&scope=global'), calls.fetch[0].url);
    assert(!ctx._pinnedItemsCache.has('slack::C1'));
  }

  // tab pin: unchanged behaviour, no modal, no scope
  {
    const { ctx, calls } = makeCtx([{ source: 'slack', id: 'C1', label: 'x' }], { unpinned: true });
    await ctx._unpinItem('slack', 'C1');
    assert.strictEqual(calls.modal.length, 0);
    assert(calls.fetch[0].url.endsWith('?context_id=tabB'), calls.fetch[0].url);
    assert(!ctx._pinnedItemsCache.has('slack::C1'));
  }

  // server says nothing was unpinned: button state rolls back
  {
    const { ctx } = makeCtx([{ source: 'slack', id: 'C1', label: 'x' }], { unpinned: false });
    await ctx._unpinItem('slack', 'C1');
    assert(ctx._pinnedItemsCache.has('slack::C1'));
  }
  console.log('global_unpin_item: all assertions passed');
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
