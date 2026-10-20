// The recorder widget template is extracted from SKILL.md and run against a stub DOM/fetch.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { test } = require('node:test');

const skill = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'skills', 'gator-demo-recorder', 'SKILL.md'), 'utf8');

function widgetScript() {
  const start = skill.indexOf('```html:widget');
  assert(start >= 0, 'first html:widget block found');
  const end = skill.indexOf('\n```', start + 1);
  const m = skill.slice(start, end).match(/<script>([\s\S]*?)<\/script>/);
  assert(m, 'widget <script> found');
  return m[1];
}

function makeEnv(routes) {
  const els = {};
  const el = (id) => els[id] || (els[id] = {
    id, textContent: '', className: '', innerHTML: '', style: {}, disabled: false,
    checked: true, value: '0', onclick: null, appendChild() {},
  });
  const posted = [];
  const fetched = [];
  const ctx = {
    document: {
      getElementById: el,
      createElement: () => ({ appendChild() {}, value: '', textContent: '' }),
      addEventListener() {},
      visibilityState: 'visible',
    },
    setInterval() {},
    fetch(url, opts) {
      const action = url.split('/api/recorder/')[1];
      fetched.push({ action, body: opts && opts.body });
      const body = routes[action] || (action === 'screens' ? { screens: [] } : { status: 'idle' });
      return Promise.resolve({ json: () => Promise.resolve(body) });
    },
    parent: { postMessage: (m) => posted.push(m) },
  };
  ctx.window = ctx;
  ctx.addEventListener = () => {};
  vm.createContext(ctx);
  vm.runInContext(widgetScript(), ctx);
  const flush = () => new Promise((r) => setImmediate(r));
  return { ctx, el, posted, fetched, routes, flush };
}

test('a failed resume is shown and survives the status poll until the next action', async () => {
  const { ctx, el, routes, flush } = makeEnv({
    resume: { ok: false, error: 'ffmpeg failed to restart — check ffmpeg_log.txt' },
  });
  await flush();
  ctx.render({ status: 'paused', elapsed: 5 });
  ctx.doResume();
  await flush();

  assert.strictEqual(el('status').className, 'status error');
  assert(el('status').textContent.includes('ffmpeg failed to restart'));

  ctx.render({ status: 'paused', elapsed: 5 });
  assert(el('status').textContent.includes('ffmpeg failed to restart'), 'poll must not erase the error');
  assert.strictEqual(el('btn-resume').style.display, '', 'Resume stays available for a retry');

  routes.resume = { ok: true, status: 'recording', elapsed: 5 };
  ctx.doResume();
  await flush();
  ctx.render({ status: 'recording', elapsed: 6 });
  assert.strictEqual(el('status').className, 'status recording');
});

test('a failed pause is shown', async () => {
  const { ctx, el, flush } = makeEnv({ pause: { ok: false, error: 'Not recording' } });
  await flush();
  ctx.render({ status: 'recording', elapsed: 3 });
  ctx.doPause();
  await flush();

  assert.strictEqual(el('status').className, 'status error');
  assert(el('status').textContent.includes('Not recording'));
});

test('stop success message carries the size, or no parentheses when it is unknown', async () => {
  const cases = [
    [3145728, ' (3.0MB)', '✓ Saved 3.0MB'],
    [0, '', '✓ Saved'],
  ];
  for (const [bytes, sizePart, saved] of cases) {
    const { ctx, el, posted, flush } = makeEnv({
      stop: { ok: true, path: 'C:\\demos\\final.mp4', size_bytes: bytes },
    });
    await flush();
    ctx.doStop();
    await flush();

    assert.strictEqual(el('status').textContent, saved);
    assert.strictEqual(
      posted[0].text,
      'Recording complete. File: C:\\demos\\final.mp4' + sizePart +
        '. Please analyze it and draft a narration script.');
    assert(!posted[0].text.includes('()'));
  }
});

test('a failed stop shows the error with the session folder and tells the chat nothing', async () => {
  const { ctx, el, posted, fetched, flush } = makeEnv({
    stop: { ok: false, error: 'Could not join recording segments: bad', session_dir: 'C:\\demos\\demo_1' },
  });
  await flush();
  ctx.doStop();
  await flush();

  assert.strictEqual(el('status').className, 'status error');
  assert(el('status').textContent.includes('Stop error: Could not join recording segments'));
  assert(el('status').textContent.includes('C:\\demos\\demo_1'));
  assert.strictEqual(posted.length, 0);
  assert(!fetched.some((f) => f.action === 'notify'));
});

test('Phase 2 analyzes the recording through analyze_video, not a runner script', () => {
  const phase2 = skill.slice(skill.indexOf('## Phase 2: Analyze'), skill.indexOf('## Phase 3'));
  assert(phase2.includes("describe_images(task='analyze_video'"));
  assert(!phase2.includes('subprocess.run'));
  assert(!phase2.includes('frame_%04d'));
  assert(!skill.includes('delete the `frames/`'));
});
