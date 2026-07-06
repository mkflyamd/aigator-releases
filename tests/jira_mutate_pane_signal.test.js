// Issue #145: jira_mutate POST issue success must emit a jira-issue pane signal
// so the detail pane opens automatically after the LLM handover creates a ticket.

'use strict';

const assert = require('assert');

// ── Stubs ─────────────────────────────────────────────────────────────────────

let renderCalled = null;
let successCardCalled = null;
let myWorkRefreshed = false;
let paneOpened = null;

function openThirdPane(type) { paneOpened = type; }
function _renderJiraIssueDetail(container, key, url) { renderCalled = { container, key, url }; }
function _postJiraSuccessCard(key, url) { successCardCalled = { key, url }; }
function _renderJiraMyWork(el) { myWorkRefreshed = true; }

function reset() {
  renderCalled = null; successCardCalled = null;
  myWorkRefreshed = false; paneOpened = null;
}

// ── Frontend handler (mirrors the jira-issue branch added to _handlePaneSignal) ─

function handleJiraIssuePaneSignal(pane, paneData) {
  if (pane !== 'jira-issue') return;
  openThirdPane('jira');
  const detailCol = { id: 'tp-detail-col' }; // stub for document.getElementById
  _renderJiraIssueDetail(detailCol, paneData.key, paneData.url || '');
  _renderJiraMyWork(null);
  if (paneData.key && paneData.url) _postJiraSuccessCard(paneData.key, paneData.url);
}

// ── Backend emission (mirrors _tool_jira_mutate pane signal logic in tools.py) ─

const BROWSE_URL = 'https://jira.example.com';

function simulateMutateResult(method, path, apiResponse) {
  const result = apiResponse || { ok: true };
  const cleanPath = path.replace(/^\//, '').split('?')[0].replace(/\/$/, '');
  if (method === 'POST' && cleanPath === 'issue' && result.key) {
    const key = result.key;
    const url = `${BROWSE_URL}/browse/${key}`;
    return Object.assign({}, result, { _pane: 'jira-issue', data: { key, url } });
  }
  return result;
}

// ─────────────────────────────────────────────────────────────────────────────
// Frontend handler tests
// ─────────────────────────────────────────────────────────────────────────────

// jira-issue opens pane, renders detail, posts success card
{
  reset();
  handleJiraIssuePaneSignal('jira-issue', { key: 'AIVLLM-300', url: 'https://jira.example.com/browse/AIVLLM-300' });
  assert.strictEqual(paneOpened, 'jira', 'pane opened as jira');
  assert.ok(renderCalled, '_renderJiraIssueDetail called');
  assert.strictEqual(renderCalled.key, 'AIVLLM-300', 'correct key passed to detail render');
  assert.strictEqual(renderCalled.url, 'https://jira.example.com/browse/AIVLLM-300', 'correct url passed');
  assert.ok(myWorkRefreshed, '_renderJiraMyWork called');
  assert.ok(successCardCalled, '_postJiraSuccessCard called');
  assert.strictEqual(successCardCalled.key, 'AIVLLM-300', 'success card has correct key');
}

// non-jira-issue pane is ignored
{
  reset();
  handleJiraIssuePaneSignal('jira-create', { key: 'AIVLLM-300' });
  assert.strictEqual(paneOpened, null, 'jira-create pane: does not fire jira-issue handler');
}

// ─────────────────────────────────────────────────────────────────────────────
// Backend pane signal emission tests
// ─────────────────────────────────────────────────────────────────────────────

// POST issue with key → emits jira-issue pane signal
{
  const result = simulateMutateResult('POST', 'issue', { key: 'AIVLLM-300', id: '10001' });
  assert.strictEqual(result._pane, 'jira-issue', 'POST issue: _pane is jira-issue');
  assert.strictEqual(result.data.key, 'AIVLLM-300', 'POST issue: data.key correct');
  assert.ok(result.data.url.includes('AIVLLM-300'), 'POST issue: data.url contains key');
}

// POST issue with leading slash in path
{
  const result = simulateMutateResult('POST', '/issue', { key: 'ROCM-99' });
  assert.strictEqual(result._pane, 'jira-issue', 'leading-slash path: pane signal emitted');
  assert.strictEqual(result.data.key, 'ROCM-99');
}

// POST issue with no key in response (error case) → no pane signal
{
  const result = simulateMutateResult('POST', 'issue', { error: 'forbidden' });
  assert.strictEqual(result._pane, undefined, 'error response: no pane signal');
}

// POST to non-issue path → no pane signal
{
  const result = simulateMutateResult('POST', 'issueLink', { ok: true });
  assert.strictEqual(result._pane, undefined, 'issueLink: no pane signal');
}

// PUT issue → no pane signal
{
  const result = simulateMutateResult('PUT', 'issue/AIVLLM-300', {});
  assert.strictEqual(result._pane, undefined, 'PUT: no pane signal');
}

// DELETE → no pane signal
{
  const result = simulateMutateResult('DELETE', 'issue/AIVLLM-300', {});
  assert.strictEqual(result._pane, undefined, 'DELETE: no pane signal');
}

// POST issue with trailing slash in path
{
  const result = simulateMutateResult('POST', 'issue/', { key: 'PLM-5' });
  assert.strictEqual(result._pane, 'jira-issue', 'trailing-slash path: pane signal emitted');
}

console.log('jira_mutate_pane_signal: all assertions passed');
