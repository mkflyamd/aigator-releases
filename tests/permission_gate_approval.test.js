// The runner permission card must not let the page forge a grant: the browser never sends a
// list of "approved" dependencies, it only reports the server-issued approval id.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { test } = require('node:test');

const app = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

test('chat requests never carry client-supplied approved_deps', () => {
  assert(!/approved_deps|_approvedSkillDeps/.test(app));
});

test('Allow on the permission card posts the server-issued approval id before resending', () => {
  const i = app.indexOf("fetch('/api/chat/approve-deps'");
  assert(i > 0, 'approve-deps is called');
  const call = app.slice(i, i + 400);
  assert(/method:\s*'POST'/.test(call));
  assert(/approval_id:\s*msg\.approval_id/.test(call));
});

test('a refused grant re-sends the saved request instead of dropping it', () => {
  const i = app.indexOf("fetch('/api/chat/approve-deps'");
  const handler = app.slice(i, i + 1400);
  assert(!/Send your message again/.test(app), 'no "retype your message" dead end');
  assert(!/if \(!grant \|\| !grant\.ok\)\s*\{[^}]*return;/.test(handler), 'failed grant must not return early');
  assert(/doSend\(resendPayload\)/.test(handler), 'saved payload is re-sent');
});
