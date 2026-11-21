// tests/web-pin.test.js
const test = require('node:test');
const assert = require('node:assert');
const { EventEmitter } = require('node:events');
const { createWebPin } = require('../shell/web-pin');

const INFO = JSON.stringify({
  tag: 'DIV', ariaLabel: 'Revenue', role: '', name: 'Revenue', heading: '', text: '4.2M',
  locator: { selector: '#kpi', role: '', name: 'Revenue', rect: { x: 10, y: 120, width: 100, height: 60 } },
});
const PAGE = JSON.stringify({ text: 'whole page', title: 'Dash', url: 'https://a.com/r/1' });

function fakeWc({ url = 'https://a.com/r/1', overrides = {}, attached: preAttached = false } = {}) {
  const sent = [];
  const inspectCalls = [];
  const params = {};
  let attached = preAttached;
  let currentUrl = url;
  const handlers = {
    'DOM.resolveNode': { object: { objectId: 'o1' } },
    'Runtime.callFunctionOn': { result: { value: INFO } },
    'DOM.getBoxModel': { model: { border: [10, 20, 110, 20, 110, 80, 10, 80] } },
    'Page.getLayoutMetrics': { cssVisualViewport: { pageX: 0, pageY: 100, clientWidth: 800, clientHeight: 600 } },
    'Page.captureScreenshot': { data: 'UE5H' },
    'Runtime.evaluate': { result: { value: PAGE } },
    ...overrides,
  };
  const dbg = new EventEmitter();
  dbg.isAttached = () => attached;
  dbg.attach = () => { attached = true; };
  dbg.detach = () => { attached = false; };
  dbg.sendCommand = async (method, p) => {
    sent.push(method);
    params[method] = p;
    if (method === 'Overlay.setInspectMode') inspectCalls.push(p);
    const h = handlers[method];
    return typeof h === 'function' ? h(p) : h || {};
  };
  const wc = new EventEmitter();
  return Object.assign(wc, {
    debugger: dbg, sent, inspectCalls, params, getURL: () => currentUrl, setUrl: (u) => { currentUrl = u; }, isDestroyed: () => false,
  });
}

function inspectModes(wc) {
  return wc.inspectCalls.map((p) => p.mode);
}

function deferred() {
  let resolve;
  const promise = new Promise((r) => { resolve = r; });
  return { promise, resolve };
}

function harness(wc, { visible = true, timeoutMs = 50 } = {}) {
  const events = { captured: [], errors: [], states: [] };
  const wp = createWebPin({
    getPane: (id) => (id === 'custom-x' ? wc : null),
    isPaneVisible: () => visible,
    onState: (s) => events.states.push(s),
    onCaptured: (c) => events.captured.push(c),
    onError: (e) => events.errors.push(e),
    timeoutMs,
  });
  return { wp, events };
}

async function waitFor(fn, ms = 500) {
  const end = Date.now() + ms;
  while (!fn()) {
    if (Date.now() > end) throw new Error('waitFor timed out');
    await new Promise((r) => setTimeout(r, 5));
  }
}

test('pick flow captures the clicked element after hiding the highlight', async () => {
  const wc = fakeWc();
  const { wp, events } = harness(wc);
  assert.deepStrictEqual(await wp.start('custom-x'), { ok: true });
  assert.deepStrictEqual(events.states.at(-1), { appId: 'custom-x', picking: true, label: '' });
  wc.debugger.emit('message', {}, 'Overlay.inspectNodeRequested', { backendNodeId: 5 });
  await waitFor(() => events.captured.length === 1);
  const c = events.captured[0];
  assert.strictEqual(c.appId, 'custom-x');
  assert.strictEqual(c.image_b64, 'UE5H');
  assert.strictEqual(c.aria_label, 'Revenue');
  assert.strictEqual(c.text, '4.2M');
  assert.strictEqual(c.locator.selector, '#kpi');
  assert.strictEqual(c.url, 'https://a.com/r/1');
  assert.strictEqual(c.title, 'Dash');
  assert.ok(wc.sent.indexOf('Overlay.hideHighlight') < wc.sent.indexOf('Page.captureScreenshot'));
  assert.deepStrictEqual(inspectModes(wc), ['searchForNode', 'none', 'none']);
  assert.deepStrictEqual(wc.params['Page.captureScreenshot'].clip, { x: 10, y: 120, width: 100, height: 60, scale: 2 });
  await waitFor(() => !wc.debugger.isAttached());
  assert.strictEqual(events.states.at(-1).picking, false);
});

