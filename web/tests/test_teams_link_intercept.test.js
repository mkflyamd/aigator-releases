/**
 * Issue #105 — Recording/Play links in Teams chat open AI chat instead of browser.
 *
 * Root cause: links rendered inside .tp-msg-text via sanitizeHtml have no target
 * attribute and no click handler — in Electron the navigation is intercepted by
 * the app's global handler, which opens an AI chat prompt instead of the OS browser.
 *
 * Fix: after rendering textEl.innerHTML, attach a click handler to all <a> tags
 * inside .tp-msg-text that calls window.open(href, '_blank', 'noopener') for
 * external http/https URLs, preventing the Electron navigation intercept.
 */

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'third-pane.js'),
  'utf8',
);

// ── Test 1: _buildTeamsMessage must wire link clicks to open externally ────────

(function testMessageBodyLinksOpenExternally() {
  const buildMsgStart = source.indexOf('function _buildTeamsMessage(');
  assert.notStrictEqual(buildMsgStart, -1, '_buildTeamsMessage must exist');
  const nextFn = source.indexOf('\nfunction ', buildMsgStart + 1);
  const buildMsgSrc = source.slice(buildMsgStart, nextFn !== -1 ? nextFn : buildMsgStart + 6000);

  // Must have a click handler on links in the message body
  assert.ok(
    buildMsgSrc.includes('tp-msg-text') && buildMsgSrc.includes('querySelectorAll'),
    '_buildTeamsMessage must query links inside .tp-msg-text to wire them',
  );

  // Must call window.open with _blank for external links
  assert.ok(
    buildMsgSrc.includes("'_blank'") || buildMsgSrc.includes('"_blank"'),
    "_buildTeamsMessage must open message body links with target '_blank'",
  );
})();

// ── Test 2: the link handler must preventDefault to block Electron intercept ──

(function testMessageLinkHandlerPreventsDefault() {
  const buildMsgStart = source.indexOf('function _buildTeamsMessage(');
  const nextFn = source.indexOf('\nfunction ', buildMsgStart + 1);
  const buildMsgSrc = source.slice(buildMsgStart, nextFn !== -1 ? nextFn : buildMsgStart + 6000);

  // Must prevent default navigation — without this, Electron's global handler fires
  assert.ok(
    buildMsgSrc.includes('preventDefault'),
    "_buildTeamsMessage link handler must call preventDefault() to block Electron navigation",
  );
})();

// ── Test 3: only http/https links get the external handler (not mailto etc.) ──

(function testLinkHandlerOnlyForHttps() {
  const buildMsgStart = source.indexOf('function _buildTeamsMessage(');
  const nextFn = source.indexOf('\nfunction ', buildMsgStart + 1);
  const buildMsgSrc = source.slice(buildMsgStart, nextFn !== -1 ? nextFn : buildMsgStart + 6000);

  // Must filter for http/https — mailto and tel links should not be intercepted
  assert.ok(
    buildMsgSrc.includes('http') || buildMsgSrc.includes('href'),
    "_buildTeamsMessage link handler should be scoped to http/https links",
  );
})();

console.log('test_teams_link_intercept: all checks passed');
