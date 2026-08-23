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

// --- Extract _itemIdFromAttrs (+ its helper _isGraphItemId) and adapt them ---
// _itemIdFromAttrs calls _isGraphItemId, so both must be in the sandbox.
const itemIdMatch = source.match(/function _itemIdFromAttrs\([^)]*\)\s*\{[\s\S]*?\n  \}/);
assert(itemIdMatch, '_itemIdFromAttrs not found in main.js');
const isGraphMatch = source.match(/function _isGraphItemId\([^)]*\)\s*\{[\s\S]*?\n  \}/);
assert(isGraphMatch, '_isGraphItemId not found in main.js');

// The real fn calls el.getAttribute(name); give the sandbox a shim element that
// reads from a plain object so we can test the regex logic without a DOM.
const sandboxSrc =
  isGraphMatch[0] +
  '\n' +
  itemIdMatch[0].replace(/el\.getAttribute\(([^)]+)\)/g, 'el.getAttribute($1)') +
  '; _itemIdFromAttrs;';
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
// The pin ctx stores web_url via a shareUrl var that falls back to
// window.location.href (line: `if (!shareUrl) shareUrl = window.location.href;`).
// The old bug used the undefined `string.href`. Assert the fallback is present.
assert(
  /shareUrl\s*=\s*window\.location\.href/.test(source),
  'web_url fallback must use window.location.href, not the undefined string.href',
);

// --- Guard: the "New" badge bug must be fixed --------------------------------
// SharePoint renders a "New" glimmer badge (<i data-automationid="newSignal"
// title="New">) BEFORE the filename span for recently-added files. The old
// compound selector '[data-id="heroField"], [title]' matched that badge first
// (it's the first titled element in document order), so pins were labeled "New"
// instead of the real filename. The fix must:
//   1. Prefer [data-id="heroField"] explicitly (not via a compound selector).
//   2. Exclude the newSignal badge from the [title] fallback.
assert(
  !/querySelector\(\s*'\[data-id="heroField"\],\s*\[title\]'\s*\)/.test(source),
  'the compound selector [data-id="heroField"], [title] must be gone (it matched the "New" badge first)',
);
assert(
  /querySelector\(\s*'\[data-id="heroField"\]'\s*\)/.test(source),
  'heroField must be queried explicitly via [data-id="heroField"]',
);
assert(
  /not\(\[data-automationid="newSignal"\]\)/.test(source),
  'the [title] fallback must exclude the newSignal badge',
);

console.log('onedrive_pin_id_extract.test.js: all assertions passed');