test('hover events update the banner label', async () => {
  const wc = fakeWc({ overrides: { 'Runtime.callFunctionOn': { result: { value: JSON.stringify({ ariaLabel: 'Sales by region' }) } } } });
  const { wp, events } = harness(wc);
  await wp.start('custom-x');
  wc.debugger.emit('message', {}, 'Overlay.nodeHighlightRequested', { nodeId: 3 });
  await waitFor(() => events.states.some((s) => s.label === 'Sales by region'));
});

test('Escape cancels pick mode and detaches', async () => {
  const wc = fakeWc();
  const { wp, events } = harness(wc);
  await wp.start('custom-x');
  let prevented = false;
  wc.emit('before-input-event', { preventDefault() { prevented = true; } }, { type: 'keyDown', key: 'Escape' });
  await waitFor(() => !wc.debugger.isAttached());
  assert.ok(prevented);
  assert.strictEqual(events.captured.length, 0);
  assert.strictEqual(wc.listenerCount('before-input-event'), 0);
  assert.strictEqual(events.states.at(-1).picking, false);
  assert.strictEqual(inspectModes(wc).at(-1), 'none');
  assert.ok(wc.sent.includes('Overlay.hideHighlight'));
});

test('start refuses a hidden or unknown pane', async () => {
  const hidden = harness(fakeWc(), { visible: false });
  assert.deepStrictEqual(await hidden.wp.start('custom-x'), { ok: false, status: 'pane_not_visible' });
  assert.deepStrictEqual(hidden.events.errors, [{ appId: 'custom-x', code: 'pane_not_visible' }]);
  const unknown = harness(fakeWc());
  assert.deepStrictEqual(await unknown.wp.start('nope'), { ok: false, status: 'pane_unavailable' });
});

test('pinView captures the visible viewport with no locator', async () => {
  const wc = fakeWc();
  const { wp, events } = harness(wc);
  await wp.pinView('custom-x');
  assert.strictEqual(events.captured.length, 1);
  const c = events.captured[0];
  assert.strictEqual(c.locator, null);
  assert.strictEqual(c.text, 'whole page');
  assert.deepStrictEqual(wc.params['Page.captureScreenshot'].clip, { x: 0, y: 100, width: 800, height: 600, scale: 2 });
  assert.strictEqual(wc.debugger.isAttached(), false);
});

test('recapture refuses hidden panes and moved pages', async () => {
  const hidden = harness(fakeWc(), { visible: false });
  assert.deepStrictEqual(await hidden.wp.recapture('custom-x', null, 'https://a.com/r/1'), { status: 'pane_not_visible' });
  const moved = harness(fakeWc({ url: 'https://a.com/r/2' }));
  assert.deepStrictEqual(await moved.wp.recapture('custom-x', null, 'https://a.com/r/1'), { status: 'page_mismatch' });
});

test('recapture re-finds the element by selector', async () => {
  const wc = fakeWc({
    overrides: {
      'Runtime.evaluate': { result: { subtype: 'node', objectId: 'o9', value: PAGE } },
      'DOM.describeNode': { node: { backendNodeId: 7 } },
    },
  });
  const { wp, events } = harness(wc);
  const r = await wp.recapture('custom-x', JSON.parse(INFO).locator, 'https://a.com/r/1');
  assert.strictEqual(r.status, 'ok');
  assert.strictEqual(r.match, 'selector');
  assert.strictEqual(r.image_b64, 'UE5H');
  assert.strictEqual(events.captured.length, 0);
});

