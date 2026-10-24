// Sub-project 8: "Edit with Gator" for saved widgets. Pure helpers and handlers are cut
// out of app.js and run in a vm sandbox, the same way tests/chat_xss_render.test.js does.

const assert = require('assert');
const { test } = require('node:test');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function extract(name) {
  const match = source.match(
    new RegExp('\\n(?:async )?function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}'),
  );
  assert(match, name + ' not found in app.js');
  return match[0];
}

function load(names, sandbox) {
  const ctx = vm.createContext(sandbox || {});
  return vm.runInContext(names.map(extract).join('\n') + '\n({' + names.join(',') + '});', ctx);
}

// Objects built inside the vm have a different Object.prototype; compare plain copies.
function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

test('_newTabRecord defaults to a plain New Chat tab', () => {
  const { _newTabRecord } = load(['_newTabRecord']);
  const tab = plain(_newTabRecord('t1'));
  assert.deepStrictEqual(Object.keys(tab).sort(), ['createdAt', 'id', 'title']);
  assert.strictEqual(tab.id, 't1');
  assert.strictEqual(tab.title, 'New Chat');
  assert.strictEqual(typeof tab.createdAt, 'number');
});

test('_newTabRecord ignores a click event passed as opts', () => {
  const { _newTabRecord } = load(['_newTabRecord']);
  const tab = plain(_newTabRecord('t1', { type: 'click', target: {} }));
  assert.strictEqual(tab.title, 'New Chat');
  assert.strictEqual(tab.editingWidget, undefined);
});

test('_newTabRecord carries title and editingWidget', () => {
  const { _newTabRecord } = load(['_newTabRecord']);
  const tab = plain(
    _newTabRecord('t1', {
      title: 'Edit: Local Use',
      editingWidget: { widget_id: 'w1', name: 'Local Use' },
    }),
  );
  assert.strictEqual(tab.title, 'Edit: Local Use');
  assert.deepStrictEqual(tab.editingWidget, { widget_id: 'w1', name: 'Local Use' });
});

test('_newTabRecord drops an editingWidget without a widget_id', () => {
  const { _newTabRecord } = load(['_newTabRecord']);
  const tab = plain(_newTabRecord('t1', { editingWidget: { name: 'x' } }));
  assert.strictEqual(tab.editingWidget, undefined);
});

test('_saveTabs persists editingWidget and omits it for plain tabs', () => {
  const store = {};
  const { _saveTabs } = load(['_saveTabs'], {
    _tabs: [
      { id: 'a', title: 'Edit: X', createdAt: 1, editingWidget: { widget_id: 'w1', name: 'X' } },
      { id: 'b', title: 'New Chat', createdAt: 2 },
    ],
    _activeTabId: 'a',
    TABS_KEY: 'tabs',
    ACTIVE_TAB_KEY: 'active',
    _syncTabsToServer() {},
    localStorage: {
      setItem(key, value) {
        store[key] = value;
      },
    },
  });
  _saveTabs();
  const saved = JSON.parse(store.tabs);
  assert.deepStrictEqual(saved[0].editingWidget, { widget_id: 'w1', name: 'X' });
  assert.ok(!('editingWidget' in saved[1]));
  assert.strictEqual(store.active, 'a');
});

test('_activeEditingWidget reads the active tab record', () => {
  const sandbox = {
    _tabs: [
      { id: 'a', title: 'Edit: X', createdAt: 1, editingWidget: { widget_id: 'w1', name: 'X' } },
      { id: 'b', title: 'New Chat', createdAt: 2 },
    ],
    _activeTabId: 'a',
  };
  const { _activeEditingWidget } = load(['_activeEditingWidget'], sandbox);
  assert.deepStrictEqual(plain(_activeEditingWidget()), { widget_id: 'w1', name: 'X' });
  sandbox._activeTabId = 'b';
  assert.strictEqual(_activeEditingWidget(), null);
  sandbox._activeTabId = 'missing';
  assert.strictEqual(_activeEditingWidget(), null);
});

