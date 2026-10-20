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
assert.ok(/\.tip\{[^}]*left:0[^}]*\}/.test(editor) && !/\.tip\{[^}]*right:0/.test(editor), 'tooltip anchors left so it is not clipped by the frame');
assert.ok(editor.includes("'pa'+i"), 'per-segment pause input id');
assert.ok(
  editor.includes("segOut(s, document.getElementById('s'+i).value, voice, speed, document.getElementById('pa'+i).value)"),
  'approve() goes through segOut'
);

// Precondition from SP2
assert.ok(editor.includes("var _PROJECT_ID = 'PROJECT_ID_PLACEHOLDER'"), 'SP2 must be merged: editor needs _PROJECT_ID');
assert.ok(editor.includes('id="btn-approve"'), 'SP2 must be merged: Approve button needs id="btn-approve"');

// progressView
{
  const { progressView } = vm.runInNewContext(
    fn('progressView') + '\n({ progressView })'
  );

  const SINCE = 1000000;
  const rec = (o) => Object.assign({ approval_id: 'a1', updated_at: SINCE / 1000 + 5 }, o);
  const view = (p, waited) => plain(progressView(p, 'a1', waited === undefined ? 1000 : waited, SINCE));
  const WAITING = { text: 'Waiting for generation to start…', color: '#6b8db5', stop: false, retry: false };
  const STALLED = {
    text: 'Generation has not started yet. Check that the AI Gator agent is still working, or click Approve to retry.',
    color: '#f87171', stop: true, retry: true,
  };

  assert.deepStrictEqual(view({ state: 'none' }), WAITING);
  assert.deepStrictEqual(view(null), WAITING);
  assert.deepStrictEqual(
    view(rec({ state: 'running', message: 'Generating speech 2 of 5' })),
    { text: 'Generating speech 2 of 5', color: '#f97316', stop: false, retry: false }
  );
  assert.deepStrictEqual(
    view(rec({ state: 'done' })),
    { text: 'Done — your demo video is ready.', color: '#4ade80', stop: true, retry: false }
  );
  assert.deepStrictEqual(
    view(rec({ state: 'failed', error: 'ffmpeg exploded' })),
    { text: 'Generation failed: ffmpeg exploded', color: '#f87171', stop: true, retry: true }
  );
  assert.deepStrictEqual(view(rec({ state: 'done', updated_at: SINCE / 1000 - 1 })), WAITING, 'stale same-id record');
  assert.deepStrictEqual(view(rec({ state: 'done', approval_id: 'a2' })), WAITING, 'other approval');
  assert.deepStrictEqual(view({ state: 'none' }, 120000), STALLED);
  assert.deepStrictEqual(view(rec({ state: 'running', approval_id: 'a2' }), 130000), STALLED, 'other id does not mask a stall');
  assert.strictEqual(view(rec({ state: 'done' }), 130000).text, 'Done — your demo video is ready.', 'a real result wins over the stall timer');
}

// Template and SKILL.md wiring
assert.ok(editor.includes('id="merge-status"'), 'merge status element');
assert.ok(editor.includes('gator:narration-approval-result'), 'listens for the approval reply');
assert.ok(editor.includes("'gator:demo-summary'"), 'asks the parent for the project summary');
assert.ok(editor.includes("'gator:demo-progress'"), 'asks the parent for merge progress');
assert.ok(editor.includes('gator:demo-summary-result') && editor.includes('gator:demo-progress-result'), 'listens for the parent replies');
assert.ok(!/fetch\([^)]*demo-projects/.test(editor), 'no direct demo-project backend calls from the editor');
assert.strictEqual((editor.match(/fetch\(/g) || []).length, 2, 'only the two pre-existing TTS preview fetches remain');
assert.ok(!editor.includes('latest-output'), 'editor no longer uses latest-output');
assert.ok(!editor.includes('/api/demo-projects/active'), 'editor no longer uses the active-project route');
assert.ok(
  /if\(v\.retry\)\{[^}]*_approving=false/.test(editor),
  'retry re-arms approve(), not just the button'
);
assert.ok(
  /"--progress-file", str\(PROJECT_DIR \/ "work" \/ "logs" \/ "merge_progress\.json"\),\s*"--approval-id", verdict\["approval_id"\]/.test(skill),
  'Phase 4 passes the progress flags'
);

console.log('narration_editor_widget: PASS');
