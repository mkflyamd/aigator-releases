// Confluence card pin: space overview cards + top-right positioning regression.
//
// BUG 1: "Pick up where you left off" tiles include space overview cards (e.g.
// /wiki/spaces/AIG/overview) that have no /pages/ segment. scanPages only
// matched a[href*="/pages/"], so space overview cards never got a pin.
//
// BUG 2: Pins were injected INLINE (flex, prepended before text) on ALL links,
// including card anchors (tile overlays). This disrupted the card's layout and
// placed the pin at the left edge. The user wants pins in the TOP-RIGHT CORNER
// of the card anchor.
//
// FIX:
//   1. scanPages now also scans a[href*="/wiki/spaces/"][href*="/overview"] for
//      space overview cards, extracting the space key as the id.
//   2. isCardAnchor() distinguishes card tile anchors from text links.
//   3. injectCardPin() positions the pin absolutely (top:4px; right:4px) inside
//      the card anchor, while injectInlinePin() keeps the old inline approach
//      for text links.

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(path.join(__dirname, '..', 'shell', 'main.js'), 'utf8');
const sourceLF = source.replace(/\r\n/g, '\n');

// Isolate the Confluence pin module (between CF_PIN_MODULE and its end).
const cfStart = sourceLF.indexOf('var SVG_NS =');
assert(cfStart !== -1, 'Confluence pin module sentinel not found');
// The CF module ends at the closing of the IIFE + backtick (just before the
// confluenceView.webContents.on('dom-ready') call).
const cfEnd = sourceLF.indexOf("confluenceView.webContents.on('dom-ready'", cfStart);
assert(cfEnd !== -1, 'Confluence module end marker not found');
const cfModule = sourceLF.slice(cfStart, cfEnd);

// --- Guard: scanPages must scan space overview links ---
assert(
  /href\*="\/wiki\/spaces\/"\]\[href\*="\/overview"/.test(cfModule),
  'scanPages must scan a[href*="/wiki/spaces/"][href*="/overview"] for space overview cards',
);

// --- Guard: extractSpaceKey must be defined ---
assert(/function extractSpaceKey/.test(cfModule), 'Confluence module must define extractSpaceKey');

// --- Guard: isCardAnchor must be defined ---
assert(
  /function isCardAnchor/.test(cfModule),
  'Confluence module must define isCardAnchor to distinguish card tiles from text links',
);

// --- Guard: injectCardPin must position absolutely in the top-right corner ---
assert(/function injectCardPin/.test(cfModule), 'Confluence module must define injectCardPin');
assert(
  /btn\.style\.position\s*=\s*['"]absolute['"]/.test(cfModule) &&
    /btn\.style\.top\s*=\s*['"]4px['"]/.test(cfModule) &&
    /btn\.style\.right\s*=\s*['"]4px['"]/.test(cfModule),
  'injectCardPin must position the pin absolutely (top:4px; right:4px) in the top-right corner',
);

// --- Guard: injectInlinePin must be defined (for text links) ---
assert(
  /function injectInlinePin/.test(cfModule),
  'Confluence module must define injectInlinePin for text links',
);

// --- Guard: scanPages must use isCardAnchor to choose injection method ---
assert(
  /isCardAnchor\(link\)\s*\)\s*injectCardPin/.test(cfModule),
  'scanPages must use isCardAnchor to choose between injectCardPin and injectInlinePin',
);

// --- Guard: space pins must carry data-pin-space-key ---
assert(
  /data-pin-space-key/.test(cfModule),
  'space overview pins must carry data-pin-space-key for dedup and click context',
);

// --- Guard: space pins must set kind: 'space' ---
assert(
  /kind:\s*['"]space['"]/.test(cfModule),
  'space overview pins must set kind: "space" in __gatorPinCtx',
);

// --- Guard: extractPageId must handle draft links ---
// Draft links (/pages/resumedraft.action?draftId=<id>) have no numeric page ID
// after /pages/. Without handling, extractPageId returns '' and the card is
// skipped entirely (no pin). The fix returns 'draft:<id>'.
assert(
  /resumedraft/.test(cfModule) && /draftId/.test(cfModule),
  'extractPageId must handle draft links (resumedraft.action?draftId=)',
);

console.log('confluence_card_pin.test.js: all assertions passed');