function createTabSandbox() {
  return {
    _tabs: [],
    _activeTabId: '',
    history: ['old'],
    _saveActiveTabHistory() {},
    _genTabId: () => 'new1',
    _saveTabs() {},
    _renderTabBar() {},
    requestAnimationFrame() {},
    document: { querySelector: () => null },
    _showChatOrOnboarding() {},
    _refreshPinOrb() {},
    _renderPinChip() {},
    _switchPinContext() {},
    _remountCodeAgentTerminalForTab() {},
  };
}

test('createTab applies title and editingWidget from opts', () => {
  const sandbox = createTabSandbox();
  const { createTab } = load(['_newTabRecord', 'createTab'], sandbox);
  createTab({ title: 'Edit: X', editingWidget: { widget_id: 'w1', name: 'X' } });
  assert.strictEqual(sandbox._activeTabId, 'new1');
  assert.strictEqual(sandbox._tabs.length, 1);
  assert.strictEqual(sandbox._tabs[0].title, 'Edit: X');
  assert.deepStrictEqual(plain(sandbox._tabs[0].editingWidget), { widget_id: 'w1', name: 'X' });
});

test('createTab called as a click handler still makes a plain tab', () => {
  const sandbox = createTabSandbox();
  const { createTab } = load(['_newTabRecord', 'createTab'], sandbox);
  createTab({ type: 'click' });
  assert.strictEqual(sandbox._tabs[0].title, 'New Chat');
  assert.strictEqual(sandbox._tabs[0].editingWidget, undefined);
});

const HISTORY_WITH_WIDGETS = [
  { role: 'user', content: 'make a clock' },
  { role: 'assistant', content: 'v1\n```html:widget\n<div>v1</div>\n```' },
  { role: 'user', content: 'bigger' },
  { role: 'assistant', content: 'v2\n```html:widget\n<div>v2</div>\n```\nDone' },
];

test('_latestWidgetHtmlFromHistory returns the newest widget block', () => {
  const { _latestWidgetHtmlFromHistory } = load(['_latestWidgetHtmlFromHistory']);
  assert.strictEqual(_latestWidgetHtmlFromHistory(HISTORY_WITH_WIDGETS), '<div>v2</div>');
});

test('_latestWidgetHtmlFromHistory returns null without a widget block', () => {
  const { _latestWidgetHtmlFromHistory } = load(['_latestWidgetHtmlFromHistory']);
  assert.strictEqual(_latestWidgetHtmlFromHistory([]), null);
  assert.strictEqual(
    _latestWidgetHtmlFromHistory([{ role: 'assistant', content: 'plain text' }]),
    null,
  );
});

test('_latestWidgetHtmlFromHistory ignores user messages and non-string content', () => {
  const { _latestWidgetHtmlFromHistory } = load(['_latestWidgetHtmlFromHistory']);
  const hist = [
    { role: 'user', content: '```html:widget\n<div>mine</div>\n```' },
    { role: 'assistant', content: [{ type: 'text', text: '```html:widget\n<p>x</p>\n```' }] },
  ];
  assert.strictEqual(_latestWidgetHtmlFromHistory(hist), null);
});

test('_buildWidgetEditSuffix names the widget and demands the complete widget back', () => {
  const { _buildWidgetEditSuffix } = load(['_buildWidgetEditSuffix']);
  const suffix = _buildWidgetEditSuffix('Local Use', '<div>hi</div>');
  assert.ok(suffix.includes('"Local Use"'));
  assert.ok(suffix.includes('<div>hi</div>'));
  assert.ok(suffix.includes('COMPLETE'));
  assert.ok(suffix.includes('html:widget'));
  assert.ok(suffix.includes('data'));
});

function suffixSandbox({ editing = true, fetchImpl } = {}) {
  const calls = [];
  const sandbox = {
    _tabs: [
      {
        id: 'a',
        title: 'Edit: Local Use',
        createdAt: 1,
        ...(editing ? { editingWidget: { widget_id: 'w1', name: 'Local Use' } } : {}),
      },
    ],
    fetch: async (url) => {
      calls.push(url);
      return fetchImpl ? fetchImpl(url) : { ok: false };
    },
  };
  const fns = load(
    ['_latestWidgetHtmlFromHistory', '_buildWidgetEditSuffix', '_widgetEditSuffixFor'],
    sandbox,
  );
  return { fns, calls };
}