test('recapture of a whole-view pin reports match "view"', async () => {
  const { wp } = harness(fakeWc());
  const r = await wp.recapture('custom-x', null, 'https://a.com/r/1');
  assert.strictEqual(r.status, 'ok');
  assert.strictEqual(r.match, 'view');
});

test('recapture falls back to the whole view when the element is gone', async () => {
  const wc = fakeWc({
    overrides: {
      'Runtime.evaluate': (p) =>
        /scrollX/.test(p.expression) ? { result: { value: { x: 0, y: 0 } } } : { result: { subtype: 'null', value: PAGE } },
      'DOM.getDocument': { root: { nodeId: 1 } },
      'Accessibility.queryAXTree': { nodes: [] },
      'DOM.getNodeForLocation': () => { throw new Error('no node'); },
    },
  });
  const { wp } = harness(wc);
  const r = await wp.recapture('custom-x', JSON.parse(INFO).locator, 'https://a.com/r/1');
  assert.strictEqual(r.status, 'ok');
  assert.strictEqual(r.match, 'view-fallback');
});

test('a hung CDP call times out and detaches', async () => {
  const wc = fakeWc({ overrides: { 'Page.getLayoutMetrics': () => new Promise(() => {}) } });
  const { wp } = harness(wc);
  assert.deepStrictEqual(await wp.recapture('custom-x', null, 'https://a.com/r/1'), { status: 'timeout' });
  assert.strictEqual(wc.debugger.isAttached(), false);
});

test('a zero-size view fails with empty_target instead of calling captureScreenshot', async () => {
  const wc = fakeWc({
    overrides: { 'Page.getLayoutMetrics': { cssVisualViewport: { pageX: 0, pageY: 0, clientWidth: 0, clientHeight: 0 } } },
  });
  const { wp, events } = harness(wc);
  await wp.pinView('custom-x');
  assert.deepStrictEqual(events.errors, [{ appId: 'custom-x', code: 'empty_target' }]);
  assert.ok(!wc.sent.includes('Page.captureScreenshot'));
  assert.strictEqual(wc.debugger.isAttached(), false);
});

test('a zero-size element fails with empty_target and leaves inspect mode', async () => {
  const wc = fakeWc({ overrides: { 'DOM.getBoxModel': { model: { border: [10, 20, 10, 20, 10, 20, 10, 20] } } } });
  const { wp, events } = harness(wc);
  await wp.start('custom-x');
  wc.debugger.emit('message', {}, 'Overlay.inspectNodeRequested', { backendNodeId: 5 });
  await waitFor(() => events.errors.length === 1);
  assert.deepStrictEqual(events.errors, [{ appId: 'custom-x', code: 'empty_target' }]);
  assert.strictEqual(events.captured.length, 0);
  assert.ok(!wc.sent.includes('Page.captureScreenshot'));
  await waitFor(() => !wc.debugger.isAttached());
  assert.strictEqual(inspectModes(wc).at(-1), 'none');
  assert.strictEqual(events.states.at(-1).picking, false);
});

test('a failing element capture reports an error, leaves inspect mode and detaches', async () => {
  const wc = fakeWc({ overrides: { 'DOM.getBoxModel': () => { throw new Error('boom'); } } });
  const { wp, events } = harness(wc);
  await wp.start('custom-x');
  wc.debugger.emit('message', {}, 'Overlay.inspectNodeRequested', { backendNodeId: 5 });
  await waitFor(() => events.errors.length === 1);
  assert.deepStrictEqual(events.errors, [{ appId: 'custom-x', code: 'pane_unavailable' }]);
  assert.strictEqual(events.captured.length, 0);
  await waitFor(() => !wc.debugger.isAttached());
  assert.strictEqual(inspectModes(wc).at(-1), 'none');
  assert.strictEqual(events.states.at(-1).picking, false);
});

