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

// Built-in skills are not in the server-injected __USER_SKILLS__ list, so "/" only lists them
// if they are in the static SKILL_REGISTRY literal.
const registrySrc = source.match(/const SKILL_REGISTRY = \[[\s\S]*?\n\];/);
assert(registrySrc, 'SKILL_REGISTRY literal not found in app.js');

const ctx = vm.runInNewContext(
  `const ICON = (id) => id;\n${registrySrc[0]}\n${extract('_fuzzyScore')}\n${extract('_fuzzyFilterSkills')}\n` +
    '({ SKILL_REGISTRY, _fuzzyFilterSkills });',
  {},
);

const entry = ctx.SKILL_REGISTRY.find((s) => s.id === 'skill_manager');
assert(entry, 'skill_manager is missing from SKILL_REGISTRY, so "/" never lists it');
assert.strictEqual(entry.label, 'Skill Manager');
assert.strictEqual(entry.chipAlias, 'skill_manager', 'chip alias must equal the skill id');
assert.ok(!entry._customApp, 'slash menu hides _customApp entries');

for (const query of ['skill', 'manager', 'skill_manager']) {
  const hits = ctx._fuzzyFilterSkills(
    ctx.SKILL_REGISTRY.filter((s) => !s._customApp),
    query,
  );
  assert.ok(
    hits.some((s) => s.id === 'skill_manager'),
    `typing "/${query}" lists the Skill Manager`,
  );
}

console.log('skill_manager_slash_entry: PASS');