test('_widgetEditSuffixFor returns null for a tab that is not editing', async () => {
  const { fns, calls } = suffixSandbox({ editing: false });
  assert.strictEqual(await fns._widgetEditSuffixFor('a', HISTORY_WITH_WIDGETS), null);
  assert.deepStrictEqual(calls, []);
});

test('_widgetEditSuffixFor prefers the newest widget in history over the saved copy', async () => {
  const { fns, calls } = suffixSandbox();
  const suffix = await fns._widgetEditSuffixFor('a', HISTORY_WITH_WIDGETS);
  assert.ok(suffix.includes('<div>v2</div>'));
  assert.deepStrictEqual(calls, []);
});

test('_widgetEditSuffixFor falls back to the saved widget', async () => {
  const { fns, calls } = suffixSandbox({
    fetchImpl: () => ({ ok: true, json: async () => ({ html: '<div>saved</div>' }) }),
  });
  const suffix = await fns._widgetEditSuffixFor('a', [{ role: 'user', content: 'hi' }]);
  assert.ok(suffix.includes('<div>saved</div>'));
  assert.deepStrictEqual(calls, ['/api/widgets/w1']);
});

test('_widgetEditSuffixFor returns null when the saved widget cannot be loaded', async () => {
  const notOk = suffixSandbox({ fetchImpl: () => ({ ok: false }) });
  assert.strictEqual(await notOk.fns._widgetEditSuffixFor('a', []), null);
  const failing = suffixSandbox({
    fetchImpl: () => {
      throw new Error('network');
    },
  });
  assert.strictEqual(await failing.fns._widgetEditSuffixFor('a', []), null);
});

test('doSend passes the editing-tab suffix as system_prompt_suffix', () => {
  assert.ok(
    /const _wSuffix =\s*window\._pendingWidgetSuffix \|\|\s*\(await _widgetEditSuffixFor\(requestContextId, requestHistory\)\) \|\|\s*null;/.test(
      source,
    ),
    'doSend must build _wSuffix from _widgetEditSuffixFor',
  );
});

function actionNames() {
  const match = source.match(/const GATOR_ACTIONS = new Set\(\[([\s\S]*?)\]\);/);
  assert(match, 'GATOR_ACTIONS not found in app.js');
  return [...match[1].matchAll(/'([^']+)'/g)].map((m) => m[1]);
}

test('GATOR_ACTIONS allows the Edit action', () => {
  assert.ok(actionNames().includes('gatorWidgetEditWithGator'));
});

test('the manager row renders the Edit button through gatorActionAttrs', () => {
  assert.ok(
    source.includes("gatorActionAttrs('gatorWidgetEditWithGator', [w.widget_id, w.name])"),
    'manager row must render the pencil button',
  );
});

function editSandbox(tabs) {
  const calls = { created: [], switched: [], closed: 0, range: [] };
  const input = {
    textContent: '',
    focused: false,
    events: [],
    dispatchEvent(e) {
      this.events.push(e.type);
    },
    focus() {
      this.focused = true;
    },
  };
  const sandbox = {
    _tabs: tabs || [],
    _activeTabId: 'x',
    Event: class {
      constructor(type) {
        this.type = type;
      }
    },
    gatorCloseWidgetManager() {
      calls.closed++;
    },
    createTab(opts) {
      calls.created.push(opts);
    },
    switchTab(id) {
      calls.switched.push(id);
    },
    document: {
      getElementById: (id) => (id === 'chat-input' ? input : null),
      createRange: () => ({
        selectNodeContents() {},
        collapse(toStart) {
          calls.range.push(['collapse', toStart]);
        },
      }),
    },
    window: {
      getSelection: () => ({
        removeAllRanges() {},
        addRange() {
          calls.range.push(['add']);
        },
      }),
    },
  };
  return { sandbox, input, calls };
}

