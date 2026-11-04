// Permission cards offer Always allow / Allow in this tab / Deny in that order, led by the button the server marks primary.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { test } = require('node:test');

const app = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');
const pick = (name) => {
  const m = app.match(new RegExp(String.raw`\nfunction ${name}\([^)]*\)\s*\{[\s\S]*?\n\}`));
  assert(m, `${name} not found in app.js`);
  return m[0];
};

const ctx = {};
vm.runInNewContext(
  `${pick('_scopeLabel')}\n${pick('_scopeButtonSpecs')}\n${pick('_scopeDoneNote')}\nthis.specs = _scopeButtonSpecs;\nthis.note = _scopeDoneNote;`,
  ctx,
);

const specsOf = (o) => JSON.parse(JSON.stringify(ctx.specs(o) || null));

test('low-risk card leads with Always allow and keeps the fixed order', () => {
  const specs = specsOf({ scopes: ['tab', 'always'], primary: 'always' });
  assert.deepStrictEqual(
    specs.map((s) => [s.scope, s.label, s.primary]),
    [
      ['always', 'Always allow', true],
      ['tab', 'Allow in this tab', false],
    ],
  );
});

test('high-risk card leads with Allow in this tab', () => {
  const specs = specsOf({ scopes: ['always', 'tab'], primary: 'tab' });
  assert.deepStrictEqual(
    specs.map((s) => s.primary),
    [false, true],
  );
});

test('a category that cannot be remembered shows no Always button', () => {
  const specs = specsOf({ scopes: ['tab'], primary: 'always' });
  assert.deepStrictEqual(
    specs.map((s) => s.scope),
    ['tab'],
  );
  assert.strictEqual(specs[0].primary, true);
});

test('a card with no scope options falls back to the plain Allow / Deny buttons', () => {
  assert.deepStrictEqual(specsOf(undefined), []);
  assert.deepStrictEqual(specsOf({ scopes: [] }), []);
  assert.deepStrictEqual(specsOf({ scopes: ['bogus'] }), []);
});

test('the done note says where a grant lives', () => {
  assert(/always allowed/.test(ctx.note('always')));
  assert(/this tab/.test(ctx.note('tab')));
});

test('the source card sends the chosen scope in the confirm body and puts Deny last', () => {
  const i = app.indexOf('function _showBrowserConfirmCard');
  const fn = app.slice(i, app.indexOf('/* ── Failover Consent Gate', i));
  assert(/JSON\.stringify\(\{ scope \}\)/.test(fn));
  assert(/btnWrap\.append\(\.\.\.allowBtns, cancelBtn\)/.test(fn));
});

test('the permission card posts the scope with the approval id', () => {
  const i = app.indexOf("fetch('/api/chat/approve-deps'");
  assert(/approval_id:\s*msg\.approval_id,\s*scope/.test(app.slice(i, i + 400)));
});

test('Settings offers only Ask / Always allow per category and a Remove all for rules', () => {
  const i = app.indexOf('function _initPermissionSettings');
  const fn = app.slice(i, app.indexOf('// Called from the shell toolbar', i));
  assert(/\['ask', 'Ask'\],\s*\['always', 'Always allow'\]/.test(fn));
  assert(/'\/api\/permissions\/mode'/.test(fn));
  assert(/DELETE', '\/api\/permissions\/rules'\)/.test(fn));
  assert(/_initPermissionSettings\(\);\r?\n\}/.test(app));
});

test('the failover card sends the chosen scope and puts Deny last', () => {
  const i = app.indexOf('function _showFailoverConfirmCard');
  const fn = app.slice(i, app.indexOf('/* ── Streaming state', i));
  assert(/_scopeButtonSpecs\(scopeOpts\)/.test(fn));
  assert(/JSON\.stringify\(\{ scope \}\)/.test(fn));
  assert(/btnWrap\.append\(\.\.\.allowBtns, cancelBtn\)/.test(fn));
});