test('Escape while the screenshot is pending cancels without a pin or an error', async () => {
  const shot = deferred();
  const wc = fakeWc({ overrides: { 'Page.captureScreenshot': () => shot.promise } });
  const { wp, events } = harness(wc, { timeoutMs: 1000 });
  await wp.start('custom-x');
  wc.debugger.emit('message', {}, 'Overlay.inspectNodeRequested', { backendNodeId: 5 });
  await waitFor(() => wc.sent.includes('Page.captureScreenshot'));
  wc.emit('before-input-event', { preventDefault() {} }, { type: 'keyDown', key: 'Escape' });
  await waitFor(() => !wc.debugger.isAttached());
  shot.resolve({ data: 'UE5H' });
  await new Promise((r) => setTimeout(r, 30));
  assert.strictEqual(events.captured.length, 0);
  assert.deepStrictEqual(events.errors, []);
  assert.strictEqual(events.states.at(-1).picking, false);
});

test('a double start opens a single session', async () => {
  const wc = fakeWc();
  const { wp, events } = harness(wc);
  const [a, b] = await Promise.all([wp.start('custom-x'), wp.start('custom-x')]);
  assert.deepStrictEqual(a, { ok: true });
  assert.deepStrictEqual(b, { ok: true });
  assert.strictEqual(wc.listenerCount('before-input-event'), 1);
  assert.strictEqual(wc.debugger.listenerCount('message'), 1);
  assert.strictEqual(wc.sent.filter((m) => m === 'Overlay.enable').length, 1);
  await wp.stop();
  assert.strictEqual(wc.debugger.isAttached(), false);
  assert.strictEqual(wc.debugger.listenerCount('message'), 0);
  assert.deepStrictEqual(events.errors, []);
});

test('start is refused while a capture is in flight on the same pane', async () => {
  const gate = deferred();
  const wc = fakeWc({ overrides: { 'Page.getLayoutMetrics': () => gate.promise } });
  const { wp, events } = harness(wc, { timeoutMs: 1000 });
  const pinning = wp.pinView('custom-x');
  await waitFor(() => wc.sent.includes('Page.getLayoutMetrics'));
  assert.deepStrictEqual(await wp.start('custom-x'), { ok: false, status: 'pane_unavailable' });
  assert.strictEqual(wc.debugger.isAttached(), true);
  gate.resolve({ cssVisualViewport: { pageX: 0, pageY: 0, clientWidth: 800, clientHeight: 600 } });
  await pinning;
  assert.strictEqual(events.captured.length, 1);
  assert.strictEqual(wc.debugger.isAttached(), false);
});

test('pane destruction while picking resets the banner without sending CDP', async () => {
  const wc = fakeWc();
  const { wp, events } = harness(wc);
  await wp.start('custom-x');
  const sentBefore = wc.sent.length;
  wc.emit('destroyed');
  await waitFor(() => events.states.at(-1).picking === false);
  assert.strictEqual(wc.sent.length, sentBefore);
  assert.strictEqual(wc.listenerCount('before-input-event'), 0);
  assert.strictEqual(wc.listenerCount('destroyed'), 0);
  assert.strictEqual(wc.debugger.listenerCount('detach'), 0);
  assert.deepStrictEqual(events.errors, []);
});

test('an external debugger detach while picking resets the banner', async () => {
  const wc = fakeWc();
  const { wp, events } = harness(wc);
  await wp.start('custom-x');
  wc.debugger.detach();
  wc.debugger.emit('detach', {}, 'target closed');
  await waitFor(() => events.states.at(-1).picking === false);
  assert.strictEqual(wc.listenerCount('before-input-event'), 0);
  assert.strictEqual(wc.debugger.listenerCount('message'), 0);
  assert.strictEqual(wc.debugger.listenerCount('detach'), 0);
});