test('gatorWidgetEditWithGator opens an editing tab and prefills the input', () => {
  const { sandbox, input, calls } = editSandbox();
  const { gatorWidgetEditWithGator } = load(['gatorWidgetEditWithGator'], sandbox);
  gatorWidgetEditWithGator('w1', 'Local Use');
  assert.strictEqual(calls.closed, 1);
  assert.deepStrictEqual(plain(calls.created), [
    { title: 'Edit: Local Use', editingWidget: { widget_id: 'w1', name: 'Local Use' } },
  ]);
  assert.strictEqual(input.textContent, 'Edit my "Local Use" widget: ');
  assert.deepStrictEqual(input.events, ['input']);
  assert.strictEqual(input.focused, true);
  assert.deepStrictEqual(calls.range, [['collapse', false], ['add']]);
});

test('gatorWidgetEditWithGator cuts long names in the tab title only', () => {
  const { sandbox, input, calls } = editSandbox();
  const { gatorWidgetEditWithGator } = load(['gatorWidgetEditWithGator'], sandbox);
  const name = 'A'.repeat(40);
  gatorWidgetEditWithGator('w1', name);
  assert.strictEqual(calls.created[0].title, 'Edit: ' + 'A'.repeat(23) + '…');
  assert.strictEqual(calls.created[0].editingWidget.name, name);
  assert.strictEqual(input.textContent, 'Edit my "' + name + '" widget: ');
});

test('gatorWidgetEditWithGator switches to a tab already editing that widget', () => {
  const { sandbox, calls } = editSandbox([
    { id: 't9', title: 'Edit: X', createdAt: 1, editingWidget: { widget_id: 'w1', name: 'X' } },
  ]);
  const { gatorWidgetEditWithGator } = load(['gatorWidgetEditWithGator'], sandbox);
  gatorWidgetEditWithGator('w1', 'X');
  assert.deepStrictEqual(calls.switched, ['t9']);
  assert.deepStrictEqual(calls.created, []);
});

test('gatorWidgetEditWithGator keeps an existing draft', () => {
  const { sandbox, input } = editSandbox();
  input.textContent = 'half-written message';
  const { gatorWidgetEditWithGator } = load(['gatorWidgetEditWithGator'], sandbox);
  gatorWidgetEditWithGator('w1', 'X');
  assert.strictEqual(input.textContent, 'half-written message');
});

const WIDGET_FENCE = '```html:widget\n<div>hi</div>\n```';

function renderSandbox(editingName) {
  return {
    GATOR_WIDGET_MAX_H: 3000,
    GATOR_WIDGET_STORE_PREFIX: 'gator.widgetstore.',
    localStorage: { getItem: () => null },
    window: { location: { origin: 'http://127.0.0.1:8000' } },
    _tabs: [
      {
        id: 'a',
        title: 'Tab',
        createdAt: 1,
        ...(editingName ? { editingWidget: { widget_id: 'w1', name: editingName } } : {}),
      },
    ],
    _activeTabId: 'a',
  };
}

const RENDER_FUNCTIONS = [
  'escapeHtml',
  'applyInline',
  'gatorWidgetCspHtml',
  'gatorWidgetFrameScript',
  'gatorWidgetStoreKey',
  'gatorWidgetStoreLoad',
  'gatorWidgetStorageScript',
  'gatorActionAttrs',
  '_activeEditingWidget',
  'renderMarkdown',
];

test('GATOR_ACTIONS allows the Update action', () => {
  assert.ok(actionNames().includes('gatorWidgetUpdateConfirm'));
});

test('no Update button outside an editing tab', () => {
  const { renderMarkdown } = load(RENDER_FUNCTIONS, renderSandbox(null));
  const out = renderMarkdown(WIDGET_FENCE);
  assert.ok(out.includes('-save-btn'));
  assert.ok(!out.includes('-update-btn'));
});

