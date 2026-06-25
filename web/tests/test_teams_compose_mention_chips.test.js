/**
 * Issue #90 — AI-composed @mention shown as plain text in compose pane.
 *
 * Root cause: AI fills the compose via setText(raw) — Quill creates plain text,
 * not MentionBlots. The "Hi @Mayuresh" text is just a string; no chip appears.
 *
 * Fix: After loading the AI draft into Quill, call _tpInjectMentionBlotsFromText(quill, recipients)
 * which scans the Quill text for @Name patterns matching known recipients,
 * and replaces them with real MentionBlot inserts.
 * Recipients already have p.id populated (awaited before this runs).
 *
 * Tests verify:
 * 1. _tpInjectMentionBlotsFromText function exists
 * 2. It scans Quill text for @Name patterns from the recipients list
 * 3. _renderTeamsComposeForm calls it after the AI draft is loaded
 */

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'third-pane.js'),
  'utf8',
);

// ── Test 1: injection helper must exist ──────────────────────────────────────

(function testInjectionHelperExists() {
  assert.ok(
    source.includes('_tpInjectMentionBlotsFromText'),
    '_tpInjectMentionBlotsFromText must exist — scans Quill text for @Name patterns and inserts MentionBlots',
  );
})();

// ── Test 2: helper must scan Quill text and use insertEmbed ─────────────────

(function testHelperUsesInsertEmbed() {
  const helperStart = source.indexOf('function _tpInjectMentionBlotsFromText(');
  assert.notStrictEqual(helperStart, -1, '_tpInjectMentionBlotsFromText function must exist');
  const nextFn = Math.min(
    ...['\nfunction ', '\nasync function '].map(p => {
      const i = source.indexOf(p, helperStart + 1);
      return i === -1 ? Infinity : i;
    }),
  );
  const body = source.slice(helperStart, isFinite(nextFn) ? nextFn : helperStart + 1500);
  assert.ok(
    body.includes('insertEmbed') || body.includes('updateContents'),
    '_tpInjectMentionBlotsFromText must use insertEmbed/updateContents to create MentionBlot chips',
  );
  assert.ok(
    body.includes('getText') || body.includes('getContents') || body.includes('@'),
    '_tpInjectMentionBlotsFromText must scan for @ patterns in the Quill text',
  );
})();

// ── Test 3: compose form must call it after loading the draft ────────────────

(function testComposeCallsInjection() {
  const composeStart = source.indexOf('function _renderTeamsComposeForm(');
  assert.notStrictEqual(composeStart, -1, '_renderTeamsComposeForm must exist');
  // Find end of function (next top-level function)
  const nextFn = Math.min(
    ...['\nfunction ', '\nasync function '].map(p => {
      const i = source.indexOf(p, composeStart + 1);
      return i === -1 ? Infinity : i;
    }),
  );
  const body = source.slice(composeStart, isFinite(nextFn) ? nextFn : composeStart + 10000);
  assert.ok(
    body.includes('_tpInjectMentionBlotsFromText'),
    '_renderTeamsComposeForm must call _tpInjectMentionBlotsFromText after loading the AI draft into Quill',
  );
})();

console.log('test_teams_compose_mention_chips: all checks passed');