test('a debugger attached by someone else stays attached after cancel', async () => {
  const wc = fakeWc({ attached: true });
  const { wp } = harness(wc);
  await wp.start('custom-x');
  wc.emit('before-input-event', { preventDefault() {} }, { type: 'keyDown', key: 'Escape' });
  await waitFor(() => wc.debugger.listenerCount('message') === 0);
  assert.strictEqual(wc.debugger.isAttached(), true);
  assert.strictEqual(inspectModes(wc).at(-1), 'none');
});

test('recapture without a url is a page_mismatch and captures nothing', async () => {
  const wc = fakeWc();
  const { wp } = harness(wc);
  assert.deepStrictEqual(await wp.recapture('custom-x', null, ''), { status: 'page_mismatch' });
  assert.ok(!wc.sent.includes('Page.captureScreenshot'));
  assert.strictEqual(wc.debugger.isAttached(), false);
});

test('recapture fails with page_mismatch when the page navigates mid-capture', async () => {
  let wcRef;
  const wc = fakeWc({
    overrides: { 'Page.captureScreenshot': () => { wcRef.setUrl('https://a.com/r/2'); return { data: 'UE5H' }; } },
  });
  wcRef = wc;
  const { wp } = harness(wc);
  assert.deepStrictEqual(await wp.recapture('custom-x', null, 'https://a.com/r/1'), { status: 'page_mismatch' });
  assert.strictEqual(wc.debugger.isAttached(), false);
});

test('pinned url comes from the main process, not from page-reported text', async () => {
  const spoof = JSON.stringify({ text: 'whole page', title: 'Dash', url: 'https://evil.test/phish' });
  const view = fakeWc({ overrides: { 'Runtime.evaluate': { result: { value: spoof } } } });
  const v = harness(view);
  await v.wp.pinView('custom-x');
  assert.strictEqual(v.events.captured[0].url, 'https://a.com/r/1');

  const pick = fakeWc({ overrides: { 'Runtime.evaluate': { result: { value: spoof } } } });
  const p = harness(pick);
  await p.wp.start('custom-x');
  pick.debugger.emit('message', {}, 'Overlay.inspectNodeRequested', { backendNodeId: 5 });
  await waitFor(() => p.events.captured.length === 1);
  assert.strictEqual(p.events.captured[0].url, 'https://a.com/r/1');

  const re = fakeWc({ overrides: { 'Runtime.evaluate': { result: { value: spoof } } } });
  const r = await harness(re).wp.recapture('custom-x', null, 'https://a.com/r/1');
  assert.strictEqual(r.url, 'https://a.com/r/1');
});

test('captureBeyondViewport is only requested when the clip leaves the viewport', async () => {
  // whole-view capture and an element fully inside the viewport (0,100 800x600)
  const view = fakeWc();
  await harness(view).wp.pinView('custom-x');
  assert.strictEqual(view.params['Page.captureScreenshot'].captureBeyondViewport, false);

  const inside = fakeWc();
  const i = harness(inside);
  await i.wp.start('custom-x');
  inside.debugger.emit('message', {}, 'Overlay.inspectNodeRequested', { backendNodeId: 5 });
  await waitFor(() => i.events.captured.length === 1);
  assert.strictEqual(inside.params['Page.captureScreenshot'].captureBeyondViewport, false);

  // an element taller than the viewport needs the page to be captured beyond it
  const tall = fakeWc({ overrides: { 'DOM.getBoxModel': { model: { border: [10, 20, 110, 20, 110, 900, 10, 900] } } } });
  const t = harness(tall);
  await t.wp.start('custom-x');
  tall.debugger.emit('message', {}, 'Overlay.inspectNodeRequested', { backendNodeId: 5 });
  await waitFor(() => t.events.captured.length === 1);
  assert.strictEqual(tall.params['Page.captureScreenshot'].captureBeyondViewport, true);
});
