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

function fakeWc({ url = 'https://a.com/r/1', overrides = {} } = {}) {
  const sent = [];
  const params = {};
  let attached = false;
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
    const h = handlers[method];
    return typeof h === 'function' ? h(p) : h || {};
  };
  const wc = new EventEmitter();
  return Object.assign(wc, { debugger: dbg, sent, params, getURL: () => url, isDestroyed: () => false });
}

function harness(wc, { visible = true } = {}) {
  const events = { captured: [], errors: [], states: [] };
  const wp = createWebPin({
    getPane: (id) => (id === 'custom-x' ? wc : null),
    isPaneVisible: () => visible,
    onState: (s) => events.states.push(s),
    onCaptured: (c) => events.captured.push(c),
    onError: (e) => events.errors.push(e),
    timeoutMs: 50,
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
