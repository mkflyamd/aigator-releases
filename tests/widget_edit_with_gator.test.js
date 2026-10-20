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
