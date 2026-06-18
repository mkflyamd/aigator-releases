// Issue #96: File path not rendered as clickable button after AI creates/edits a file.
//
// The applyInline() path-detection regexes only matched backslash separators.
// Python's Path on Windows can emit forward slashes, and AI prose sometimes uses
// forward slashes too. Fix: accept both \ and / as path separators.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'app.js'),
  'utf8',
);

// Extract escapeHtml and applyInline from app.js
const escapeMatch = source.match(/function escapeHtml\(t\)\s*\{[\s\S]*?\n\}/);
assert(escapeMatch, 'escapeHtml not found in app.js');

const applyMatch = source.match(/function applyInline\(html\)\s*\{[\s\S]*?\n\}/);
assert(applyMatch, 'applyInline not found in app.js');

// Provide window stub so applyInline's Jira key pass doesn't crash
const ctx = vm.createContext({ window: { GATOR_JIRA_INSTANCES: [], GATOR_JIRA_URL: null } });
vm.runInContext(escapeMatch[0], ctx);
vm.runInContext(applyMatch[0], ctx);
const applyInline = vm.runInContext('applyInline', ctx);

function hasFileBtn(html) {
  return html.includes('class="file-path-btn"');
}

// Case 1: Backslash path embedded in prose (should already work)
{
  const out = applyInline('The file was saved to C:\\Users\\maykulka\\Downloads\\deck.pptx in your Downloads folder.');
  assert(hasFileBtn(out), 'backslash path in prose must become a button');
}

// Case 2: Backslash path in backticks (should already work)
{
  const out = applyInline('The file is at `C:\\Users\\maykulka\\Downloads\\Rocm.AI\\file.pptx`.');
  assert(hasFileBtn(out), 'backslash path in backticks must become a button');
}

// Case 3 (the bug): Forward-slash path in prose
{
  const out = applyInline('The file was saved to C:/Users/maykulka/Downloads/deck.pptx in your Downloads folder.');
  assert(hasFileBtn(out), 'forward-slash Windows path in prose must become a button');
}

// Case 4 (the bug): Forward-slash path in backticks
{
  const out = applyInline('The file is at `C:/Users/maykulka/Downloads/Rocm.AI/file.pptx`.');
  assert(hasFileBtn(out), 'forward-slash Windows path in backticks must become a button');
}

// Case 5: Mixed slashes in backticks
{
  const out = applyInline('Saved to `C:\\Users\\maykulka/Downloads/deck.pptx`.');
  assert(hasFileBtn(out), 'mixed-slash Windows path in backticks must become a button');
}

// Case 6: Non-path backtick content must remain a code span
{
  const out = applyInline('Run `npm install` first.');
  assert(!hasFileBtn(out), 'non-path backtick content must not become a button');
  assert(out.includes('<code>'), 'non-path backtick content must be wrapped in <code>');
}

// Case 7: Plain non-Windows path must not become a button
{
  const out = applyInline('Check the `config.json` file.');
  assert(!hasFileBtn(out), 'plain filename without drive letter must not become a button');
}

console.log('jira_file_path_btn: all assertions passed');
