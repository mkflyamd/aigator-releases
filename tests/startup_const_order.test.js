const assert = require('assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

// The Init block runs selectSkill() synchronously, which re-renders saved chat history through
// renderMarkdown(). Anything that path reads must already be declared, or startup dies with a
// ReferenceError and the dock, settings and window drag never get wired.
const init = source.search(/^renderDock\(\);\r?\ninitChatResize\(\);/m);
assert.ok(init > 0, 'Init block not found');

for (const name of [
  'GATOR_WIDGET_MAX_H',
  'GATOR_WIDGET_STORE_PREFIX',
  'GATOR_WIDGET_STORE_LIMITS',
  'GATOR_RECORDER_ACTIONS',
  'GATOR_TTS_VOICE_RE',
  'GATOR_RECORDER_GRANT_IDLE_MS',
  'GATOR_RECORDER_CONSENT_MS',
  'gatorRecorderGrants',
  'gatorRecorderConsents',
]) {
  const decl = source.search(new RegExp('^const ' + name + ' =', 'm'));
  assert.ok(decl >= 0, name + ' is not declared');
  assert.ok(
    decl < init,
    name + ' is declared after the startup Init block (temporal dead zone at load)',
  );
}

console.log('startup_const_order: PASS');
