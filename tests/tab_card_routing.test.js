// An approval card belongs to the tab whose turn asked; another tab only gets a cue until it is shown.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { test } = require('node:test');

const app = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');
const pick = (name) => {
  const m = app.match(new RegExp(String.raw`\nfunction ${name}\([^)]*\)\s*\{[\s\S]*?\n\}`));
  assert(m, `${name} not found in app.js`);
  return m[0];
};

function setup(activeTabId) {
  const log = { toasts: [], expired: [], classed: [] };
  const ctx = {
    _pendingTabCards: new Map(),
    _tabsWithUpdates: new Set(),
    _activeTabId: activeTabId,
    _showConnectivityToast: (m) => log.toasts.push(m),
    _expireConfirmCardById: (id) => log.expired.push(id),
    document: {
      querySelector: (sel) => ({ classList: { add: (c) => log.classed.push([sel, c]) } }),
    },
  };
  const names = [
    '_markTabNeedsAttention',
    '_routeCardToTab',
    '_resolveTabCard',
    '_expireTabCard',
    '_renderTabCards',
    '_dropStaleTabCards',
  ];
  vm.runInNewContext(
    `${names.map(pick).join('\n')}\nthis.api = { ${names.join(', ')} };`,
    ctx,
  );
  return { ctx, api: ctx.api, log };
}

test('a card for the tab on screen is drawn at once', () => {
  const { api, log } = setup('A');
  let drawn = 0;
  api._routeCardToTab('A', 'c1', () => drawn++);
  assert.strictEqual(drawn, 1);
  assert.strictEqual(log.toasts.length, 0);
});

test('a card for another tab is held, the tab is flagged, and it is drawn when that tab is shown', () => {
  const { ctx, api, log } = setup('B');
  let drawn = 0;
  api._routeCardToTab('A', 'c1', () => drawn++);
  assert.strictEqual(drawn, 0);
  assert(ctx._tabsWithUpdates.has('A'));
  assert.deepStrictEqual(log.classed[0][1], 'tab-has-update');
  assert.strictEqual(log.toasts.length, 1);
  api._renderTabCards('A');
  assert.strictEqual(drawn, 1);
  api._renderTabCards('B');
  assert.strictEqual(drawn, 1);
});

test('an answered card is not drawn again', () => {
  const { api } = setup('B');
  let drawn = 0;
  api._routeCardToTab('A', 'c1', () => drawn++);
  api._resolveTabCard('A', 'c1');
  api._renderTabCards('A');
  assert.strictEqual(drawn, 0);
});

test('a card that expired while its tab was hidden is drawn expired', () => {
  const { api, log } = setup('B');
  api._routeCardToTab('A', 'c1', () => {});
  api._expireTabCard('A', 'c1');
  api._renderTabCards('A');
  assert.deepStrictEqual(log.expired, ['c1']);
});

test('when the turn ends, waiting cards are dropped but expired ones stay to be shown once', () => {
  const { ctx, api } = setup('B');
  api._routeCardToTab('A', 'waiting', () => {});
  api._routeCardToTab('A', 'late', () => {});
  api._expireTabCard('A', 'late');
  api._dropStaleTabCards('A');
  assert.deepStrictEqual([...ctx._pendingTabCards.get('A').keys()], ['late']);
});

test('the browser, source and failover cards are routed through the tab and draw into their own tab', () => {
  assert(/_routeCardToTab\(requestTabId, _confirm\.confirm_id/.test(app));
  assert(/_routeCardToTab\(requestTabId, `failover:\$\{_failover\.consent_id\}`/.test(app));
  assert(/_expireTabCard\(requestTabId, msg\.browser_confirm_expired\)/.test(app));
  assert(/_renderTabCards\(tabId\);/.test(app));
  const i = app.indexOf('function _showBrowserConfirmCard');
  const fn = app.slice(i, app.indexOf('/* ── Failover Consent Gate', i));
  assert(/const _tabId = ownerTabId \|\| _activeTabId/.test(fn));
});

test('a permission card from a turn in another tab flags that tab', () => {
  const i = app.indexOf("msg.type === 'permission_required'");
  assert(/_markTabNeedsAttention\(\s*requestTabId/.test(app.slice(i, i + 400)));
});
