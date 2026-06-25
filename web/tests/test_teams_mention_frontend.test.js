/**
 * Issues #90, #92, #93, #119 — Teams @mention frontend bugs.
 *
 * #90  - AI-composed plain-text @mentions not sent as real mention entities
 * #92  - @mention loses formatting after edit (edit PATCH sends no mentions)
 * #93  - @mention shows as plain text on first optimistic render
 * #119 - Editing a message silently drops @mentions
 *
 * Tests verify:
 * 1. Edit save handler sends `mentions` in PATCH body (not just `body`)
 * 2. Optimistic bubble receives and preserves mention HTML from send payload
 * 3. _buildMentionPayload output includes Skype itemtype spans (not <at> tags)
 */

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'third-pane.js'),
  'utf8',
);

// ── Test 1: edit PATCH body must include mentions ─────────────────────────────

(function testEditPatchIncludesMentions() {
  const runEditStart = source.indexOf('function _runInlineEdit(');
  assert.notStrictEqual(runEditStart, -1, '_runInlineEdit must exist');
  // Find the next function boundary after _runInlineEdit
  const nextFn = source.indexOf('\nfunction ', runEditStart + 1);
  const editFnSrc = source.slice(runEditStart, nextFn !== -1 ? nextFn : runEditStart + 6000);
  // The PATCH body JSON.stringify inside the edit save handler must include mentions
  assert.ok(
    editFnSrc.includes("method: 'PATCH'"),
    'PATCH fetch must exist inside _runInlineEdit',
  );
  // Find JSON.stringify after 'PATCH' in the edit fn source
  const patchIdx = editFnSrc.indexOf("method: 'PATCH'");
  const bodyCtx = editFnSrc.slice(Math.max(0, patchIdx - 400), patchIdx + 50);
  assert.ok(
    bodyCtx.includes('mentions'),
    `Edit PATCH body must include 'mentions'. Context around PATCH: ${bodyCtx.slice(0, 400)}`,
  );
})();

// ── Test 2: _buildMentionPayload uses Skype itemtype span (not <at>) ──────────

(function testBuildMentionPayloadUsesSkypeSpan() {
  const helperStart = source.indexOf('function _buildMentionPayload(');
  assert.notStrictEqual(helperStart, -1, '_buildMentionPayload must exist');
  // Find next function boundary — handles both 'function' and 'async function'
  const nextFn = Math.min(
    ...['\nfunction ', '\nasync function '].map(p => {
      const i = source.indexOf(p, helperStart + 1);
      return i === -1 ? Infinity : i;
    }),
  );
  const body = source.slice(helperStart, isFinite(nextFn) ? nextFn : helperStart + 2000);
  assert.ok(
    body.includes('http://schema.skype.com/Mention'),
    '_buildMentionPayload must produce Skype itemtype="http://schema.skype.com/Mention" spans, not <at> tags',
  );
  assert.ok(
    !body.includes('<at '),
    '_buildMentionPayload must not use <at> tags — Skype API uses itemscope/itemtype spans',
  );
})();

// ── Test 3: optimistic bubble uses displayText/HTML that preserves mention spans

(function testOptimisticBubblePreservesMentionHtml() {
  // tpSendTeamsMessage builds the optimistic bubble from bubbleHtml / displayText
  // The optimistic _buildTeamsMessage call must receive body_html (not just body/text)
  // so that Skype mention spans render immediately without a round-trip.
  const sendFnStart = source.indexOf('async function tpSendTeamsMessage(');
  assert.notStrictEqual(sendFnStart, -1, 'tpSendTeamsMessage must exist');
  const nextFn = source.indexOf('\nasync function ', sendFnStart + 1);
  const sendBody = source.slice(sendFnStart, nextFn !== -1 ? nextFn : sendFnStart + 3000);

  // The optimistic object passed to _buildTeamsMessage must use body_html
  // (not just `body`) so mention spans survive the optimistic render
  assert.ok(
    sendBody.includes('body_html'),
    'tpSendTeamsMessage optimistic bubble must set body_html so mention HTML renders immediately',
  );
})();

// ── Test 4: edit save handler extracts mentions from Quill before sending ─────

(function testEditSaveHandlerExtractsMentions() {
  const runEditStart = source.indexOf('function _runInlineEdit(');
  assert.notStrictEqual(runEditStart, -1, '_runInlineEdit must exist');
  const nextFn = source.indexOf('\nfunction ', runEditStart + 1);
  const editBody = source.slice(runEditStart, nextFn !== -1 ? nextFn : runEditStart + 5000);

  // The save handler must call _buildMentionPayload (to extract mentions from Quill)
  assert.ok(
    editBody.includes('_buildMentionPayload'),
    '_runInlineEdit save handler must call _buildMentionPayload to extract mentions from Quill before PATCH',
  );
})();

console.log('test_teams_mention_frontend: all checks passed');
