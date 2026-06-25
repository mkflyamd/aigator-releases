/**
 * Issues #92 / #119 — @mention lost on message edit.
 *
 * Root cause: _runInlineEdit loads the existing message body via
 * dangerouslyPasteHTML(). The body contains <at data-aad="guid">Name</at>
 * (backend-normalized format). Quill parses those as plain inline HTML, NOT
 * as MentionBlots. _buildMentionPayload finds 0 blots → returns empty
 * mentions[] → PATCH sends no mention data → Teams drops the @mention.
 *
 * Fix: after loading the edit body into Quill, convert any <at data-aad>
 * nodes into real MentionBlot embeds so _buildMentionPayload picks them up.
 * The conversion helper is _tpConvertAtNodesToMentionBlots(quill).
 *
 * Tests verify:
 * 1. _tpConvertAtNodesToMentionBlots exists in the source
 * 2. _runInlineEdit calls it after dangerouslyPasteHTML
 * 3. The edit save handler's _buildMentionPayload call fires AFTER the conversion
 */

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'third-pane.js'),
  'utf8',
);

// ── Test 1: conversion helper must exist ─────────────────────────────────────

(function testConversionHelperExists() {
  assert.ok(
    source.includes('_tpConvertAtNodesToMentionBlots'),
    '_tpConvertAtNodesToMentionBlots must exist — converts <at data-aad> nodes to Quill MentionBlots after dangerouslyPasteHTML',
  );
})();

// ── Test 2: helper pre-processes HTML string → ql-mention spans ──────────────

(function testHelperPreprocessesHtmlString() {
  const helperStart = source.indexOf('function _tpConvertAtNodesToMentionBlots(');
  assert.notStrictEqual(helperStart, -1, '_tpConvertAtNodesToMentionBlots function must exist');
  const nextFn = Math.min(
    ...['\nfunction ', '\nasync function '].map(p => {
      const i = source.indexOf(p, helperStart + 1);
      return i === -1 ? Infinity : i;
    }),
  );
  const body = source.slice(helperStart, isFinite(nextFn) ? nextFn : helperStart + 1500);
  // Must convert <at data-aad> to ql-mention spans (pre-HTML approach, not DOM mutation)
  assert.ok(
    body.includes('ql-mention'),
    '_tpConvertAtNodesToMentionBlots must produce ql-mention spans readable by MentionBlot',
  );
  assert.ok(
    body.includes('data-aad') || body.includes('data-id'),
    '_tpConvertAtNodesToMentionBlots must read/write data-aad / data-id for the mention',
  );
  assert.ok(
    body.includes('replace('),
    '_tpConvertAtNodesToMentionBlots must use string.replace() to pre-process HTML (not DOM mutation)',
  );
})();

// ── Test 3: _runInlineEdit must pass originalContent through the conversion ───

(function testRunInlineEditCallsConversion() {
  const runEditStart = source.indexOf('function _runInlineEdit(');
  assert.notStrictEqual(runEditStart, -1, '_runInlineEdit must exist');
  const nextFn = Math.min(
    ...['\nfunction ', '\nasync function '].map(p => {
      const i = source.indexOf(p, runEditStart + 1);
      return i === -1 ? Infinity : i;
    }),
  );
  const body = source.slice(runEditStart, isFinite(nextFn) ? nextFn : runEditStart + 6000);
  assert.ok(
    body.includes('_tpConvertAtNodesToMentionBlots'),
    '_runInlineEdit must call _tpConvertAtNodesToMentionBlots to pre-process <at data-aad> before dangerouslyPasteHTML',
  );
  // Conversion must wrap the originalContent argument to dangerouslyPasteHTML
  assert.ok(
    body.includes('dangerouslyPasteHTML(0, _tpConvertAtNodesToMentionBlots('),
    '_tpConvertAtNodesToMentionBlots must be applied inline to the HTML string passed to dangerouslyPasteHTML',
  );
})();

// ── Test 4: conversion must happen before _buildMentionPayload is called ─────

(function testConversionBeforeBuildPayload() {
  const runEditStart = source.indexOf('function _runInlineEdit(');
  const nextFn = Math.min(
    ...['\nfunction ', '\nasync function '].map(p => {
      const i = source.indexOf(p, runEditStart + 1);
      return i === -1 ? Infinity : i;
    }),
  );
  const body = source.slice(runEditStart, isFinite(nextFn) ? nextFn : runEditStart + 6000);
  const convertIdx = body.indexOf('_tpConvertAtNodesToMentionBlots');
  // Find the CALL to _buildMentionPayload (not just the name appearing in comments)
  // It's called as: _buildMentionPayload(quill) — look for the invocation
  const buildCallIdx = body.indexOf('_buildMentionPayload(');
  assert.ok(
    convertIdx !== -1 && buildCallIdx !== -1 && convertIdx < buildCallIdx,
    '_tpConvertAtNodesToMentionBlots must be called BEFORE _buildMentionPayload(quill) invocation in _runInlineEdit',
  );
})();

console.log('test_teams_mention_edit_blots: all checks passed');
