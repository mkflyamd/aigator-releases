const test = require('node:test');
const assert = require('node:assert');
const { createPaneTrace, summarize } = require('../shell/pane-trace');

function makeTrace(extra = {}) {
  const clock = { t: 0 };
  const lines = [];
  const timers = [];
  const trace = createPaneTrace({
    enabled: true,
    now: () => clock.t,
    log: (line) => lines.push(line),
    schedule: (fn) => {
      timers.push(fn);
      return {};
    },
    ...extra,
  });
  return { trace, clock, lines, timers };
}

test('disabled trace records and logs nothing', () => {
  const lines = [];
  const trace = createPaneTrace({ enabled: false, log: (l) => lines.push(l) });
  trace.click('teams', 1000);
  trace.mark('frame');
  assert.strictEqual(trace.enabled, false);
  assert.strictEqual(lines.length, 0);
});

test('a click summarizes timings, passes and hides', () => {
  const { trace, clock, lines } = makeTrace();
  trace.click('teams', 1000);
  clock.t = 1004;
  trace.mark('ipc-hide', { app: 'outlook', noop: true });
  clock.t = 1006;
  trace.mark('ipc-show', { app: 'teams' });
  clock.t = 1010;
  trace.mark('layout', { active: 'teams' });
  clock.t = 1030;
  trace.mark('frame');
  assert.strictEqual(lines.length, 1);
  assert.ok(lines[0].startsWith('[pane-trace] '));
  assert.deepStrictEqual(JSON.parse(lines[0].slice('[pane-trace] '.length)), {
    app: 'teams',
    clickToShowIpcMs: 6,
    clickToLayoutMs: 10,
    clickToFrameMs: 30,
    layoutPasses: 1,
    nullActivePasses: 0,
    hideIpcs: 1,
    noopHideIpcs: 1,
  });
});

test('layout passes with no active app are counted', () => {
  const rec = {
    app: 'slack',
    t0: 0,
    marks: [
      { event: 'layout', t: 5, detail: { active: null } },
      { event: 'layout', t: 9, detail: { active: 'slack' } },
    ],
  };
  const s = summarize(rec);
  assert.strictEqual(s.layoutPasses, 2);
  assert.strictEqual(s.nullActivePasses, 1);
  assert.strictEqual(s.clickToFrameMs, null);
  assert.strictEqual(s.clickToShowIpcMs, null);
});

test('a new click flushes the unfinished previous click', () => {
  const { trace, clock, lines } = makeTrace();
  trace.click('calendar', 100);
  clock.t = 110;
  trace.mark('layout', { active: null });
  trace.click('teams', 200);
  assert.strictEqual(lines.length, 1);
  assert.strictEqual(JSON.parse(lines[0].slice(13)).app, 'calendar');
});

test('marks after the frame are ignored', () => {
  const { trace, clock, lines } = makeTrace();
  trace.click('teams', 0);
  clock.t = 5;
  trace.mark('frame');
  clock.t = 9;
  trace.mark('layout', { active: 'teams' });
  trace.finish();
  assert.strictEqual(lines.length, 1);
  assert.strictEqual(JSON.parse(lines[0].slice(13)).layoutPasses, 0);
});

test('the settle timer finishes a click that never got a frame', () => {
  const { trace, lines, timers } = makeTrace();
  trace.click('calendar', 0);
  assert.strictEqual(timers.length, 1);
  timers[0]();
  assert.strictEqual(lines.length, 1);
  timers[0]();
  assert.strictEqual(lines.length, 1);
});

test('a stale settle timer does not finish a newer click', () => {
  const { trace, lines, timers } = makeTrace();
  trace.click('calendar', 0);
  trace.click('teams', 10);
  assert.strictEqual(lines.length, 1);
  timers[0]();
  assert.strictEqual(lines.length, 1);
});

test('a late frame probe from an older click is ignored', () => {
  const { trace, clock, lines } = makeTrace();
  trace.click('teams', 0);
  const oldToken = trace.token();
  trace.click('outlook', 10);
  clock.t = 20;
  trace.markFrame(oldToken);
  assert.strictEqual(lines.length, 1);
  trace.markFrame(trace.token());
  assert.strictEqual(lines.length, 2);
  assert.strictEqual(JSON.parse(lines[1].slice('[pane-trace] '.length)).clickToFrameMs, 10);
});

test('a frame probe after the click settled is ignored', () => {
  const { trace, lines, timers } = makeTrace();
  trace.click('teams', 0);
  const tok = trace.token();
  timers[0]();
  trace.click('slack', 5000);
  trace.markFrame(tok);
  assert.strictEqual(lines.length, 1);
});

const fs = require('node:fs');
const path = require('node:path');
const read = (rel) => fs.readFileSync(path.join(__dirname, '..', rel), 'utf8');

test('the trace is wired through main, preload and the rail click', () => {
  const main = read('shell/main.js');
  assert.match(
    main,
    /require\('\.\/pane-trace'\)\.createPaneTrace\(\{\s*enabled: process\.env\.AIGATOR_PANE_TRACE === '1'/,
  );
  assert.match(main, /ipcMain\.on\('pane-trace:click'/);
  assert.match(main, /paneTrace\.mark\('ipc-show'/);
  assert.match(main, /paneTrace\.mark\('ipc-hide'/);
  assert.match(main, /paneTrace\.mark\('layout'/);
  assert.match(main, /paneTrace\.markFrame\(traceToken\)/);
  assert.match(
    read('shell/preload.js'),
    /paneTraceClick: \(app\) => ipcRenderer\.send\('pane-trace:click', app, Date\.now\(\)\)/,
  );
  assert.match(read('web/static/app.js'), /window\.gatorShell\?\.paneTraceClick\?\.\(id\)/);
});
