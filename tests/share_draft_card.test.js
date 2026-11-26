// The share email reuses the standard draft card, locked to the exact text the server holds.

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');
const pane = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'marketplace-pane.js'),
  'utf8',
);

assert(
  source.includes('window._injectDraftApprovalCard = _injectDraftApprovalCard;'),
  'the card is exported for the share modal',
);
assert(
  /\.\.\.\(data\.locked\s*\?\s*\{\s*customBody:[\s\S]*?viewAvailable: false/.test(source),
  'a locked email draft shows its text read-only and offers no Outlook hand-off',
);
assert(
  /!data\.locked\s*&&\s*Array\.isArray\(data\.to_people\)/.test(source),
  'a locked draft has no editable recipients',
);
assert(
  source.includes("type === 'email-send' && !data.locked"),
  'a locked draft has no editable subject',
);
assert(
  /showDraftCard: \(type, data\) => window\._injectDraftApprovalCard\(type, data\)/.test(pane),
  'the share modal is given the card',
);