test('editing tab shows one primary Save changes button and a quieter Save as new widget', () => {
  const { renderMarkdown } = load(RENDER_FUNCTIONS, renderSandbox('Local Use'));
  const out = renderMarkdown(WIDGET_FENCE);
  assert.ok(out.includes('-update-btn'));
  assert.ok(out.includes('data-call="gatorWidgetUpdateConfirm"'));
  assert.ok(out.includes('Save changes to &quot;Local Use&quot;'));
  assert.ok(out.includes('-save-btn'));
  assert.ok(out.includes('Save as new widget'));
  assert.ok(out.includes('data-call="gatorWidgetSavePrompt"'));
  assert.ok(out.includes('gator-widget-btn-secondary'));
  assert.ok(!/>[^<]*&#128190; Save</.test(out), 'plain Save label is gone in editing tabs');
});

test('editing tab label says the changes are unsaved', () => {
  const { renderMarkdown } = load(RENDER_FUNCTIONS, renderSandbox('Local Use'));
  const out = renderMarkdown(WIDGET_FENCE);
  assert.ok(/-label">Unsaved changes to &quot;Local Use&quot;</.test(out));
});

test('plain tabs keep the Widget label and the Save button', () => {
  const { renderMarkdown } = load(RENDER_FUNCTIONS, renderSandbox(null));
  const out = renderMarkdown(WIDGET_FENCE);
  assert.ok(/-label">Widget</.test(out));
  assert.ok(out.includes('&#128190; Save'));
  assert.ok(!out.includes('Save as new widget'));
  assert.ok(!out.includes('gator-widget-btn-secondary'));
});

test('Update button name is escaped and cut to 20 characters', () => {
  const escaped = load(RENDER_FUNCTIONS, renderSandbox('A<b>')).renderMarkdown(WIDGET_FENCE);
  assert.ok(!escaped.includes('<b>'));
  assert.ok(escaped.includes('A&lt;b&gt;'));
  const long = load(RENDER_FUNCTIONS, renderSandbox('B'.repeat(30))).renderMarkdown(WIDGET_FENCE);
  assert.ok(long.includes('B'.repeat(19) + '…'));
  assert.ok(!long.includes('B'.repeat(20)));
});

test('transient no-save widgets get no Update button', () => {
  const { renderMarkdown } = load(RENDER_FUNCTIONS, renderSandbox('Local Use'));
  const out = renderMarkdown('```html:widget\n<div data-no-save>x</div>\n```');
  assert.ok(!out.includes('-save-btn'));
  assert.ok(!out.includes('-update-btn'));
});

function updateSandbox({ editing = true, status = 200, reject = false } = {}) {
  const btn = { textContent: '', disabled: false };
  const label = { textContent: 'Unsaved changes to "Local Use"' };
  const calls = { fetch: [], dock: 0, manager: 0 };
  const panel = { classList: { contains: (c) => c === 'is-open' } };
  const sandbox = {
    _tabs: [
      {
        id: 'a',
        title: 'Edit: Local Use',
        createdAt: 1,
        ...(editing ? { editingWidget: { widget_id: 'w1', name: 'Local Use' } } : {}),
      },
    ],
    _activeTabId: 'a',
    gatorWidgetHtmlFromId: (id) => (id === 'frame1' ? '<div>v2</div>' : null),
    gatorWidgetRenderDock() {
      calls.dock++;
    },
    gatorWidgetManagerRender() {
      calls.manager++;
    },
    document: {
      getElementById: (id) =>
        id === 'frame1-update-btn'
          ? btn
          : id === 'frame1-label'
            ? label
            : id === 'gator-widget-manager'
              ? panel
              : null,
    },
    fetch: async (url, init) => {
      calls.fetch.push({ url, init });
      if (reject) throw new Error('network');
      return { ok: status >= 200 && status < 300, status };
    },
  };
  return { sandbox, btn, label, calls };
}

test('gatorWidgetUpdateConfirm PATCHes only the html of the edited widget', async () => {
  const { sandbox, btn, label, calls } = updateSandbox();
  const { gatorWidgetUpdateConfirm } = load(
    ['_activeEditingWidget', 'gatorWidgetUpdateConfirm'],
    sandbox,
  );
  await gatorWidgetUpdateConfirm('frame1');
  assert.strictEqual(calls.fetch.length, 1);
  assert.strictEqual(calls.fetch[0].url, '/api/widgets/w1');
  assert.strictEqual(calls.fetch[0].init.method, 'PATCH');
  assert.deepStrictEqual(JSON.parse(calls.fetch[0].init.body), { html: '<div>v2</div>' });
  assert.strictEqual(btn.textContent, '✓ Saved');
  assert.strictEqual(label.textContent, 'Saved to "Local Use"');
  assert.strictEqual(btn.disabled, true);
  assert.strictEqual(calls.dock, 1);
  assert.strictEqual(calls.manager, 1);
});

test('gatorWidgetUpdateConfirm reports a deleted widget', async () => {
  const { sandbox, btn, label, calls } = updateSandbox({ status: 404 });
  const { gatorWidgetUpdateConfirm } = load(
    ['_activeEditingWidget', 'gatorWidgetUpdateConfirm'],
    sandbox,
  );
  await gatorWidgetUpdateConfirm('frame1');
  assert.strictEqual(btn.textContent, 'Widget was deleted — use Save as new widget');
  assert.strictEqual(label.textContent, 'Unsaved changes to "Local Use"');
  assert.strictEqual(btn.disabled, true);
  assert.strictEqual(calls.dock, 0);
});

test('gatorWidgetUpdateConfirm lets the user retry after a failure', async () => {
  for (const options of [{ reject: true }, { status: 500 }]) {
    const { sandbox, btn, label, calls } = updateSandbox(options);
    const { gatorWidgetUpdateConfirm } = load(
      ['_activeEditingWidget', 'gatorWidgetUpdateConfirm'],
      sandbox,
    );
    await gatorWidgetUpdateConfirm('frame1');
    assert.strictEqual(btn.textContent, 'Save failed — retry');
    assert.strictEqual(label.textContent, 'Unsaved changes to "Local Use"');
    assert.strictEqual(btn.disabled, false);
    assert.strictEqual(calls.dock, 0);
  }
});

test('gatorWidgetUpdateConfirm does nothing outside an editing tab', async () => {
  const { sandbox, calls } = updateSandbox({ editing: false });
  const { gatorWidgetUpdateConfirm } = load(
    ['_activeEditingWidget', 'gatorWidgetUpdateConfirm'],
    sandbox,
  );
  await gatorWidgetUpdateConfirm('frame1');
  assert.deepStrictEqual(calls.fetch, []);
});

test('the My Widgets dock icon has no total-count badge', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'index.html'), 'utf8');
  const css = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'style.css'), 'utf8');
  for (const text of [source, html, css]) assert.ok(!text.includes('dock-widgets-badge'));
});

