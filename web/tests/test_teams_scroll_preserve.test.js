/**
 * Issue #123 — Marking a Teams conversation read/unread auto-scrolls chat list to top.
 *
 * Root cause: the mark-read/unread handler calls renderTeamsList() which re-renders
 * the entire list, resetting scrollTop to 0. The handler does not save/restore
 * the scroll position around the re-render.
 *
 * Fix: capture .tp-list-scroll scrollTop before calling renderTeamsList(),
 * restore it immediately after — same pattern already used in the "load more" handler.
 */

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'third-pane.js'),
  'utf8',
);

// ── Test 1: mark-as-read handler must save+restore scroll position ────────────

(function testMarkReadPreservesScroll() {
  // Find the mark-as-read action in the context menu handler
  const markReadIdx = source.indexOf("'Mark as read'");
  assert.notStrictEqual(markReadIdx, -1, "Mark as read context menu item must exist");

  // Find the action: function body for mark-as-read
  const actionStart = source.lastIndexOf('action: () => {', markReadIdx + 200);
  assert.notStrictEqual(actionStart, -1, 'mark-as-read action callback must exist');
  // Capture the action body (up to end of block)
  const actionBody = source.slice(actionStart, actionStart + 600);

  // Must save scroll before renderTeamsList
  assert.ok(
    actionBody.includes('scrollTop') || actionBody.includes('savedTop') || actionBody.includes('savedScroll'),
    "Mark-as-read action must save scroll position before re-rendering the list. " +
    `Found action body: ${actionBody.slice(0, 300)}`,
  );

  // Must call renderTeamsList (the re-render that causes the scroll jump)
  assert.ok(
    actionBody.includes('renderTeamsList'),
    "Mark-as-read action must call renderTeamsList",
  );
})();

// ── Test 2: mark-as-unread handler must also preserve scroll ─────────────────

(function testMarkUnreadPreservesScroll() {
  const markUnreadIdx = source.indexOf("'Mark as unread'");
  assert.notStrictEqual(markUnreadIdx, -1, "Mark as unread context menu item must exist");

  const actionStart = source.lastIndexOf('action: () => {', markUnreadIdx + 200);
  const actionBody = source.slice(actionStart, actionStart + 600);

  assert.ok(
    actionBody.includes('scrollTop') || actionBody.includes('savedTop') || actionBody.includes('savedScroll'),
    "Mark-as-unread action must save scroll position before re-rendering. " +
    `Found: ${actionBody.slice(0, 300)}`,
  );
})();

// ── Test 3: load-more remote fetch already preserves scroll (regression guard) ─

(function testLoadMoreAlreadyPreservesScroll() {
  // The "Load more" remote fetch handler already has scroll preservation.
  // Verify it's still there so we haven't accidentally broken it.
  const loadMoreIdx = source.indexOf("'Load more'");
  assert.notStrictEqual(loadMoreIdx, -1, "Load more button must exist");
  const loadMoreCtx = source.slice(loadMoreIdx, loadMoreIdx + 800);
  assert.ok(
    loadMoreCtx.includes('savedTop') || loadMoreCtx.includes('scrollTop'),
    "Load more handler must still preserve scroll position (regression guard)",
  );
})();

console.log('test_teams_scroll_preserve: all checks passed');
