const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const skill = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'skills', 'gator-demo-recorder', 'SKILL.md'),
  'utf8'
);
const blocks = [...skill.matchAll(/```html:widget\n([\s\S]*?)\n```/g)].map((m) => m[1]);
const editor = blocks.find((b) => b.includes('Edit Narration Script'));
assert.ok(editor, 'narration editor widget found in SKILL.md');

function fn(name) {
  const m = editor.match(new RegExp('function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}'));
  if (!m) throw new Error(name + ' not found in editor widget');
  return m[0];
}
const plain = (x) => JSON.parse(JSON.stringify(x));

// pauseValue / segOut
{
  const { pauseValue, segOut } = vm.runInNewContext(
    fn('pauseValue') + '\n' + fn('segOut') + '\n({ pauseValue, segOut })'
  );
  assert.strictEqual(pauseValue('1.5'), 1.5);
  assert.strictEqual(pauseValue('abc'), 0);
  assert.strictEqual(pauseValue(null), 0);
  assert.strictEqual(pauseValue(undefined), 0);
  assert.strictEqual(pauseValue(''), 0);
  assert.strictEqual(pauseValue(-3), 0);
  assert.strictEqual(pauseValue(99), 10);
  assert.strictEqual(pauseValue(1.26), 1.3);
  assert.deepStrictEqual(
    plain(segOut({ start_at: 4 }, 'hi', 'af_heart', 1, '2')),
    { start_at: 4, text: 'hi', voice: 'af_heart', speed: 1, pause_after: 2 }
  );
  assert.deepStrictEqual(
    plain(segOut({ start: 5 }, 'x', 'af_nova', 1.1, '')),
    { start_at: 5, text: 'x', voice: 'af_nova', speed: 1.1, pause_after: 0 }
  );
}

// Template wiring
assert.ok(editor.includes('Pause after (s)'), 'pause label');
assert.ok(editor.includes('id="pacing-tip"'), 'tooltip id');
assert.ok(editor.includes('Use commas and periods for natural breaths'), 'tooltip text');
assert.ok(!editor.includes('[pause:'), 'no [pause:...] syntax advertised');
assert.ok(editor.includes("'pa'+i"), 'per-segment pause input id');
assert.ok(
  editor.includes("segOut(s, document.getElementById('s'+i).value, voice, speed, document.getElementById('pa'+i).value)"),
  'approve() goes through segOut'
);

console.log('narration_editor_widget: PASS');
