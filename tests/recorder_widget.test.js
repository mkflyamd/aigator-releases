// The recorder widget template is extracted from SKILL.md and run against a stub DOM/fetch.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { test } = require('node:test');

const skill = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'skills', 'gator-demo-recorder', 'SKILL.md'),
  'utf8',
);

function widgetScript() {
  const start = skill.indexOf('```html:widget');
  assert(start >= 0, 'first html:widget block found');
  const end = skill.indexOf('\n```', start + 1);
  const m = skill.slice(start, end).match(/<script>([\s\S]*?)<\/script>/);
  assert(m, 'widget <script> found');
  return m[1];
}

// 'inline' is a sandboxed chat frame (opaque origin): backend calls go through the
// parent bridge. 'hud' is the Electron HUD window: parent === window, direct fetch.
function makeEnv(mode, routes) {
  const els = {};
  const el = (id) =>
    els[id] ||
    (els[id] = {
      id,
      textContent: '',
      className: '',
      innerHTML: '',
      style: {},
      disabled: false,
      checked: true,
      value: '0',
      onclick: null,
      appendChild() {},
    });
  const posted = [];
  const fetched = [];
  const bridged = [];
  const listeners = {};
  const answer = (action) =>
    routes[action] || (action === 'screens' ? { screens: [] } : { status: 'idle' });
  const ctx = {
    document: {
      getElementById: el,
      createElement: () => ({ appendChild() {}, value: '', textContent: '' }),
      addEventListener() {},
      visibilityState: 'visible',
    },
    setInterval() {},
    setTimeout() {},
    fetch(url, opts) {
      const action = url.split('/api/recorder/')[1];
      fetched.push({ action, body: opts && opts.body });
      return Promise.resolve({ json: () => Promise.resolve(answer(action)) });
    },
  };
  ctx.window = ctx;
  ctx.addEventListener = (type, fn) => {
    (listeners[type] = listeners[type] || []).push(fn);
  };
  if (mode === 'hud') {
    ctx.parent = ctx;
    ctx.postMessage = (m) => posted.push(m);
  } else {
    ctx.parent = {
      postMessage: (m) => {
        if (m.type !== 'gator:recorder') {
          posted.push(m);
          return;
        }
        bridged.push(m);
        fetched.push({ action: m.action, body: m.params ? JSON.stringify(m.params) : undefined });
        const data = answer(m.action);
        Promise.resolve().then(() =>
          (listeners.message || []).forEach((fn) =>
            fn({
              source: ctx.parent,
              data: { type: 'gator:recorder-result', action: m.action, rid: m.rid, data },
            }),
          ),
        );
      },
    };
  }
  vm.createContext(ctx);
  vm.runInContext(widgetScript(), ctx);
  const flush = () => new Promise((r) => setImmediate(r));
  return { ctx, el, posted, fetched, bridged, listeners, routes, flush };
}

const each = (name, fn) =>
  ['inline', 'hud'].forEach((mode) => test(name + ' [' + mode + ']', () => fn(mode)));

each(
  'a failed resume is shown and survives the status poll until the next action',
  async (mode) => {
    const { ctx, el, routes, flush } = makeEnv(mode, {
      resume: { ok: false, error: 'ffmpeg failed to restart — check ffmpeg_log.txt' },
    });
    await flush();
    ctx.render({ status: 'paused', elapsed: 5 });
    ctx.doResume();
    await flush();

    assert.strictEqual(el('status').className, 'status error');
    assert(el('status').textContent.includes('ffmpeg failed to restart'));

    ctx.render({ status: 'paused', elapsed: 5 });
    assert(
      el('status').textContent.includes('ffmpeg failed to restart'),
      'poll must not erase the error',
    );
    assert.strictEqual(el('btn-resume').style.display, '', 'Resume stays available for a retry');

    routes.resume = { ok: true, status: 'recording', elapsed: 5 };
    ctx.doResume();
    await flush();
    ctx.render({ status: 'recording', elapsed: 6 });
    assert.strictEqual(el('status').className, 'status recording');
  },
);

each('a failed pause is shown', async (mode) => {
  const { ctx, el, flush } = makeEnv(mode, { pause: { ok: false, error: 'Not recording' } });
  await flush();
  ctx.render({ status: 'recording', elapsed: 3 });
  ctx.doPause();
  await flush();

  assert.strictEqual(el('status').className, 'status error');
  assert(el('status').textContent.includes('Not recording'));
});

