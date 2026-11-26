const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { test } = require('node:test');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'marketplace-pane.js'),
  'utf8',
);

test('Mine skill rows offer Share and the file download stays available', () => {
  assert(source.includes("shareBtn.dataset.action = 'share-mine'"));
  assert(source.includes("action === 'share-mine'"));
  const start = source.indexOf('async function _downloadMineSkill(');
  assert(start > 0, 'download handler exists');
  const body = source.slice(start, source.indexOf('async function _editMineSkill(', start));
  assert(body.includes("'/api/marketplace/export/'"));
  assert(body.includes("a.download = skillId + '.skill'"));
});

test('Share opens the Share modal and hands it the download as a fallback', () => {
  const start = source.indexOf('function _shareMineSkill(');
  assert(start > 0, 'share handler exists');
  const body = source.slice(start, source.indexOf('async function _downloadMineSkill(', start));
  assert(body.includes('window.SkillSharing.openShareModal(skillId'));
  assert(body.includes('postJson: _postJson'));
  assert(body.includes('getJson: _getJson'));
  assert(body.includes('downloadSkill: _downloadMineSkill'));
  assert(body.includes('showAlert: _showAlert'));
  assert(body.includes('refresh'));
  assert(
    body.includes('return _downloadMineSkill(skillId)'),
    'falls back when the module is missing',
  );
});

test('Mine rows show a Shared chip only for a positive published_version', () => {
  assert(source.includes('Share with colleagues through OneDrive, or download a file'));
  const chip = extractFn('_sharedChip', fakeDocument());
  assert.strictEqual(chip({ tier: 'Mine', id: 'a' }), null);
  assert.strictEqual(chip({ tier: 'Mine', id: 'a', published_version: 0 }), null);
  assert.strictEqual(chip({ tier: 'Community', id: 'a', published_version: 2 }), null);
  const shown = chip({ tier: 'Mine', id: 'a', published_version: 2 });
  assert.strictEqual(shown.tag, 'span');
  assert.strictEqual(shown.textContent, 'Shared · v2');
});

test('the Share modal script loads before the marketplace pane', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'index.html'), 'utf8');
  const share = html.indexOf('/static/skill-sharing.js');
  const pane = html.indexOf('/static/marketplace-pane.js');
  assert(share > 0 && share < pane);
});

test('Share is only added inside the Mine branch of the installed list', () => {
  const at = source.indexOf("shareBtn.dataset.action = 'share-mine'");
  const branch = source.lastIndexOf("if (skill.tier === 'Mine') {", at);
  const removeBtn = source.indexOf('const removeBtn', branch);
  assert(branch > 0 && at < removeBtn, 'share button sits in the tier === Mine block');
});

