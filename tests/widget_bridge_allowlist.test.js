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
function block(re) {
  const m = source.match(re);
  if (!m) throw new Error(String(re) + ' not found in app.js');
  return m[0];
}
const plain = (x) => JSON.parse(JSON.stringify(x));

// Wiring: every message must come from a widget frame, and both new cases are routed.
{
  const listener = source.slice(source.indexOf("window.addEventListener('message', (e) => {"));
  const head = listener.slice(0, listener.indexOf("switch (d.type)"));
  assert.ok(head.includes('gatorWidgetFrameForSource(e.source)'), 'the bridge ignores messages from anything but a widget frame');
  assert.ok(/case 'gator:recorder':\s*gatorRecorderBridge\(d, e\);/.test(listener), 'gator:recorder goes through the allow-list');
  assert.ok(/case 'gator:tts-preview':\s*gatorTtsPreviewBridge\(d, e\);/.test(listener), 'gator:tts-preview is routed');
  const openEnded = source.split("fetch('/api/recorder/' + action").length - 1;
  assert.strictEqual(openEnded, 1, 'the only /api/recorder/ + action fetch is the allow-listed one');
  assert.ok(fn('gatorRecorderBridge').includes('GATOR_RECORDER_ACTIONS'), 'and it sits behind the allow-list');
}

const frameWin = { name: 'widget' };
const otherWin = { name: 'other' };
const calls = [];
let routes = {};
const ctx = {
  document: { querySelectorAll: () => [{ contentWindow: frameWin }] },
  fetch: (url, opts) => {
    calls.push({ url, method: (opts && opts.method) || 'GET', body: opts && opts.body ? JSON.parse(opts.body) : null, headers: opts && opts.headers });
    const h = routes[url];
    if (!h) return Promise.reject(new Error('no route ' + url));
    return Promise.resolve(h(opts));
  },
};
const api = vm.runInNewContext(
  [
    block(/const GATOR_RECORDER_ACTIONS = \{[\s\S]*?\n\};/),
    block(/const GATOR_TTS_VOICE_RE = [^\n]+;/),
    fn('gatorWidgetFrameForSource'),
    fn('gatorWidgetReply'),
    fn('gatorRecorderParams'),
    fn('gatorRecorderBridge'),
    fn('gatorTtsPreviewBridge'),
    '({ gatorRecorderBridge, gatorTtsPreviewBridge, gatorRecorderParams, GATOR_RECORDER_ACTIONS })',
  ].join('\n'),
  ctx
);

const json = (body, ok = true, status = 200) => ({ ok, status, json: () => Promise.resolve(body) });

async function run(bridge, d, src) {
  const sent = [];
  calls.length = 0;
  const post = (m, o) => sent.push(plain({ m, o }));
  let source = { postMessage: post };
  if (src === 'frame') source = Object.assign(frameWin, { postMessage: post });
  else if (src === 'other') source = Object.assign(otherWin, { postMessage: post });
  else if (src === null) source = null;
  await api[bridge](d, { source });
  return sent;
}