each(
  'stop success message carries the size, or no parentheses when it is unknown',
  async (mode) => {
    const cases = [
      [3145728, ' (3.0MB)', '✓ Saved 3.0MB'],
      [0, '', '✓ Saved'],
    ];
    for (const [bytes, sizePart, saved] of cases) {
      const { ctx, el, posted, flush } = makeEnv(mode, {
        stop: { ok: true, path: 'C:\\demos\\final.mp4', size_bytes: bytes },
      });
      await flush();
      ctx.doStop();
      await flush();

      assert.strictEqual(el('status').textContent, saved);
      assert.strictEqual(
        posted[0].text,
        'Recording complete. File: C:\\demos\\final.mp4' +
          sizePart +
          '. Please analyze it and draft a narration script.',
      );
      assert(!posted[0].text.includes('()'));
    }
  },
);

each(
  'a failed stop shows the error with the session folder and tells the chat nothing',
  async (mode) => {
    const { ctx, el, posted, fetched, flush } = makeEnv(mode, {
      stop: {
        ok: false,
        error: 'Could not join recording segments: bad',
        session_dir: 'C:\\demos\\demo_1',
      },
    });
    await flush();
    ctx.doStop();
    await flush();

    assert.strictEqual(el('status').className, 'status error');
    assert(el('status').textContent.includes('Stop error: Could not join recording segments'));
    assert(el('status').textContent.includes('C:\\demos\\demo_1'));
    assert.strictEqual(posted.length, 0);
    assert(!fetched.some((f) => f.action === 'notify'));
  },
);

test('inline: backend calls go through the parent bridge and never fetch', async () => {
  const { ctx, bridged, fetched, posted, flush } = makeEnv('inline', {
    stop: { ok: true, path: 'C:\\d\\f.mp4', size_bytes: 0 },
  });
  await flush();
  assert(
    bridged.some((m) => m.action === 'status'),
    'status is polled through the bridge',
  );
  ctx.doStop();
  await flush();
  assert(bridged.some((m) => m.action === 'stop'));
  assert(
    bridged.every((m) => typeof m.rid === 'number'),
    'every request carries a request id',
  );
  assert(!fetched.some((f) => f.action === 'notify'), 'no HUD notify from an inline frame');
  assert.strictEqual(posted.length, 1, 'the chat is told once, by postMessage');
});

test('inline: screen change and Record send only documented parameters', async () => {
  const { ctx, el, bridged, flush } = makeEnv('inline', {});
  await flush();
  el('sel-screen').value = '2';
  ctx.onScreenChange();
  ctx.doRecord();
  await flush();
  const sel = bridged.find((m) => m.action === 'select-screen');
  assert.deepStrictEqual(JSON.parse(JSON.stringify(sel.params)), { screen_index: 2 });
  const start = bridged.find((m) => m.action === 'start');
  assert.deepStrictEqual(JSON.parse(JSON.stringify(start.params)), {
    screen_index: 2,
    force: true,
  });
});

test('inline: replies are matched by request id and only accepted from the parent', async () => {
  const { ctx, el, listeners, flush } = makeEnv('inline', {
    pause: { ok: false, error: 'Not recording' },
  });
  await flush();
  ctx.render({ status: 'recording', elapsed: 3 });
  const fire = (ev) => listeners.message.forEach((fn) => fn(ev));
  fire({
    source: {},
    data: { type: 'gator:recorder-result', action: 'pause', rid: 1, data: { ok: true } },
  });
  fire({
    source: ctx.parent,
    data: { type: 'gator:recorder-result', action: 'pause', rid: 9999, data: { ok: true } },
  });
  ctx.doPause();
  await flush();
  assert(
    el('status').textContent.includes('Not recording'),
    'forged or stale replies do not settle a request',
  );
});

test('the widget never reads the parent page or the CSRF token', () => {
  const script = widgetScript();
  assert(!/window\.top|__CSRF_TOKEN__|parent\.document|parent\.window/.test(script));
});

test('Phase 2 analyzes the recording through analyze_video, not a runner script', () => {
  const phase2 = skill.slice(skill.indexOf('## Phase 2: Analyze'), skill.indexOf('## Phase 3'));
  assert(phase2.includes("describe_images(task='analyze_video'"));
  assert(!phase2.includes('subprocess.run'));
  assert(!phase2.includes('frame_%04d'));
  assert(!skill.includes('delete the `frames/`'));
});
