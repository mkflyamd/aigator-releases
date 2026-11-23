// The Browser rail item must open a shell pane like the other web panes, and ship on the
// default rail.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const read = (f) => fs.readFileSync(path.join(__dirname, '..', 'web', 'static', f), 'utf8');
const source = read('app.js');

const helper = source.match(/\nfunction _isShellWebPaneSkill\([^)]*\)\s*\{[\s\S]*?\n\}/);
assert(helper, '_isShellWebPaneSkill not found in app.js');
const isShellWebPane = vm.runInNewContext(helper[0] + '\n_isShellWebPaneSkill;', {});

assert.strictEqual(isShellWebPane({ _browserPane: true }), true, 'Browser is a shell web pane');
assert.strictEqual(isShellWebPane({ _customApp: true }), true, 'custom apps still are');
assert.strictEqual(isShellWebPane({ _googleService: true }), true, 'Google services still are');
assert.strictEqual(isShellWebPane({ id: 'jira' }), false, 'other skills are not');
assert.strictEqual(isShellWebPane(undefined), false, 'a missing skill is not');

const defaults = source.match(/const DEFAULT_DOCK_FAVS = \[([\s\S]*?)\];/);
assert(defaults, 'DEFAULT_DOCK_FAVS not found');
const ids = defaults[1].match(/'[^']+'/g).map((s) => s.slice(1, -1));
assert.deepStrictEqual(
  ids,
  ['email', 'calendar', 'teams', 'onedrive', 'confluence', 'jira', 'slack', 'code_agent', 'browser'],
  'default rail',
);

const tpIds = source.match(/const _TP_SKILL_IDS = new Set\(\[([\s\S]*?)\]\)/);
assert(tpIds && /'browser'/.test(tpIds[1]), 'browser must open the third pane');

const browserSkill = source.match(/\{\s*id: 'browser',[\s\S]*?_browserPane: true,/);
assert(browserSkill, "the 'browser' skill must carry _browserPane");

assert(
  /currentType === null \|\| currentType === app \|\|/.test(source),
  'closing Settings must restore the pane that was open, even when it is not a classic native type',
);

const thirdPane = read('third-pane.js');
assert(
  !/_customApp \|\| [\w\[\]\.]*_googleService/.test(thirdPane),
  'third-pane.js must use _isShellWebPaneSkill, not repeat the flag check',
);

console.log('rail_browser: ok');
