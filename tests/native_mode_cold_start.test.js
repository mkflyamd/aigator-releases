// Right after a cold start /api/config has not answered yet. In the shell the native pane must be used
// then, not the classic one; an explicit classic setting and a plain browser still get classic.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'third-pane.js'),
  'utf8',
);
const helper = source.match(/\nfunction _nativeUnlessClassic\([^)]*\)\s*\{[\s\S]*?\n\}/);
assert(helper, '_nativeUnlessClassic not found in third-pane.js');

const APPS = ['outlook', 'onedrive', 'onenote', 'confluence', 'jira', 'github'];

function enabled(app, mode, inShell) {
  const fn = source.match(
    new RegExp(`\\nfunction _${app}NativeEnabled\\(\\)\\s*\\{[\\s\\S]*?\\n\\}`),
  );
  assert(fn, `_${app}NativeEnabled not found in third-pane.js`);
  const window = inShell ? { gatorShell: { isShell: true } } : {};
  return vm.runInNewContext(
    `${helper[0]}\nlet _${app}Mode = __mode;\n${fn[0]}\n_${app}NativeEnabled()`,
    {
      window,
      __mode: mode,
    },
  );
}

for (const app of APPS) {
  assert.strictEqual(enabled(app, null, true), true, `${app}: unknown mode in the shell is native`);
  assert.strictEqual(enabled(app, 'native', true), true, `${app}: native stays native`);
  assert.strictEqual(
    enabled(app, 'classic', true),
    false,
    `${app}: explicit classic stays classic`,
  );
  assert.strictEqual(
    enabled(app, null, false),
    false,
    `${app}: unknown mode in a browser is classic`,
  );
}

console.log('native_mode_cold_start: ok');
