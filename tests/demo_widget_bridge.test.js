const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function fn(name) {
  const m = source.match(new RegExp('(?:async )?function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}'));
  if (!m) throw new Error(name + ' not found in app.js');
  return m[0];
}
function line(re) {
  const m = source.match(re);
  if (!m) throw new Error(String(re) + ' not found in app.js');
  return m[0];
}

// The three cases sit after gator:recorder and delegate to gatorDemoBridge.
{
  const rec = source.indexOf("case 'gator:recorder':");
  assert(rec > 0, 'gator:recorder case found');
  for (const t of ['gator:demo-summary', 'gator:demo-progress', 'gator:demo-open-folder']) {
    const at = source.indexOf("case '" + t + "':");
    assert(at > rec, t + ' case follows gator:recorder');
    assert(source.slice(at, at + 160).includes('gatorDemoBridge(d, e)'), t + ' delegates to gatorDemoBridge');
  }
}

const frameWin = { name: 'widget' };
const otherWin = { name: 'other' };
const fetchCalls = [];
let routes = {};
const ctx = {
  document: { querySelectorAll: () => [{ contentWindow: frameWin }] },
  fetch: (url, opts) => {
    fetchCalls.push({ url, opts: opts ? JSON.parse(JSON.stringify(opts)) : null });
    const h = routes[url];
    if (!h) return Promise.reject(new Error('no route ' + url));
    return Promise.resolve(h(opts));
  },
};
const api = vm.runInNewContext(
  [
    line(/const GATOR_DEMO_ID_RE = [^\n]+;/),
    line(/const GATOR_DEMO_TARGETS = [^\n]+;/),
    fn('gatorWidgetFrameForSource'),
    fn('gatorDemoBridge'),
    '({ gatorWidgetFrameForSource, gatorDemoBridge })',
  ].join('\n'),
  ctx
);

const ok = (body) => ({ ok: true, status: 200, json: () => Promise.resolve(body) });
const bad = (status) => ({ ok: false, status, json: () => Promise.resolve({}) });

async function run(d, src) {
  const sent = [];
  fetchCalls.length = 0;
  const e = { source: { postMessage: (m, o) => sent.push(JSON.parse(JSON.stringify({ m, o }))) } };
  if (src === 'frame') e.source = Object.assign(frameWin, { postMessage: e.source.postMessage });
  else if (src === 'other') e.source = Object.assign(otherWin, { postMessage: e.source.postMessage });
  else if (src === null) e.source = null;
  await api.gatorDemoBridge(d, e);
  return sent;
}

(async () => {
  const SUMMARY = { path: 'C:\\p', final_dir: 'C:\\p\\final', final: 'C:\\p\\final\\AI_Gator_Demo.mp4', final_rel: 'final/AI_Gator_Demo.mp4', raw_rel: 'source/raw.mp4', source_count: 3, work_bytes: 5 };

  // summary and progress
  routes = { '/api/demo-projects/demo_1/summary': () => ok(SUMMARY) };
  let sent = await run({ type: 'gator:demo-summary', project_id: 'demo_1' }, 'frame');
  assert.deepStrictEqual(sent, [{ m: { type: 'gator:demo-summary-result', project_id: 'demo_1', ok: true, summary: SUMMARY }, o: '*' }]);

  routes = { '/api/demo-projects/demo_1/progress': () => ok({ state: 'running', approval_id: 'a1' }) };
  sent = await run({ type: 'gator:demo-progress', project_id: 'demo_1' }, 'frame');
  assert.deepStrictEqual(sent[0].m, { type: 'gator:demo-progress-result', project_id: 'demo_1', ok: true, progress: { state: 'running', approval_id: 'a1' } });

  routes = { '/api/demo-projects/demo_1/summary': () => bad(404) };
  sent = await run({ type: 'gator:demo-summary', project_id: 'demo_1' }, 'frame');
  assert.deepStrictEqual(sent[0].m, { type: 'gator:demo-summary-result', project_id: 'demo_1', ok: false, error: 'HTTP 404' });

  routes = {};
  sent = await run({ type: 'gator:demo-summary', project_id: 'demo_1' }, 'frame');
  assert.strictEqual(sent[0].m.ok, false, 'network failure becomes an error reply');

  // validation and origin
  routes = { '/api/demo-projects/demo_1/summary': () => ok(SUMMARY) };
  sent = await run({ type: 'gator:demo-summary', project_id: '../../etc' }, 'frame');
  assert.strictEqual(sent[0].m.ok, false);
  assert.strictEqual(fetchCalls.length, 0, 'invalid project id makes no request');
  sent = await run({ type: 'gator:demo-summary', project_id: 'demo_1' }, 'other');
  assert.strictEqual(sent.length, 0, 'message from a non-widget window is ignored');
  assert.strictEqual(fetchCalls.length, 0);
  sent = await run({ type: 'gator:demo-summary', project_id: 'demo_1' }, null);
  assert.strictEqual(fetchCalls.length, 0, 'message without a source is ignored');

  // open folder: the parent picks the path, the widget cannot
  const opens = [];
  routes = {
    '/api/demo-projects/demo_1/summary': () => ok(SUMMARY),
    '/api/open-file': (o) => { opens.push(JSON.parse(o.body)); return ok({ ok: true }); },
  };
  sent = await run({ type: 'gator:demo-open-folder', project_id: 'demo_1', target: 'final', path: 'C:\\Windows\\System32\\calc.exe' }, 'frame');
  assert.deepStrictEqual(opens[0], { path: 'C:\\p\\final\\AI_Gator_Demo.mp4', reveal: true }, 'final reveals the final video; widget path ignored');
  assert.deepStrictEqual(sent[0].m, { type: 'gator:demo-open-folder-result', project_id: 'demo_1', ok: true, message: '' });

  routes['/api/demo-projects/demo_1/summary'] = () => ok(Object.assign({}, SUMMARY, { final: null }));
  await run({ type: 'gator:demo-open-folder', project_id: 'demo_1', target: 'final' }, 'frame');
  assert.deepStrictEqual(opens[1], { path: 'C:\\p\\final', reveal: false }, 'no final video: open the final folder');

  routes['/api/demo-projects/demo_1/summary'] = () => ok(SUMMARY);
  await run({ type: 'gator:demo-open-folder', project_id: 'demo_1', target: 'project' }, 'frame');
  assert.deepStrictEqual(opens[2], { path: 'C:\\p', reveal: false });

  const before = opens.length;
  sent = await run({ type: 'gator:demo-open-folder', project_id: 'demo_1', target: 'C:\\Windows' }, 'frame');
  assert.strictEqual(sent[0].m.ok, false);
  assert.strictEqual(fetchCalls.length, 0, 'unknown target makes no request');
  assert.strictEqual(opens.length, before);

  routes['/api/open-file'] = () => ok({ ok: false, message: 'That path no longer exists: C:\\p' });
  sent = await run({ type: 'gator:demo-open-folder', project_id: 'demo_1', target: 'project' }, 'frame');
  assert.deepStrictEqual(sent[0].m, { type: 'gator:demo-open-folder-result', project_id: 'demo_1', ok: false, message: 'That path no longer exists: C:\\p' });

  console.log('demo_widget_bridge: PASS');
})().catch((err) => { console.error(err); process.exit(1); });
