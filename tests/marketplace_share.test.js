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
  const at = source.indexOf("chip.className = 'mp-share-chip'");
  assert(at > 0, 'chip exists');
  const guard = source.lastIndexOf('skill.published_version > 0', at);
  assert(guard > 0 && at - guard < 800, 'chip is guarded by a positive published_version');
  assert(source.includes("'Shared \u00b7 v' + skill.published_version"));
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

test('Share reuses the people search endpoint and hands drafts to the chat', () => {
  const start = source.indexOf('function _shareMineSkill(');
  const body = source.slice(start, source.indexOf('async function _downloadMineSkill(', start));
  assert(body.includes('searchPeople: _searchPeople'));
  assert(body.includes('window.showShareDrafts'));
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

test('app.js exposes showShareDrafts, which closes Settings and injects approval cards', () => {
  const app = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');
  const at = app.indexOf('window.showShareDrafts = function');
  assert(at > 0);
  const body = app.slice(at, at + 400);
  assert(body.includes('closeDrawer()'));
  assert(body.includes('_injectDraftApprovalCard(item._draft, item.data)'));
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

function extractFn(name, ctx) {
  const context = vm.createContext(ctx || {});
  return vm.runInContext(fnSource(name) + ';' + name + ';', context);
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
  assert.strictEqual(renders, 1);
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
  assert(
    source.includes(
      "skill.tier === 'Community' && !!(skill.share_source && skill.share_source.folder_id)",
    ),
  );
  assert(source.includes("updateBtn.textContent = updating ? 'Update' : 'Check for update'"));
  assert(source.includes("updating ? 'apply-update' : 'check-update'"));
  assert(source.includes("action === 'check-update'"));
  assert(source.includes('_checkSharedUpdate(btn.dataset.skillId)'));
});

test('Update reuses the review and install modal with the folder link from the check', () => {
  const at = source.indexOf("action === 'apply-update'");
  assert(at > 0);
  const branch = source.slice(at, source.indexOf("action === 'submit-create'", at));
  assert(branch.includes('_updateStatus[btn.dataset.skillId]'));
  assert(branch.includes('_reviewSharedLink(found.link)'));
  const onInstalled = source.indexOf('delete _updateStatus[result.skill_id]');
  assert(onInstalled > 0, 'the stale answer is dropped once the update installs');
});

test('a Mine skill edited after sharing shows "Shared v1 · edited since" and opens Share', () => {
  const at = source.indexOf('skill.unshared_edits === true');
  assert(at > 0);
  const branch = source.slice(at, source.indexOf("chip.className = 'mp-share-chip';", at));
  assert(branch.includes("document.createElement('button')"));
  assert(branch.includes("'Shared v' + skill.published_version + ' · edited since'"));
  assert(branch.includes("chip.dataset.action = 'share-mine'"));
  assert(branch.includes('chip.dataset.skillId = skill.id'));
  // The same delegated handler that serves the Share button opens the Share dialog.
  assert(source.includes("action === 'share-mine'"));
  assert(source.includes('_shareMineSkill(btn.dataset.skillId)'));
});
