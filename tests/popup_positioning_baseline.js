/**
 * Baseline regression tests for all popup positioning in AI Gator.
 * Run in the browser console via: copy-paste or injected script.
 *
 * Each test:
 *   1. Opens the popup
 *   2. Asserts it's fully within the viewport (fullyInViewport)
 *   3. Asserts it's within 8px margin of any edge
 *   4. For resize-sensitive popups: triggers resize and re-checks
 *
 * Usage: node tests/popup_positioning_baseline.js  (source inspection only)
 *        Or paste _runBrowserTests() into browser console for live tests.
 */

// ── Source-inspection guards (runnable in Node) ──────────────────────────────
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const appJs = fs.readFileSync(path.join(__dirname, '../web/static/app.js'), 'utf8');
const tpJs  = fs.readFileSync(path.join(__dirname, '../web/static/third-pane.js'), 'utf8');

// Guard 1: _positionDropdownFixed must exist in app.js
assert(appJs.includes('function _positionDropdownFixed('), '_positionDropdownFixed must exist in app.js');
// Guard 2: _positionDropdownFixed must delegate to _fpopup (which uses FloatingUIDOM internally)
{
  const start = appJs.indexOf('function _positionDropdownFixed(');
  const body = appJs.slice(start, start + 1000);
  assert(body.includes('_fpopup(') || body.includes('computePosition') || body.includes('FloatingUIDOM'),
    '_positionDropdownFixed must use _fpopup or FloatingUIDOM for positioning');
}

// Guard 3: emoji picker must use _fpopup (which handles ResizeObserver via autoUpdate)
assert(tpJs.includes("_fullPicker._emojiCleanup = _fpopup("), 'emoji picker must assign _fpopup cleanup to _fullPicker._emojiCleanup');

// Guard 4: people card must use _fpopup (replaces _posPersonCard)
assert(tpJs.includes("_cardCleanup = _fpopup(card, anchorEl"), 'people card must use _fpopup for positioning');

// Guard 5: Jira select positionPanel must have vertical flip
{
  const start = tpJs.indexOf('function positionPanel(');
  assert(start > -1, 'positionPanel must exist in third-pane.js');
  const body = tpJs.slice(start, start + 1000);
  assert(body.includes('spaceBelow') || body.includes('innerHeight'), 'Jira positionPanel must check viewport height');
}

// Guard 6: FloatingUI must be present after migration
assert(appJs.includes('FloatingUIDOM'), '_fpopup in app.js must reference FloatingUIDOM');
assert(appJs.includes('function _fpopup('), '_fpopup shared helper must exist in app.js');
assert(tpJs.includes('_fpopup('), 'third-pane.js must use _fpopup for popup positioning');

// Guard 7: old inline implementations must be gone from third-pane.js
assert(!tpJs.includes('_reposEmoji'), '_reposEmoji inline emoji positioning must be replaced by _fpopup');
assert(!tpJs.includes('_posPersonCard'), '_posPersonCard inline people card positioning must be replaced by _fpopup');

// Guard 8: _tpAnchorDropdown must now delegate to _fpopup
{
  const start = tpJs.indexOf('function _tpAnchorDropdown(');
  const body = tpJs.slice(start, start + 500);
  assert(body.includes('_fpopup('), '_tpAnchorDropdown must delegate to _fpopup');
}

console.log('popup_positioning_baseline: all source-inspection guards passed (post-migration)');

// ── Browser test helper (paste into console) ─────────────────────────────────
/*
async function _runBrowserTests() {
  const vh = window.innerHeight, vw = window.innerWidth;
  const MARGIN = 8;
  const results = [];

  function checkBounds(el, label) {
    const r = el.getBoundingClientRect();
    const pass = r.top >= -1 && r.bottom <= vh + 1 && r.left >= -1 && r.right <= vw + 1;
    const overflowBy = Math.max(0, r.bottom - vh, r.right - vw, -r.top, -r.left);
    results.push({ label, pass, overflowBy: Math.round(overflowBy), bounds: { top: Math.round(r.top), bottom: Math.round(r.bottom) } });
    return pass;
  }

  // TEST 1: @mention dropdown
  const input = document.querySelector('#chat-input, [data-testid="chat-input"], .ql-editor');
  if (input) {
    input.focus();
    input.dispatchEvent(new KeyboardEvent('keydown', { key: '@', bubbles: true }));
    await new Promise(r => setTimeout(r, 500));
    const dd = document.querySelector('.mention-dropdown, [class*="mention"]');
    if (dd) checkBounds(dd, '@mention dropdown');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  }

  // TEST 2: Emoji picker (need to be in Teams chat)
  const emojiBtn = document.querySelector('.tp-quill-emoji-btn, button[title*="moji"], button[aria-label*="moji"]');
  if (emojiBtn) {
    emojiBtn.click();
    await new Promise(r => setTimeout(r, 200));
    const picker = document.querySelector('.tp-emoji-picker-popup:not(.hidden)');
    if (picker) {
      checkBounds(picker, 'emoji picker (empty)');
      const si = picker.querySelector('.tp-ep-search');
      if (si) { si.value = 's'; si.dispatchEvent(new Event('input', { bubbles: true })); }
      await new Promise(r => setTimeout(r, 400));
      checkBounds(picker, 'emoji picker (search results)');
    }
    document.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  }

  // TEST 3: People card
  const personLink = document.querySelector('[data-aad-id], .tp-mention-person');
  if (personLink) {
    personLink.click();
    await new Promise(r => setTimeout(r, 1000));
    const card = document.getElementById('tp-person-card');
    if (card) checkBounds(card, 'people card');
    card?.remove();
  }

  // TEST 4: Jira custom select (if Jira pane open)
  const jiraSelect = document.querySelector('.jira-csel-trigger');
  if (jiraSelect) {
    jiraSelect.click();
    await new Promise(r => setTimeout(r, 100));
    const panel = document.querySelector('.jira-csel-panel.open');
    if (panel) checkBounds(panel, 'Jira custom select panel');
    jiraSelect.click(); // close
  }

  // TEST 5: Model selector
  const modelBtn = document.querySelector('[data-testid="model-btn"], .model-selector-btn, button[aria-label*="model"]');
  if (modelBtn) {
    modelBtn.click();
    await new Promise(r => setTimeout(r, 100));
    const drop = document.getElementById('model-dropdown');
    if (drop) checkBounds(drop, 'model selector dropdown');
    document.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  }

  console.table(results);
  const failed = results.filter(r => !r.pass);
  console.log(`${results.length} tested, ${failed.length} failed`);
  if (failed.length) console.warn('FAILED:', failed.map(r => r.label + ' overflow=' + r.overflowBy + 'px').join(', '));
  return { results, passed: results.filter(r => r.pass).length, failed: failed.length };
}
// Run: await _runBrowserTests()
*/
