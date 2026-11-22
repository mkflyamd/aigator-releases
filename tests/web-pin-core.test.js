const test = require('node:test');
const assert = require('node:assert');
const core = require('../shell/web-pin-core');

test('clipFromQuad uses min/max of the quad and adds the scroll offset', () => {
  const clip = core.clipFromQuad([10, 20, 110, 20, 110, 80, 10, 80], { x: 5, y: 100 });
  assert.deepStrictEqual(clip, { x: 15, y: 120, width: 100, height: 60, scale: 1 });
});

test('clipFromQuad works without an offset', () => {
  assert.deepStrictEqual(core.clipFromQuad([0, 0, 4, 0, 4, 2, 0, 2]), { x: 0, y: 0, width: 4, height: 2, scale: 1 });
});

test('captureScale caps at 2x and shrinks large captures to 1600px', () => {
  assert.strictEqual(core.captureScale(200, 100), 2);
  assert.strictEqual(core.captureScale(3200, 1000), 0.5);
  assert.strictEqual(core.captureScale(1600, 900), 1);
  assert.strictEqual(core.captureScale(0, 0), 1);
});

test('capText collapses blank runs and enforces the cap', () => {
  assert.strictEqual(core.capText('a\n\n\n\nb'), 'a\n\nb');
  const out = core.capText('x'.repeat(30000));
  assert.ok(out.length <= core.MAX_TEXT && out.endsWith('\n[truncated]'));
  assert.strictEqual(core.capText('short'), 'short');
  assert.strictEqual(core.capText(null), '');
});

test('hoverLabel priority and truncation', () => {
  assert.strictEqual(core.hoverLabel({ ariaLabel: 'Revenue', role: 'img', heading: 'H', tag: 'DIV' }), 'Revenue');
  assert.strictEqual(core.hoverLabel({ role: 'img', heading: 'H', tag: 'DIV' }), 'img');
  assert.strictEqual(core.hoverLabel({ heading: 'Sales by region', tag: 'DIV' }), 'Sales by region');
  assert.strictEqual(core.hoverLabel({ tag: 'DIV' }), 'div');
  assert.ok(core.hoverLabel({ ariaLabel: 'x'.repeat(200) }).length <= 60);
  assert.strictEqual(core.hoverLabel({}), 'element');
});

test('urlMatches compares origin and pathname only', () => {
  assert.ok(core.urlMatches('https://a.com/r/1?x=1#h', 'https://a.com/r/1/'));
  assert.ok(!core.urlMatches('https://a.com/r/1', 'https://a.com/r/2'));
  assert.ok(!core.urlMatches('https://a.com/r/1', 'https://b.com/r/1'));
  assert.ok(!core.urlMatches('not a url', 'https://a.com'));
});

function fakeCdp(handlers) {
  const calls = [];
  return {
    calls,
    async send(method, params) {
      calls.push(method);
      const h = handlers[method];
      if (!h) throw new Error('unexpected ' + method);
      return typeof h === 'function' ? h(params) : h;
    },
  };
}

const LOC = { selector: '#kpi', role: 'img', name: 'Revenue', rect: { x: 100, y: 200, width: 40, height: 20 } };

test('resolveTarget prefers a unique selector', async () => {
  const cdp = fakeCdp({
    'Runtime.evaluate': { result: { subtype: 'node', objectId: 'o1' } },
    'DOM.describeNode': { node: { backendNodeId: 7 } },
  });
  assert.deepStrictEqual(await core.resolveTarget(cdp, LOC), { backendNodeId: 7, match: 'selector' });
});

test('resolveTarget falls back to a unique role+name', async () => {
  const cdp = fakeCdp({
    'Runtime.evaluate': { result: { subtype: 'null' } },
    'DOM.getDocument': { root: { nodeId: 1 } },
    'Accessibility.queryAXTree': { nodes: [{ backendDOMNodeId: 9 }] },
  });
  assert.deepStrictEqual(await core.resolveTarget(cdp, LOC), { backendNodeId: 9, match: 'role-name' });
});

test('resolveTarget falls back to rect when role+name is ambiguous', async () => {
  const cdp = fakeCdp({
    'Runtime.evaluate': (p) =>
      /scrollX/.test(p.expression) ? { result: { value: { x: 0, y: 100 } } } : { result: { subtype: 'null' } },
    'DOM.getDocument': { root: { nodeId: 1 } },
    'Accessibility.queryAXTree': { nodes: [{ backendDOMNodeId: 9 }, { backendDOMNodeId: 10 }] },
    'DOM.getNodeForLocation': (p) => {
      assert.deepStrictEqual([p.x, p.y], [120, 110]);
      return { backendNodeId: 11 };
    },
  });
  assert.deepStrictEqual(await core.resolveTarget(cdp, LOC), { backendNodeId: 11, match: 'rect' });
});

test('resolveTarget returns null when nothing matches or locator is empty', async () => {
  const none = fakeCdp({
    'Runtime.evaluate': { result: { subtype: 'null' } },
    'DOM.getDocument': { root: { nodeId: 1 } },
    'Accessibility.queryAXTree': { nodes: [] },
    'DOM.getNodeForLocation': () => { throw new Error('no node'); },
  });
  assert.strictEqual(await core.resolveTarget(none, LOC), null);
  assert.strictEqual(await core.resolveTarget(fakeCdp({}), null), null);
});

test('pin cursor css is one safe user rule with a hotspot and a crosshair fallback', () => {
  const css = require('../shell/web-pin-core').PIN_CURSOR_CSS;
  assert.match(css, /^html, html \* \{ cursor: url\("data:image\/svg\+xml,[^"]+"\) 8 25, crosshair !important; \}$/);
  const uri = css.slice(css.indexOf('data:'), css.indexOf('")'));
  assert.doesNotMatch(uri, /[<>#]/);
});
