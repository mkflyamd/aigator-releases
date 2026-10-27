const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { test } = require('node:test');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'marketplace-pane.js'),
  'utf8',
);

test('Mine skill rows offer Share and it downloads the exported .skill file', () => {
  assert(source.includes("shareBtn.dataset.action = 'share-mine'"));
  assert(source.includes("action === 'share-mine'"));
  const start = source.indexOf('async function _shareMineSkill(');
  assert(start > 0, 'share handler exists');
  const body = source.slice(start, source.indexOf('async function _editMineSkill(', start));
  assert(body.includes("'/api/marketplace/export/'"));
  assert(body.includes("a.download = skillId + '.skill'"));
});

test('Share is only added inside the Mine branch of the installed list', () => {
  const at = source.indexOf("shareBtn.dataset.action = 'share-mine'");
  const branch = source.lastIndexOf("if (skill.tier === 'Mine') {", at);
  const removeBtn = source.indexOf('const removeBtn', branch);
  assert(branch > 0 && at < removeBtn, 'share button sits in the tier === Mine block');
});
