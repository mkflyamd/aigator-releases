const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const skill = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'skills', 'gator-demo-recorder', 'SKILL.md'),
  'utf8',
);
const blocks = [...skill.matchAll(/```html:widget\n([\s\S]*?)\n```/g)].map((m) => m[1]);
const widget = blocks.find((b) => b.includes('Demo Ready'));
assert.ok(widget, 'delivery widget found in SKILL.md');

function fn(name) {
  const m = widget.match(new RegExp('function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}'));
  if (!m) throw new Error(name + ' not found in delivery widget');
  return m[0];
}

// Markup
assert.ok(!/download/i.test(widget), 'no Download button, function or style');
assert.ok(!widget.includes('latest-output'), 'no latest-output');
assert.ok(!/fetch\(/.test(widget), 'widget makes no direct backend calls');
assert.ok(!widget.includes('/api/open-file'), 'widget never calls open-file itself');
assert.ok(
  !/window\.top|window\.parent|__CSRF_TOKEN__/.test(widget),
  'widget does not reach into the parent',
);
assert.ok(widget.includes("'gator:demo-summary'"), 'asks the parent for the summary');
assert.ok(widget.includes("'gator:demo-open-folder'"), 'asks the parent to open folders');
assert.ok(widget.includes('📁 Open final folder'), 'Open final folder button');
assert.ok(widget.includes('Open project folder'), 'Open project folder button');
assert.ok(widget.includes("var _PROJECT_ID = 'PROJECT_ID_PLACEHOLDER';"), 'project id placeholder');
assert.ok(
  skill.includes('replacing only `PROJECT_ID_PLACEHOLDER`'),
  'prose names the one placeholder',
);

// Pinned sends: every gator:send-message carries pin_skill and project_id.
{
  const idxs = [...widget.matchAll(/type:'gator:send-message'/g)].map((m) => m.index);
  assert.ok(idxs.length >= 2, 'editNarration and cleanup both send');
  for (const i of idxs) {
    const tail = widget.slice(i, i + 260);
    assert.ok(
      tail.includes("pin_skill:'gator-demo-recorder'"),
      'pin_skill present: ' + tail.slice(0, 80),
    );
    assert.ok(tail.includes('project_id:_PROJECT_ID'), 'project_id present: ' + tail.slice(0, 80));
  }
}

// Pure helpers
const code = [
  "var _pid='demo_1';",
  fn('formatBytes'),
  fn('summaryLine'),
  fn('setOpenStatus'),
  fn('requestOpen'),
  fn('openFinal'),
  fn('openProject'),
  fn('handleOpenResult'),
  '({ formatBytes, summaryLine, openFinal, openProject, handleOpenResult, setPid: function(p){ _pid=p; } })',
].join('\n');

const posted = [];
const statusEl = { textContent: '' };
const ctx = {
  parent: { postMessage: (m, origin) => posted.push(JSON.parse(JSON.stringify({ m, origin }))) },
  document: { getElementById: () => statusEl },
};
const api = vm.runInNewContext(code, ctx);

const MB = 1048576;
assert.strictEqual(api.formatBytes(0), '0 B');
assert.strictEqual(api.formatBytes(1023), '1023 B');
assert.strictEqual(api.formatBytes(1536), '2 KB');
assert.strictEqual(api.formatBytes(280 * MB), '280 MB');
assert.strictEqual(api.formatBytes(1.5 * 1024 * MB), '1.5 GB');
assert.strictEqual(
  api.summaryLine({ final_rel: 'final/AI_Gator_Demo.mp4', source_count: 3, work_bytes: 280 * MB }),
  'Final: final/AI_Gator_Demo.mp4 · Sources: 3 · Working files: 280 MB',
);
assert.strictEqual(
  api.summaryLine({ final_rel: null, source_count: 0, work_bytes: 0 }),
  'Final: none · Sources: 0 · Working files: 0 B',
);

// Each button posts one named action with fixed parameters and no path.
api.openFinal();
assert.deepStrictEqual(posted[0], {
  m: { type: 'gator:demo-open-folder', project_id: 'demo_1', target: 'final' },
  origin: '*',
});
api.openProject();
assert.deepStrictEqual(posted[1], {
  m: { type: 'gator:demo-open-folder', project_id: 'demo_1', target: 'project' },
  origin: '*',
});

// The parent's reply drives the status line; replies for other projects are ignored.
statusEl.textContent = '';
api.handleOpenResult({
  type: 'gator:demo-open-folder-result',
  project_id: 'demo_1',
  ok: false,
  message: 'That path no longer exists: C:\\p',
});
assert.strictEqual(statusEl.textContent, 'That path no longer exists: C:\\p');
api.handleOpenResult({ type: 'gator:demo-open-folder-result', project_id: 'demo_1', ok: false });
assert.strictEqual(statusEl.textContent, 'Could not open the folder.');
api.handleOpenResult({ type: 'gator:demo-open-folder-result', project_id: 'demo_1', ok: true });
assert.strictEqual(statusEl.textContent, '');
statusEl.textContent = 'keep';
api.handleOpenResult({
  type: 'gator:demo-open-folder-result',
  project_id: 'demo_9',
  ok: false,
  message: 'other',
});
assert.strictEqual(statusEl.textContent, 'keep', 'reply for another project is ignored');

// No project id: nothing is posted.
api.setPid('');
const before = posted.length;
api.openFinal();
api.openProject();
assert.strictEqual(posted.length, before, 'no request without a project id');

console.log('demo_ready_widget: PASS');
