// An approved draft that only partly went through (e.g. the Jira status changed but the
// comment failed) must say so on the card instead of showing a plain "Applied".
// The real helper is cut out of app.js and run against a stub DOM.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { test } = require('node:test');

const source = fs
  .readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8')
  .replace(/\r\n/g, '\n');

const start = source.indexOf('function _showApprovalWarning');
assert(start >= 0, 'helper found');
const end = source.indexOf('\nfunction ', start + 10);
const helperSource = source.slice(start, end);

function run(result) {
  const inserted = [];
  const approveBtn = {
    textContent: 'Applied ✓',
    parentNode: {
      insertBefore(node, ref) {
        inserted.push({ node, ref });
      },
    },
    nextSibling: 'sibling',
  };
  const sandbox = { document: { createElement: () => ({ style: {}, className: '' }) } };
  vm.createContext(sandbox);
  vm.runInContext(helperSource + '\nthis.fn = _showApprovalWarning;', sandbox);
  const shown = sandbox.fn(approveBtn, result);
  return { shown, approveBtn, inserted };
}

test('a partial result with a warning is shown on the card', () => {
  const { shown, approveBtn, inserted } = run({ ok: 'partial', warning: 'comment failed' });
  assert.strictEqual(shown, true);
  assert.strictEqual(approveBtn.textContent, 'Applied with a warning');
  assert.strictEqual(inserted.length, 1);
  assert.strictEqual(inserted[0].node.textContent, 'comment failed');
  assert.strictEqual(inserted[0].node.className, 'gcc-draft-warning');
});

test('a partial result with no warning still says so, with a default message', () => {
  const { shown, approveBtn, inserted } = run({ ok: 'partial' });
  assert.strictEqual(shown, true);
  assert.strictEqual(approveBtn.textContent, 'Applied with a warning');
  assert.match(inserted[0].node.textContent, /did not confirm every change/);
});

test('a write that fell back to the Atlassian MCP says so, even when nothing else is wrong', () => {
  const fallback = { from: 'builtin-rest', to: 'atlassian-mcp', reason: 'HTTP 400: labels' };
  const { shown, approveBtn, inserted } = run({ ok: true, fallback });
  assert.strictEqual(shown, true);
  assert.strictEqual(approveBtn.textContent, 'Applied via Atlassian MCP');
  assert.match(
    inserted[0].node.textContent,
    /direct Jira API rejected this change \(HTTP 400: labels\)/,
  );
  assert.match(inserted[0].node.textContent, /Atlassian MCP on the same site/);
});

test('a fallback that also ended partial shows both lines', () => {
  const { approveBtn, inserted } = run({
    ok: 'partial',
    warning: 'comment failed',
    fallback: { from: 'builtin-rest', to: 'atlassian-mcp', reason: 'HTTP 422' },
  });
  assert.strictEqual(approveBtn.textContent, 'Applied with a warning');
  assert.match(inserted[0].node.textContent, /Atlassian MCP on the same site\.\ncomment failed$/);
});

test('a clean or missing result leaves the card alone', () => {
  for (const result of [{ ok: true }, {}, null, { ok: true, warning: 'x' }]) {
    const { shown, approveBtn, inserted } = run(result);
    assert.strictEqual(shown, false);
    assert.strictEqual(approveBtn.textContent, 'Applied ✓');
    assert.strictEqual(inserted.length, 0);
  }
});

test('the approve click handler consults the helper before navigating away', () => {
  const i = source.indexOf('_showApprovalWarning(approveBtn, _json)');
  assert(i > 0, 'handler calls the helper');
  const j = source.indexOf('_gatorNavAfterApproval(_nav, card)', i);
  assert(j > i, 'navigation only follows the helper check');
});
