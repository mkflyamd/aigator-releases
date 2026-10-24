const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function extract(name) {
  const m = source.match(new RegExp(`function ${name}\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}`));
  assert(m, `${name} not found in app.js`);
  return m[0];
}

// Built-in skills are excluded from the server-injected __USER_SKILLS__ list, so the "/" menu only
// shows them if they are in the static SKILL_REGISTRY literal.
const registrySrc = source.match(/const SKILL_REGISTRY = \[[\s\S]*?\n\];/);
assert(registrySrc, 'SKILL_REGISTRY literal not found in app.js');

const ctx = vm.runInNewContext(
  `const ICON = (id) => id;\n${registrySrc[0]}\n${extract('_fuzzyScore')}\n${extract('_fuzzyFilterSkills')}\n` +
    '({ SKILL_REGISTRY, _fuzzyFilterSkills });',
  {},
);

const entry = ctx.SKILL_REGISTRY.find((s) => s.id === 'gator-demo-recorder');
assert(entry, 'gator-demo-recorder is missing from SKILL_REGISTRY, so "/" never lists it');
assert.strictEqual(entry.label, 'Demo Recorder');
assert.strictEqual(entry.chipAlias, 'gator-demo-recorder', 'chip alias must equal the skill id');
assert.ok(!entry._customApp, 'slash menu hides _customApp entries');

const ids = new Set();
for (const s of ctx.SKILL_REGISTRY) {
  assert.ok(!ids.has(s.id), 'duplicate skill id in SKILL_REGISTRY: ' + s.id);
  ids.add(s.id);
}

for (const query of ['demo', 'recorder', 'gator-demo-recorder']) {
  const hits = ctx._fuzzyFilterSkills(
    ctx.SKILL_REGISTRY.filter((s) => !s._customApp),
    query,
  );
  assert.ok(
    hits.some((s) => s.id === 'gator-demo-recorder'),
    `typing "/${query}" lists the Demo Recorder`,
  );
}
assert.strictEqual(
  ctx._fuzzyFilterSkills(
    ctx.SKILL_REGISTRY.filter((s) => !s._customApp),
    'gator-demo-recorder',
  )[0].id,
  'gator-demo-recorder',
  'the full alias ranks the recorder first, ahead of the shorter "gator"',
);

console.log('demo_recorder_slash_entry: PASS');
