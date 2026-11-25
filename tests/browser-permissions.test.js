const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');

const { applyBrowserPermissions } = require('../shell/browser-permissions');

function fakeSession() {
  const s = {};
  s.setPermissionRequestHandler = (fn) => (s.request = fn);
  s.setPermissionCheckHandler = (fn) => (s.check = fn);
  s.setDisplayMediaRequestHandler = (fn, opts) => {
    s.display = fn;
    s.displayOpts = opts;
  };
  return s;
}

const PERMISSIONS = [
  'media',
  'display-capture',
  'clipboard-read',
  'clipboard-sanitized-write',
  'notifications',
  'local-network-access',
  'idle-detection',
  'geolocation',
];

test('the Browser pane denies every permission request and check', () => {
  const ses = fakeSession();
  applyBrowserPermissions(ses);
  for (const p of PERMISSIONS) {
    let granted;
    ses.request(null, p, (ok) => (granted = ok), { requestingUrl: 'https://app.slack.com/' });
    assert.strictEqual(granted, false, `request ${p}`);
    assert.strictEqual(ses.check(null, p, 'https://teams.microsoft.com'), false, `check ${p}`);
  }
});

test('the Browser pane refuses screen capture without a system picker', () => {
  const ses = fakeSession();
  applyBrowserPermissions(ses);
  let result;
  ses.display({}, (r) => (result = r));
  assert.deepStrictEqual(result, {});
  assert.strictEqual(ses.displayOpts, undefined);
});

test('main.js gives only the Browser pane the deny-all policy', () => {
  const src = fs.readFileSync(path.join(__dirname, '../shell/main.js'), 'utf8');
  assert.match(
    src,
    /if \(id === BROWSER_PANE_ID\) applyBrowserPermissions\(ses\);\s*else applyMediaPermissions\(ses\);/,
  );
});

test('popup windows opened from a pane are sandboxed with isolation and no node', () => {
  const src = fs.readFileSync(path.join(__dirname, '../shell/navigation-policy.js'), 'utf8');
  const blocks = src.match(/session: parentSession,[^}]*\}/g) || [];
  assert.ok(blocks.length >= 3);
  for (const b of blocks) {
    assert.match(b, /contextIsolation: true/);
    assert.match(b, /nodeIntegration: false/);
    assert.match(b, /sandbox: true/);
  }
});