(async () => {
  // The allow-list is exactly the actions the recorder widget uses, with fixed methods.
  assert.deepStrictEqual(
    plain(Object.fromEntries(Object.entries(api.GATOR_RECORDER_ACTIONS).map(([k, v]) => [k, v.method]))),
    {
      status: 'GET', screens: 'GET',
      'select-screen': 'POST', 'pick-region': 'POST', start: 'POST',
      pause: 'POST', resume: 'POST', stop: 'POST',
    }
  );

  // A GET action: no body, reply carries the action and the request id.
  routes = { '/api/recorder/status': () => json({ status: 'idle' }) };
  let sent = await run('gatorRecorderBridge', { type: 'gator:recorder', action: 'status', rid: 7 }, 'frame');
  assert.deepStrictEqual(calls.map((c) => [c.method, c.url, c.body]), [['GET', '/api/recorder/status', null]]);
  assert.deepStrictEqual(sent, [{ m: { type: 'gator:recorder-result', action: 'status', rid: 7, data: { status: 'idle' } }, o: '*' }]);

  // A POST action: only the documented parameters are forwarded.
  routes = { '/api/recorder/start': () => json({ ok: true }) };
  sent = await run('gatorRecorderBridge', {
    type: 'gator:recorder', action: 'start', rid: 'r1',
    params: { screen_index: 1, force: true, crop_x: 10, crop_y: 20, crop_w: 300, crop_h: 200, path: 'C:\\x', cmd: 'calc' },
  }, 'frame');
  assert.deepStrictEqual(plain(calls[0].body), { screen_index: 1, force: true, crop_x: 10, crop_y: 20, crop_w: 300, crop_h: 200 });
  assert.strictEqual(calls[0].method, 'POST');
  assert.strictEqual(sent[0].m.rid, 'r1');

  // No params: POST without a body, as before.
  routes = { '/api/recorder/pause': () => json({ ok: true }) };
  await run('gatorRecorderBridge', { type: 'gator:recorder', action: 'pause', rid: 1 }, 'frame');
  assert.deepStrictEqual([calls[0].method, calls[0].body, calls[0].headers], ['POST', null, undefined]);

  // Wrongly typed parameters are refused without a request.
  for (const params of [{ screen_index: '1' }, { screen_index: NaN }, { force: 'yes' }, { crop_x: {} }]) {
    routes = { '/api/recorder/start': () => json({ ok: true }) };
    sent = await run('gatorRecorderBridge', { type: 'gator:recorder', action: 'start', rid: 1, params }, 'frame');
    assert.strictEqual(calls.length, 0, 'bad params ' + JSON.stringify(params) + ' make no request');
    assert.strictEqual(sent[0].m.data.ok, false);
  }

  // Anything off the list makes no request, including path tricks and server routes that exist.
  for (const action of ['notify', 'set-output', 'serve-file', 'debug', '../demo-projects/x', 'status/../start', 'start?x=1', '', null, 5, 'constructor', '__proto__', 'toString']) {
    routes = {};
    sent = await run('gatorRecorderBridge', { type: 'gator:recorder', action, rid: 1 }, 'frame');
    assert.strictEqual(calls.length, 0, 'action ' + JSON.stringify(action) + ' makes no request');
    assert.strictEqual(sent.length, 1);
    assert.strictEqual(sent[0].m.data.ok, false);
  }

  // Only a widget frame is served.
  routes = { '/api/recorder/status': () => json({}) };
  sent = await run('gatorRecorderBridge', { type: 'gator:recorder', action: 'status' }, 'other');
  assert.strictEqual(calls.length, 0);
  assert.strictEqual(sent.length, 0);
  await run('gatorRecorderBridge', { type: 'gator:recorder', action: 'status' }, null);
  assert.strictEqual(calls.length, 0);

  // Network failure becomes an error reply.
  routes = {};
  sent = await run('gatorRecorderBridge', { type: 'gator:recorder', action: 'status', rid: 3 }, 'frame');
  assert.strictEqual(sent[0].m.data.ok, false);
  assert.strictEqual(sent[0].m.rid, 3);

  // TTS preview: fixed model and endpoint; the widget supplies text and a voice name only.
  const BLOB = { size: 4, type: 'audio/mpeg' };
  routes = { '/api/recorder/tts-preview': () => ({ ok: true, status: 200, blob: () => Promise.resolve(BLOB) }) };
  sent = await run('gatorTtsPreviewBridge', {
    type: 'gator:tts-preview', rid: 9, text: '  Hello there  ', voice: 'af_heart', model: 'evil', lemonade_url: 'http://evil.example',
  }, 'frame');
  assert.deepStrictEqual(plain(calls[0].body), { text: 'Hello there', voice: 'af_heart', model: 'kokoro-v1' });
  assert.strictEqual(calls[0].method, 'POST');
  assert.strictEqual(sent[0].m.type, 'gator:tts-preview-result');
  assert.strictEqual(sent[0].m.rid, 9);
  assert.strictEqual(sent[0].m.ok, true);

  routes = { '/api/recorder/tts-preview': () => json({ error: 'Lemonade TTS is not running' }, false, 502) };
  sent = await run('gatorTtsPreviewBridge', { type: 'gator:tts-preview', rid: 2, text: 'hi', voice: 'af_heart' }, 'frame');
  assert.deepStrictEqual(sent[0].m, { type: 'gator:tts-preview-result', rid: 2, ok: false, error: 'Lemonade TTS is not running' });

  for (const bad of [
    { text: '', voice: 'af_heart' },
    { text: '   ', voice: 'af_heart' },
    { text: 5, voice: 'af_heart' },
    { text: 'hi', voice: '../x' },
    { text: 'hi', voice: 'a b' },
    { text: 'hi', voice: '' },
    { text: 'hi', voice: 'x'.repeat(41) },
    { text: 'hi' },
  ]) {
    routes = { '/api/recorder/tts-preview': () => json({}) };
    sent = await run('gatorTtsPreviewBridge', Object.assign({ type: 'gator:tts-preview', rid: 1 }, bad), 'frame');
    assert.strictEqual(calls.length, 0, 'bad preview request ' + JSON.stringify(bad) + ' makes no request');
    assert.strictEqual(sent[0].m.ok, false);
  }
  routes = { '/api/recorder/tts-preview': () => ({ ok: true, blob: () => Promise.resolve(BLOB) }) };
  await run('gatorTtsPreviewBridge', { type: 'gator:tts-preview', rid: 1, text: 'x'.repeat(500), voice: 'af_heart' }, 'frame');
  assert.strictEqual(calls[0].body.text.length, 300, 'long text is cut to the server limit');
  sent = await run('gatorTtsPreviewBridge', { type: 'gator:tts-preview', text: 'hi', voice: 'af_heart' }, 'other');
  assert.strictEqual(sent.length, 0);
  assert.strictEqual(calls.length, 0);

  console.log('widget_bridge_allowlist: PASS');
})().catch((err) => { console.error(err); process.exit(1); });
