// Issue #86: Reply-All must NOT pre-fill the logged-in user's own address in CC.
// The dedup helper _replyAllCcRecipients(email, selfEmail) returns the CC list
// for Reply All, excluding the original sender AND the current user (self).

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'third-pane.js'),
  'utf8',
);

const match = source.match(
  /function _replyAllCcRecipients\(email, selfEmail\)\s*\{[\s\S]*?\n\}/,
);
assert(match, '_replyAllCcRecipients not found in third-pane.js');
const _replyAllCcRecipients = vm.runInNewContext(
  match[0] + '; _replyAllCcRecipients;',
  {},
);

const email = {
  from_email: 'boss@x.com',
  to: [
    { email: 'me@x.com', name: 'Me' },
    { email: 'peer@x.com', name: 'Peer' },
  ],
  cc: [{ email: 'cc1@x.com' }],
};

const out = _replyAllCcRecipients(email, 'me@x.com');
const emails = out.map((p) => p.email.toLowerCase());

assert(!emails.includes('me@x.com'), 'self must be excluded from CC');
assert(!emails.includes('boss@x.com'), 'original sender must be excluded from CC');
assert(emails.includes('peer@x.com'), 'other recipients must be kept');
assert(emails.includes('cc1@x.com'), 'other CC recipients must be kept');

// self exclusion is case-insensitive (token UPN casing may differ from header)
const out2 = _replyAllCcRecipients(email, 'ME@X.COM');
assert(
  !out2.map((p) => p.email.toLowerCase()).includes('me@x.com'),
  'self must be excluded case-insensitively',
);

// no selfEmail available -> still excludes sender, keeps the rest (incl. self)
const out3 = _replyAllCcRecipients(email, '');
assert(!out3.map((p) => p.email.toLowerCase()).includes('boss@x.com'));
assert(out3.map((p) => p.email.toLowerCase()).includes('peer@x.com'));

console.log('reply_all_self_cc: all assertions passed');
