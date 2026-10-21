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
const names = ['_parseNarrationApproval', '_approvalTrigger'];
const fns = vm.runInNewContext(`${names.map(extract).join('\n')}\n({ ${names.join(', ')} });`, {});
const plain = (v) => JSON.parse(JSON.stringify(v));

// parse: segments, flags, project id
let r = fns._parseNarrationApproval(
  'NARRATION_APPROVED:[{"text":"a"},{"text":"b"}] ADD_BACKGROUND_MUSIC:true PROJECT_ID:demo_20261019_101500',
);
assert.deepStrictEqual(plain(r), {
  segments: [{ text: 'a' }, { text: 'b' }],
  flags: { ADD_BACKGROUND_MUSIC: 'true' },
  projectId: 'demo_20261019_101500',
});
r = fns._parseNarrationApproval('NARRATION_APPROVED:[{"text":"a"}]');
assert.deepStrictEqual(plain(r), { segments: [{ text: 'a' }], flags: {}, projectId: null });

// brackets and flag-looking text inside a segment do not confuse the parser
r = fns._parseNarrationApproval(
  'NARRATION_APPROVED:[{"text":"use ] and PROJECT_ID:evil"}] PROJECT_ID:demo_1',
);
assert.strictEqual(r.segments[0].text, 'use ] and PROJECT_ID:evil');
assert.strictEqual(r.projectId, 'demo_1');

// parse failures
assert.throws(() => fns._parseNarrationApproval('NARRATION_APPROVED:no array here'));
assert.throws(() => fns._parseNarrationApproval('NARRATION_APPROVED:[]'));
assert.throws(() => fns._parseNarrationApproval('NARRATION_APPROVED:[{bad json}]'));

// trigger text carries the approval id
const approval = { approval_id: 'appr_2_0a1b2c3d', segment_count: 3 };
assert.strictEqual(
  fns._approvalTrigger(approval, {}),
  'Narration approved (3 segments, approval appr_2_0a1b2c3d). Please generate TTS and merge.',
);
assert.strictEqual(
  fns._approvalTrigger({ approval_id: 'appr_1_ffffffff', segment_count: 1 }, {}),
  'Narration approved (1 segment, approval appr_1_ffffffff). Please generate TTS and merge.',
);
assert.strictEqual(
  fns._approvalTrigger(approval, { ADD_BACKGROUND_MUSIC: 'true' }),
  'Narration approved (3 segments, approval appr_2_0a1b2c3d) with background music requested. Please generate TTS, add background music, and merge.',
);

// bridge source structure
const bridgeStart = source.indexOf("case 'gator:send-message'");
assert(bridgeStart > -1, 'bridge not found');
const bridge = source.slice(bridgeStart, bridgeStart + 3000);
assert(/_handleNarrationApproved\(_text, e\.source\)/.test(bridge), 'bridge must call the handler');
assert(
  !source.includes('/api/recorder/narration-approved'),
  'frontend must not call the legacy route',
);
assert(
  !/sessionStorage\.setItem\('gator_narration/.test(source),
  'no sessionStorage fallback writes',
);

const handlerMatch = source.match(
  /async function _handleNarrationApproved\([^)]*\)\s*\{[\s\S]*?\n\}/,
);
assert(handlerMatch, '_handleNarrationApproved not found');
const handler = handlerMatch[0];
assert(
  /await fetch\('\/api\/demo-projects\/' \+ encodeURIComponent\(projectId\) \+ '\/narration'/.test(
    handler,
  ),
);
assert(/if \(!res\.ok\)/.test(handler), 'handler must check res.ok');
assert(!/\.catch\(\(\) => \{\}\)/.test(handler), 'handler must not swallow errors');
const okIdx = handler.indexOf('if (!res.ok)');
const submitIdx = handler.indexOf('_submitApprovalTurn(');
assert(
  okIdx > -1 && submitIdx > okIdx,
  'chat turn is submitted only after the response is checked',
);
assert(
  /_replyApproval\(source, \{ ok: false/.test(handler),
  'failure must be reported to the widget',
);

console.log('narration_approval: all assertions passed');
