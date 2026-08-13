// OneDrive pin extraction regressions (shell/main.js).
//
// Two bugs produced unresolvable pins that 404'd in the backend:
//   1. The item-id extractor returned the bare "SPO@{siteGuid}" (a site id, not
//      a file id) instead of the resolvable itemKey after the comma. This wrote
//      pins like "SPO@3dd8961f-..." that Graph could never resolve.
//   2. The label was scraped from an element whose textContent included the
//      "modified X ago" + author text, producing labels like
//      "ROCmAi Release Review.pptx8 minutes agoKulkarni," — which then poisoned
//      the backend's filename search fallback.
//
// This test extracts the pure _itemIdFromAttrs helper from main.js and runs it
// in a vm sandbox (same pattern as file_chip_remove.test.js). It asserts the
// extractor recovers the itemKey and NEVER returns a bare SPO@guid.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'shell', 'main.js'), 'utf8');

// --- Extract _itemIdFromAttrs and adapt it to accept a plain attrs object ----
const match = source.match(/function _itemIdFromAttrs\([^)]*\)\s*\{[\s\S]*?\n  \}/);
assert(match, '_itemIdFromAttrs not found in main.js');

// The real fn calls el.getAttribute(name); give the sandbox a shim element that
// reads from a plain object so we can test the regex logic without a DOM.
const sandboxSrc =
  match[0].replace(/el\.getAttribute\(([^)]+)\)/g, 'el.getAttribute($1)') + '; _itemIdFromAttrs;';
const _itemIdFromAttrs = vm.runInNewContext(sandboxSrc, {});

function attrEl(attrs) {
  return { getAttribute: (name) => (name in attrs ? attrs[name] : null) };
}

// 1. row-SPO@{guid},{itemKey} -> the itemKey after the comma
assert.strictEqual(
  _itemIdFromAttrs(
    attrEl({
      'data-automationid':
        'row-SPO@3dd8961f-e488-4e60-8e11-a82d994e183d,01S2XP2ZTRZYVYAWBMMNFJYHOHDBMMCQWI',
    }),
  ),
  '01S2XP2ZTRZYVYAWBMMNFJYHOHDBMMCQWI',
  'must extract the itemKey after the comma',
);

// 2. Bare SPO@{guid} with NO comma -> empty (never the useless site guid)
assert.strictEqual(
  _itemIdFromAttrs(
    attrEl({
      'data-automationid': 'row-SPO@3dd8961f-e488-4e60-8e11-a82d994e183d',
    }),
  ),
  '',
  'a bare SPO@guid is a site id, not a file id — must return empty',
);

// 3. data-actions itemKey is preferred and clean
assert.strictEqual(
  _itemIdFromAttrs(
    attrEl({
      'data-actions': '{"itemKey":"01GOSXZLJDFFDNBF3T2RBLWSKOD5MMUC5G","x":1}',
    }),
  ),
  '01GOSXZLJDFFDNBF3T2RBLWSKOD5MMUC5G',
  'data-actions itemKey must be extracted',
);

// 4. No usable attrs -> empty (caller falls back to filename search)
assert.strictEqual(_itemIdFromAttrs(attrEl({})), '', 'no attrs -> empty');

// 5. direct data-item-key
assert.strictEqual(
  _itemIdFromAttrs(attrEl({ 'data-item-key': '01ABCDEFGHIJKLMNOPQRSTUVWX' })),
  '01ABCDEFGHIJKLMNOPQRSTUVWX',
  'direct data-item-key must be extracted',
);

// --- Guard: the old buggy regex must be gone ---------------------------------
assert(
  !/match\(\/\(SPO@\[\^\\s,\]\+\)\//.test(source),
  'the old /(SPO@[^\\s,]+)/ extractor (returns bare guid) must be removed',
);

// --- Guard: pinClickHandler must read the label/id stored at injection time --
assert(
  /btn\.dataset\.gatorLabel/.test(source) && /btn\.dataset\.gatorItemId/.test(source),
  'pinClickHandler must use data-gator-label / data-gator-item-id set at inject time',
);

// --- Guard: location.href bug fixed ------------------------------------------
assert(
  /web_url:\s*window\.location\.href/.test(source),
  'web_url must use window.location.href, not the undefined string.href',
);

console.log('onedrive_pin_id_extract.test.js: all assertions passed');
