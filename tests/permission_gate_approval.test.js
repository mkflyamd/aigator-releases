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

test('the global fetch wrapper refreshes a stale CSRF token and retries once', () => {
  const head = app.slice(0, app.indexOf('GATOR_WIDGET_MAX_H'));
  assert(/fetch\('\/api\/csrf'\)|orig\('\/api\/csrf'\)/.test(head));
  assert(/res\.status !== 403/.test(head));
  assert(/fresh === sentToken/.test(head), 'no retry when the token did not change');
});

test('a failed approval offers Ask again instead of a dead end', () => {
  const i = app.indexOf("'Ask again'");
  assert(i > 0);
  assert(/doSend\(retryPayload\)/.test(app.slice(i, i + 300)));
});
