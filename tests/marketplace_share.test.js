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
  assert(body.includes('return _downloadMineSkill(skillId)'), 'falls back when the module is missing');
});

test('Mine rows show a Shared chip only for a positive published_version', () => {
  assert(source.includes('Share with colleagues through OneDrive, or download a file'));
  const at = source.indexOf("chip.className = 'mp-share-chip'");
  assert(at > 0, 'chip exists');
  const guard = source.lastIndexOf('skill.published_version > 0', at);
  assert(guard > 0 && at - guard < 200, 'chip is guarded by a positive published_version');
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
  assert(/if \(!resp\.ok\) throw new Error\(/.test(fn), 'a failed search throws so it is not cached as empty');
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
