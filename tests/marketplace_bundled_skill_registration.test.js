// Post-milestone live-testing bug fix (2026-08-07 milestone — Plugin
// Marketplace A+B+E): installing a claude-plugins-official plugin BUNDLE
// (e.g. amd-skills, 7 skills) registered its skills correctly server-side
// (shared.load_installed_skill_prompts, via SKILL_PROMPTS) but never told
// the client-side SKILL_REGISTRY about them — unlike _install()'s generic
// single-skill path, which already calls window.registerUserSkill for its
// one skill.id. Net effect: a freshly installed plugin's skills were usable
// by the model (natural-language auto-activation goes through the backend)
// but invisible in the "/" compose-bar dropdown until a full page reload.
//
// _deriveBundledSkillLabel is the pure helper this fix added, extracted for
// unit-testability without a DOM (matches the established convention —
// _cardActionState/_findCollisionEntry/etc. in marketplace_verified_consent
// .test.js).

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'marketplace-pane.js'),
  'utf8',
);

function extractFn(name) {
  const re = new RegExp('function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n  \\}');
  const match = source.match(re);
  assert(match, name + ' not found in marketplace-pane.js');
  return vm.runInNewContext(match[0] + ';' + name + ';', {});
}

const _deriveBundledSkillLabel = extractFn('_deriveBundledSkillLabel');

// Namespaced sub-skill id (decision #3): "{plugin_id}__{subpath}" -> strip
// the prefix, replace separators with spaces, title-case.
assert.strictEqual(
  _deriveBundledSkillLabel('amd-skills__local-ai-use', 'amd-skills'),
  'Local Ai Use',
);
assert.strictEqual(
  _deriveBundledSkillLabel('amd-skills__serving-llms-on-instinct', 'amd-skills'),
  'Serving Llms On Instinct',
);

// A single-top-level-SKILL.md plugin's skill_ids entry IS the bare plugin_id
// (no "__" separator at all, per namespaced_skill_id's own bare-id case) —
// must pass through untouched rather than being mangled by the prefix strip.
assert.strictEqual(_deriveBundledSkillLabel('some-plugin', 'some-plugin'), 'Some Plugin');

// Underscore-separated subpath segments also get spaced/title-cased, not
// just hyphens.
assert.strictEqual(_deriveBundledSkillLabel('plugin__sub_skill_name', 'plugin'), 'Sub Skill Name');

console.log('marketplace_bundled_skill_registration: all assertions passed');
