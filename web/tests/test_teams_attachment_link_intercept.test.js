/**
 * Issue #149 — Teams messages with received/attached files render blank.
 *
 * Companion to test_teams_link_intercept.test.js (#105), but for the file
 * attachment chips rendered below a message body (.tp-msg-attachments), not
 * the links inside the message text. Once the backend started returning
 * `msg.attachments` for Skype file shares, those links needed the same
 * explicit click handler as body links — a plain target="_blank" anchor gets
 * intercepted by Electron's global navigation handler, which opens an AI
 * chat prompt instead of the OS browser.
 */

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'third-pane.js'),
  'utf8',
);

function getBuildTeamsMessageSource() {
  const start = source.indexOf('function _buildTeamsMessage(');
  assert.notStrictEqual(start, -1, '_buildTeamsMessage must exist');
  const nextFn = source.indexOf('\nfunction ', start + 1);
  return source.slice(start, nextFn !== -1 ? nextFn : start + 8000);
}

// ── Test 1: attachment rendering block exists and is guarded by content_url ──

(function testAttachmentBlockExists() {
  const src = getBuildTeamsMessageSource();
  assert.ok(
    src.includes('tp-msg-attachments') && src.includes('msg.attachments'),
    '_buildTeamsMessage must render msg.attachments into .tp-msg-attachments',
  );
})();

// ── Test 2: attachment links must have an explicit click handler ────────────

(function testAttachmentLinksHaveClickHandler() {
  const src = getBuildTeamsMessageSource();
  const attachBlockStart = src.indexOf('tp-msg-attachments');
  assert.notStrictEqual(attachBlockStart, -1);
  const attachBlock = src.slice(attachBlockStart, attachBlockStart + 1500);

  assert.ok(
    attachBlock.includes("addEventListener('click'"),
    'attachment links must have a click handler — a plain target="_blank" '
    + 'anchor is intercepted by Electron\'s global navigation handler (#105/#149)',
  );
  assert.ok(
    attachBlock.includes('preventDefault'),
    'attachment link click handler must call preventDefault() to block the '
    + 'Electron navigation intercept',
  );
  assert.ok(
    attachBlock.includes("window.open("),
    'attachment link click handler must explicitly window.open() the file URL',
  );
})();

console.log('test_teams_attachment_link_intercept: all checks passed');