test('_buildWidgetEditSuffix forbids claiming a change without the widget block', () => {
  const { _buildWidgetEditSuffix } = load(['_buildWidgetEditSuffix']);
  const suffix = _buildWidgetEditSuffix('Local Use', '<div>hi</div>');
  assert.ok(suffix.includes('MUST contain the complete'));
  assert.ok(/never say .*(changed|fixed|applied)/i.test(suffix));
  assert.ok(/cannot|can't/i.test(suffix));
});

test('_widgetEditReplyNeedsNotice flags editing-tab replies without a widget block', () => {
  const { _widgetEditReplyNeedsNotice } = load(['_widgetEditReplyNeedsNotice']);
  const editing = { id: 'a', editingWidget: { widget_id: 'w1', name: 'X' } };
  assert.strictEqual(_widgetEditReplyNeedsNotice(editing, 'I fixed the layout.'), true);
  assert.strictEqual(_widgetEditReplyNeedsNotice(editing, ''), true);
  assert.strictEqual(
    _widgetEditReplyNeedsNotice(editing, 'Here:\n```html:widget\n<p>x</p>\n```'),
    false,
  );
  assert.strictEqual(_widgetEditReplyNeedsNotice(editing, '```html:live\n<p>x</p>\n```'), false);
  assert.strictEqual(_widgetEditReplyNeedsNotice(editing, '```html\n<p>x</p>\n```'), true);
});

test('_widgetEditReplyNeedsNotice stays quiet outside editing tabs', () => {
  const { _widgetEditReplyNeedsNotice } = load(['_widgetEditReplyNeedsNotice']);
  assert.strictEqual(_widgetEditReplyNeedsNotice({ id: 'a' }, 'no widget here'), false);
  assert.strictEqual(_widgetEditReplyNeedsNotice(undefined, 'no widget here'), false);
});

test('the stream-finalize path shows the notice through the helper', () => {
  assert.ok(
    /_widgetEditReplyNeedsNotice\(\s*_tabs\.find\(\(t\) => t\.id === _tabKey\),\s*full,?\s*\)/.test(
      source,
    ),
  );
  assert.ok(source.includes('widget-edit-notice'));
});