test('Share reuses the people search endpoint and reports a send in a toast', () => {
  const start = source.indexOf('function _shareMineSkill(');
  const body = source.slice(start, source.indexOf('async function _downloadMineSkill(', start));
  assert(body.includes('searchPeople: _searchPeople'));
  assert(body.includes('showToast: window._showConnectivityToast'));
  assert(!/slack|channel/i.test(body), 'the share modal is email only');
  const search = source.indexOf('async function _searchPeople(query, signal)');
  assert(search > 0, 'people search takes a query and an abort signal');
  const fn = source.slice(search, source.indexOf('async function _downloadMineSkill(', search));
  assert(fn.includes("'/api/people/search?q='"));
  assert(fn.includes('org_only=true'));
  assert(fn.includes('{ signal }'));
  assert(
    /if \(!resp\.ok\) throw new Error\(/.test(fn),
    'a failed search throws so it is not cached as empty',
  );
  assert(!/slack|channel/i.test(fn));
});

test('Share gets a JSON GET helper that returns the response and the parsed body', () => {
  const start = source.indexOf('async function _getJson(url)');
  assert(start > 0, 'getJson helper exists');
  const fn = source.slice(start, source.indexOf('async function _searchPeople(', start));
  assert(fn.includes('await fetch(url)'));
  assert(fn.includes('resp.json()'));
  assert(fn.includes('return { resp, body }'));
});

test('the Share link field keeps only the link when the whole message is pasted', () => {
  const at = source.indexOf("shareInput.addEventListener('paste'");
  assert(at > 0, 'paste handler exists');
  const handler = source.slice(at, source.indexOf('shareRow.appendChild(shareInput)', at));
  assert(handler.includes("getData('text')"));
  assert(handler.includes('sharing.extractLink(pasted)'));
  assert(handler.includes('if (!link) return;'), 'text without a link is pasted as typed');
  assert(handler.includes('e.preventDefault()'));
  assert(handler.includes('shareInput.value = link'));
});

// ── updates for received skills and the edited-since chip ────────────────

const vm = require('vm');

function fnSource(name) {
  const re = new RegExp('(?:async\\s+)?function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n  \\}');
  const match = source.match(re);
  assert(match, name + ' not found in marketplace-pane.js');
  return match[0];
}

class FakeEl {
  constructor(tag) {
    this.tag = tag;
    this.dataset = {};
    this.className = '';
    this.title = '';
    this.disabled = false;
    this.isConnected = true;
    this.children = [];
    this.focusCalls = [];
    this._text = '';
  }
  get textContent() {
    return this.children.length ? this.children.map((c) => c.textContent).join('') : this._text;
  }
  set textContent(value) {
    this.children = [];
    this._text = String(value);
  }
  appendChild(child) {
    this.children.push(child);
    return child;
  }
  focus(options) {
    this.focusCalls.push(options);
  }
}

function fakeDocument() {
  return { document: { createElement: (tag) => new FakeEl(tag) } };
}

function extractFn(name, ctx) {
  const context = vm.createContext(ctx || {});
  return vm.runInContext(fnSource(name) + ';' + name + ';', context);
}

// Several functions of the pane in one context, so they call each other as in the page.
function extractFns(names, ctx) {
  const context = vm.createContext(ctx || {});
  names.forEach((name) => vm.runInContext(fnSource(name) + ';', context));
  return context;
}

test('the row note says "vN available", "Up to date", removed, or no access', () => {
  const note = extractFn('_updateNote');
  assert.strictEqual(note({ status: 'update', latest: 3 }), 'v3 available');
  assert.strictEqual(note({ status: 'current' }), 'Up to date');
  assert.strictEqual(note({ status: 'removed' }), 'The author removed this shared skill');
  assert.strictEqual(note({ status: 'no_access' }), 'You no longer have access');
  assert.strictEqual(note({ status: 'nonsense' }), '');
});

test('Check for update reads the update-check route and stores the answer without touching the install', async () => {
  const urls = [];
  const alerts = [];
  let renders = 0;
  const _updateStatus = {};
  const answer = { status: 'update', installed: 1, latest: 2, link: 'aigator://share?d=x' };
  const run = extractFn('_checkSharedUpdate', {
    _updateStatus,
    _getJson: async (url) => {
      urls.push(url);
      return { resp: { ok: true }, body: answer };
    },
    _showAlert: (msg, kind) => alerts.push({ msg, kind }),
    _errorMessage: () => 'x',
    _render: () => {
      renders += 1;
    },
    encodeURIComponent,
  });
  await run('weekly-report');
  assert.deepStrictEqual(urls, ['/api/skills/share/update-check?skill_id=weekly-report']);
  assert.strictEqual(_updateStatus['weekly-report'], answer);
  assert.strictEqual(renders, 0, 'the caller re-renders once the button is released');
  assert.strictEqual(alerts.length, 0);
});

test('a failed check shows an alert and records nothing', async () => {
  const alerts = [];
  const _updateStatus = {};
  const run = extractFn('_checkSharedUpdate', {
    _updateStatus,
    _getJson: async () => ({ resp: { ok: false }, body: { detail: { message: 'nope' } } }),
    _showAlert: (msg, kind) => alerts.push({ msg, kind }),
    _errorMessage: (body) => body.detail.message,
    _render: () => assert.fail('no re-render on failure'),
    encodeURIComponent,
  });
  await run('weekly-report');
  assert.deepStrictEqual(Object.keys(_updateStatus), []);
  assert.strictEqual(alerts.length, 1);
  assert.strictEqual(alerts[0].kind, 'error');
});

test('received rows get Check for update, which becomes Update once a newer version is known', () => {
  const button = extractFns(['_updateButton', '_paintUpdateButton'], {
    document: fakeDocument().document,
    _updateBusy: new Set(),
  })._updateButton;
  const skill = { id: 'weekly-report' };
  assert.strictEqual(button(false, skill, null), null);
  const check = button(true, skill, null);
  assert.strictEqual(check.textContent, 'Check for update');
  assert.strictEqual(check.dataset.action, 'check-update');
  assert.strictEqual(check.dataset.skillId, 'weekly-report');
  assert.strictEqual(button(true, skill, { status: 'current' }).dataset.action, 'check-update');
  const update = button(true, skill, { status: 'update', latest: 2 });
  assert.strictEqual(update.textContent, 'Update');
  assert.strictEqual(update.dataset.action, 'apply-update');
  assert(
    source.includes(
      "skill.tier === 'Community' && !!(skill.share_source && skill.share_source.folder_id)",
    ),
  );
});

function updateContext(overrides) {
  return extractFns(
    ['_updateButton', '_paintUpdateButton', '_startUpdateAction', '_rowButtonKey'],
    Object.assign(
      {
        document: fakeDocument().document,
        _updateBusy: new Set(),
        _updateStatus: {},
        _pendingFocusKey: null,
        _showAlert: () => {},
      },
      overrides,
    ),
  );
}

function deferred() {
  let resolve;
  const promise = new Promise((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

test('a busy update button is disabled and shows the spinner with Checking… or Opening…', () => {
  const ctx = updateContext();
  const skill = { id: 'weekly-report' };
  const idle = ctx._updateButton(true, skill, null);
  assert.strictEqual(idle.disabled, false);
  assert.strictEqual(idle.textContent, 'Check for update');
  assert.strictEqual(idle.children.length, 0);

  ctx._updateBusy.add('weekly-report');
  const checking = ctx._updateButton(true, skill, { status: 'current' });
  assert.strictEqual(checking.disabled, true);
  assert.strictEqual(checking.textContent, 'Checking…');
  assert(checking.children.some((c) => c.className === 'cap-inline-spinner'));
  assert(checking.className.includes('mp-row-btn-busy'));
  assert.strictEqual(checking.dataset.action, 'check-update');

  const opening = ctx._updateButton(true, skill, { status: 'update', latest: 2 });
  assert.strictEqual(opening.disabled, true);
  assert.strictEqual(opening.textContent, 'Opening…');
  assert(opening.children.some((c) => c.className === 'cap-inline-spinner'));
  assert.strictEqual(opening.dataset.action, 'apply-update');
});

test('Check for update shows the spinner while in flight, ignores repeat clicks, and restores after', async () => {
  const gate = deferred();
  let checks = 0;
  let renders = 0;
  const ctx = updateContext({
    _checkSharedUpdate: async () => {
      checks += 1;
      await gate.promise;
    },
  });
  ctx._render = () => {
    renders += 1;
  };
  const btn = ctx._updateButton(true, { id: 'a' }, null);
  const first = ctx._startUpdateAction(btn, 'check-update');
  assert.strictEqual(btn.disabled, true);
  assert.strictEqual(btn.textContent, 'Checking…');
  assert(btn.children.some((c) => c.className === 'cap-inline-spinner'));
  assert(ctx._updateBusy.has('a'));

  await ctx._startUpdateAction(btn, 'check-update');
  assert.strictEqual(checks, 1, 'a repeat click does not start a second check');

  // A re-render while the request runs must still draw the busy button.
  const rebuilt = ctx._updateButton(true, { id: 'a' }, null);
  assert.strictEqual(rebuilt.disabled, true);
  assert.strictEqual(rebuilt.textContent, 'Checking…');

  gate.resolve();
  await first;
  assert.strictEqual(ctx._updateBusy.size, 0);
  assert.strictEqual(renders, 1);
  const after = ctx._updateButton(true, { id: 'a' }, null);
  assert.strictEqual(after.disabled, false);
  assert.strictEqual(after.textContent, 'Check for update');
  assert.strictEqual(ctx._pendingFocusKey, null, 'the focus request does not outlive the check');
});

test('the button is restored when the check fails', async () => {
  const alerts = [];
  let renders = 0;
  const ctx = updateContext({
    _checkSharedUpdate: async () => {
      throw new Error('offline');
    },
    _showAlert: (msg, kind) => alerts.push({ msg, kind }),
  });
  ctx._render = () => {
    renders += 1;
  };
  const btn = ctx._updateButton(true, { id: 'a' }, null);
  await ctx._startUpdateAction(btn, 'check-update');
  assert.strictEqual(ctx._updateBusy.size, 0);
  assert.strictEqual(renders, 1, 'the list is drawn again with the idle button');
  assert.strictEqual(alerts.length, 1);
  assert.strictEqual(alerts[0].kind, 'error');
  assert.strictEqual(ctx._updateButton(true, { id: 'a' }, null).disabled, false);
});

test('Update shows Opening…, ignores repeat clicks, and opens the review with the checked link', async () => {
  const gate = deferred();
  const links = [];
  let renders = 0;
  const ctx = updateContext({
    _reviewSharedLink: async (link) => {
      links.push(link);
      await gate.promise;
    },
  });
  ctx._render = () => {
    renders += 1;
  };
  ctx._updateStatus.a = { status: 'update', latest: 2, link: 'aigator://share?d=x' };
  const btn = ctx._updateButton(true, { id: 'a' }, ctx._updateStatus.a);
  const first = ctx._startUpdateAction(btn, 'apply-update');
  assert.strictEqual(btn.disabled, true);
  assert.strictEqual(btn.textContent, 'Opening…');
  await ctx._startUpdateAction(btn, 'apply-update');
  assert.deepStrictEqual(links, ['aigator://share?d=x']);

  gate.resolve();
  await first;
  // The review dialog is open on top of the list: the same button is put back, no re-render.
  assert.strictEqual(renders, 0);
  assert.strictEqual(btn.disabled, false);
  assert.strictEqual(btn.textContent, 'Update');
  assert.strictEqual(ctx._updateBusy.size, 0);
});

test('Update restores the button when the review cannot open', async () => {
  const alerts = [];
  const ctx = updateContext({
    _reviewSharedLink: async () => {
      throw new Error('boom');
    },
    _showAlert: (msg, kind) => alerts.push({ msg, kind }),
  });
  ctx._updateStatus.a = { status: 'update', latest: 2, link: 'aigator://share?d=x' };
  const btn = ctx._updateButton(true, { id: 'a' }, ctx._updateStatus.a);
  await ctx._startUpdateAction(btn, 'apply-update');
  assert.strictEqual(btn.disabled, false);
  assert.strictEqual(btn.textContent, 'Update');
  assert.strictEqual(ctx._updateBusy.size, 0);
  assert.strictEqual(alerts.length, 1);
  assert.strictEqual(alerts[0].kind, 'error');
});

test('Update on a button the list already replaced redraws the list instead', async () => {
  let renders = 0;
  const ctx = updateContext({ _reviewSharedLink: async () => {} });
  ctx._render = () => {
    renders += 1;
  };
  ctx._updateStatus.a = { status: 'update', latest: 2, link: 'aigator://share?d=x' };
  const btn = ctx._updateButton(true, { id: 'a' }, ctx._updateStatus.a);
  btn.isConnected = false;
  await ctx._startUpdateAction(btn, 'apply-update');
  assert.strictEqual(renders, 1);
});

test('the delegated click handler sends both update buttons to the guarded action', () => {
  const calls = [];
  const handler = extractFn('_handleContentClick', {
    _startUpdateAction: (btn, action) => calls.push([btn.dataset.skillId, action]),
  });
  ['check-update', 'apply-update'].forEach((action) => {
    const btn = { dataset: { action, skillId: 'a' } };
    handler({ target: { closest: () => btn } });
  });
  assert.deepStrictEqual(calls, [
    ['a', 'check-update'],
    ['a', 'apply-update'],
  ]);
});

function installedContext(activeTab) {
  const calls = { render: 0, switched: [] };
  const deps = {};
  const ctx = extractFns(['_reviewSharedLink', '_updateNote', '_rowButtonKey'], {
    window: {
      SkillSharing: {
        extractLink: (text) => text,
        openLinkReview: (link, d) => Object.assign(deps, d),
      },
    },
    _updateStatus: { a: { status: 'update', latest: 2, link: 'aigator://share?d=x' } },
    _activeTab: activeTab,
    _pendingFocusKey: null,
    _postJson: async () => ({}),
    _showAlert: () => {},
    _errorMessage: () => '',
    _appendPermissionList: () => {},
    _handleInstallOutcome: () => {},
    _render: () => {
      calls.render += 1;
    },
    _switchTab: (tab) => calls.switched.push(tab),
  });
  ctx._reviewSharedLink('aigator://share?d=x');
  return { ctx, deps, calls };
}

test('after an update installs, the row keeps an "Up to date" status at the new version', () => {
  const { ctx, deps, calls } = installedContext('installed');
  deps.onInstalled({ skill_id: 'a', version: 2 }, { title: 'Weekly report' });
  assert.deepStrictEqual(Object.assign({}, ctx._updateStatus.a), {
    status: 'current',
    installed: 2,
  });
  assert.strictEqual(ctx._updateNote(ctx._updateStatus.a), 'Up to date');
  assert.strictEqual(calls.render, 1, 'the open Installed list is redrawn in place');
  assert.deepStrictEqual(calls.switched, []);
  assert.strictEqual(ctx._pendingFocusKey, 'a|update', 'focus returns to the row button');
});

test('a link installed from the Add tab still switches to Installed', () => {
  const { ctx, deps, calls } = installedContext('add');
  deps.onInstalled({ skill_id: 'a', version: 1 }, { title: 'Weekly report' });
  assert.deepStrictEqual(calls.switched, ['installed']);
  assert.strictEqual(calls.render, 0);
  assert.strictEqual(ctx._pendingFocusKey, null, 'no focus is taken from the Add form');
  assert.strictEqual(ctx._updateNote(ctx._updateStatus.a), 'Up to date');
});

// A fake #mp-content that behaves like the browser: emptying it collapses the scroll position.
function fakeContent(initialScroll) {
  return {
    children: [],
    scrollTop: initialScroll,
    get firstChild() {
      return this.children[0] || null;
    },
    removeChild(child) {
      this.children.splice(this.children.indexOf(child), 1);
      if (!this.children.length) this.scrollTop = 0;
    },
    contains(el) {
      return this.children.includes(el);
    },
    querySelectorAll() {
      return this.children;
    },
  };
}

function rowButton(id, action, disabled) {
  const btn = new FakeEl('button');
  btn.dataset.action = action;
  btn.dataset.skillId = id;
  btn.disabled = !!disabled;
  return btn;
}

function renderContext(content, active, overrides) {
  const doc = { body: { tag: 'body' }, getElementById: () => content };
  doc.activeElement = active || doc.body;
  const ctx = extractFns(
    ['_render', '_rowButtonKey', '_findRowButton'],
    Object.assign(
      {
        document: doc,
        _activeTab: 'installed',
        _pendingFocusKey: null,
        _renderBrowse: () => {},
        _renderAdd: () => {},
        _renderInstalled: (c) => {
          ['disable', 'check-update', 'remove'].forEach((action) => {
            ['a', 'b'].forEach((id) => c.children.push(rowButton(id, action)));
          });
        },
      },
      overrides,
    ),
  );
  return ctx;
}

test('a re-render keeps the Installed list scroll position and the focused row button', () => {
  const content = fakeContent(480);
  const old = rowButton('b', 'apply-update');
  content.children.push(old);
  const ctx = renderContext(content, old);
  ctx._render();
  assert.strictEqual(content.scrollTop, 480);
  const focused = content.children.filter((c) => c.focusCalls.length > 0);
  assert.strictEqual(focused.length, 1, 'exactly one button is focused');
  assert.strictEqual(focused[0].dataset.skillId, 'b');
  assert.strictEqual(focused[0].dataset.action, 'check-update');
  assert.strictEqual(focused[0].focusCalls.length, 1);
  assert.strictEqual(focused[0].focusCalls[0].preventScroll, true);
});

test('a tab switch or new search starts at the top and takes no focus', () => {
  const content = fakeContent(480);
  const old = rowButton('a', 'check-update');
  content.children.push(old);
  const ctx = renderContext(content, old);
  ctx._render(true);
  assert.strictEqual(content.scrollTop, 0);
  assert(content.children.every((c) => c.focusCalls.length === 0));
});

test('focus lost while the button was disabled comes back once the button is enabled again', () => {
  const content = fakeContent(300);
  const ctx = renderContext(content, null);
  ctx._pendingFocusKey = 'b|update';
  ctx._render();
  const focused = content.children.filter((c) => c.focusCalls.length > 0);
  assert.strictEqual(focused.length, 1);
  assert.strictEqual(focused[0].dataset.skillId, 'b');
  assert.strictEqual(ctx._pendingFocusKey, null);
  assert.strictEqual(content.scrollTop, 300);

  // A button that is still busy is not focused and the request stays pending.
  const busy = fakeContent(300);
  const second = renderContext(busy, null, {
    _renderInstalled: (c) => c.children.push(rowButton('b', 'check-update', true)),
  });
  second._pendingFocusKey = 'b|update';
  second._render();
  assert.strictEqual(busy.children[0].focusCalls.length, 0);
  assert.strictEqual(second._pendingFocusKey, 'b|update');
});

test('focus the user moved elsewhere is not pulled back to the update button', () => {
  const content = fakeContent(300);
  const ctx = renderContext(content, new FakeEl('input'));
  ctx._pendingFocusKey = 'b|update';
  ctx._render();
  assert(content.children.every((c) => c.focusCalls.length === 0));
});

test('refresh shows the loading skeleton only before the first load', async () => {
  let skeletons = 0;
  const ctx = {
    document: { getElementById: () => ({ tag: 'content', style: {} }) },
    fetch: async () => ({ json: async () => ({ skills: [] }) }),
    _renderSkeleton: () => {
      skeletons += 1;
    },
    _render: () => {},
    _loaded: false,
    _catalog: [],
    _installed: [],
    console,
  };
  const refresh = extractFn('refresh', ctx);
  await refresh();
  assert.strictEqual(skeletons, 1);
  assert.strictEqual(ctx._loaded, true);
  // An empty catalog must not bring the skeleton back: it would collapse a long list.
  await refresh();
  assert.strictEqual(skeletons, 1);
});

test('a Mine skill edited after sharing shows "Shared v1 · edited since" and opens Share', () => {
  const chip = extractFn('_sharedChip', fakeDocument());
  const edited = chip({ tier: 'Mine', id: 'a', published_version: 1, unshared_edits: true });
  assert.strictEqual(edited.tag, 'button');
  assert.strictEqual(edited.textContent, 'Shared v1 · edited since');
  assert.strictEqual(edited.dataset.action, 'share-mine');
  assert.strictEqual(edited.dataset.skillId, 'a');
  const clean = chip({ tier: 'Mine', id: 'a', published_version: 1, unshared_edits: false });
  assert.strictEqual(clean.tag, 'span');
  assert.strictEqual(clean.textContent, 'Shared · v1');
  assert.strictEqual(clean.dataset.action, undefined);
  // The same delegated handler that serves the Share button opens the Share dialog.
  assert(source.includes("action === 'share-mine'"));
  assert(source.includes('_shareMineSkill(btn.dataset.skillId)'));
});
