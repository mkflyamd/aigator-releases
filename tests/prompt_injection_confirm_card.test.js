// The in-loop confirm card serves two callers: the browser gate (no title: keeps
// "Open browser?" / Allow / Cancel) and the data-source gate (title and labels given).
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');
const match = source.match(/function _confirmCardText\([^)]*\)\s*\{[\s\S]*?\n\}/);
assert(match, '_confirmCardText not found in app.js');
const _confirmCardText = vm.runInNewContext(match[0] + ';_confirmCardText;', {});

{
  const t = _confirmCardText({});
  assert.strictEqual(t.title, 'Open browser?');
  assert.strictEqual(t.allowLabel, 'Allow');
  assert.strictEqual(t.denyLabel, 'Cancel');
  assert.strictEqual(t.isSource, false);
}
{
  const t = _confirmCardText({ title: 'Allow access to Jira?', allow_label: 'Allow for this tab', deny_label: 'Deny' });
  assert.strictEqual(t.title, 'Allow access to Jira?');
  assert.strictEqual(t.allowLabel, 'Allow for this tab');
  assert.strictEqual(t.denyLabel, 'Deny');
  assert.strictEqual(t.isSource, true);
}
assert(/source-confirm-\$\{confirm_id\}/.test(source), 'source cards must get a per-request id so two pending cards do not replace each other');
console.log('ok');
