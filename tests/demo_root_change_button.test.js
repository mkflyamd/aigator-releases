const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');
const fn = source.match(/async function demoRootRefresh\(\)\s*\{[\s\S]*?\n\}/);
assert(fn, 'demoRootRefresh not found in app.js');

async function run(gatorShell) {
  const label = { textContent: '' };
  const classes = new Set();
  const change = { classList: { toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)) } };
  const els = { 'demo-root-path': label, 'demo-root-change': change };
  const ctx = {
    document: { getElementById: (id) => els[id] || null },
    window: { gatorShell },
    fetch: async () => ({ json: async () => ({ default_root: 'C:\demo', is_default: true }) }),
  };
  vm.runInNewContext(`${fn[0]}\ndemoRootRefresh;`, ctx);
  await vm.runInNewContext(`${fn[0]}\ndemoRootRefresh();`, ctx);
  return { hidden: classes.has('hidden'), text: label.textContent };
}

(async () => {
  const web = await run(undefined);
  assert.strictEqual(web.hidden, true, 'Change is hidden when there is no native folder picker');
  assert.strictEqual(web.text, 'C:\demo (default)');
  const electron = await run({ pickDemoFolder: () => null });
  assert.strictEqual(
    electron.hidden,
    false,
    'Change is shown when the shell offers a folder picker',
  );
  console.log('demo_root_change_button: ok');
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
