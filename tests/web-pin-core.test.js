const test = require('node:test');
const assert = require('node:assert');
const core = require('../shell/web-pin-core');

test('clipFromQuad uses min/max of the quad and adds the scroll offset', () => {
  const clip = core.clipFromQuad([10, 20, 110, 20, 110, 80, 10, 80], { x: 5, y: 100 });
  assert.deepStrictEqual(clip, { x: 15, y: 120, width: 100, height: 60, scale: 1 });
});

test('clipFromQuad works without an offset', () => {
  assert.deepStrictEqual(core.clipFromQuad([0, 0, 4, 0, 4, 2, 0, 2]), {
    x: 0,
    y: 0,
    width: 4,
    height: 2,
    scale: 1,
  });
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

test('hoverLabel: accessible name, then inner heading, then own short text', () => {
  assert.deepStrictEqual(
    core.hoverLabel({ name: 'Revenue', heading: 'H', text: 't', kind: 'Chart' }),
    {
      label: 'Revenue',
      kind: 'Chart',
    },
  );
  assert.deepStrictEqual(
    core.hoverLabel({ heading: 'Sales by region', text: 'x', kind: 'Table' }),
    {
      label: 'Sales by region',
      kind: 'Table',
    },
  );
  assert.deepStrictEqual(core.hoverLabel({ text: 'Total revenue 4.2M', kind: 'Section' }), {
    label: 'Total revenue 4.2M',
    kind: '',
  });
});

test('hoverLabel: the kind is dropped for Text and Section and when it repeats the label', () => {
  assert.strictEqual(core.hoverLabel({ name: 'Notes', kind: 'Text' }).kind, '');
  assert.strictEqual(core.hoverLabel({ name: 'Notes', kind: 'Section' }).kind, '');
  assert.strictEqual(core.hoverLabel({ name: 'chart', kind: 'Chart' }).kind, '');
  assert.strictEqual(core.hoverLabel({ name: 'Save', kind: 'Button' }).kind, 'Button');
});

test('hoverLabel: long own text is skipped, long labels are clipped at 40', () => {
  const long = 'word '.repeat(30);
  assert.deepStrictEqual(
    core.hoverLabel({ text: long.slice(0, 200), textLen: long.length, kind: 'Chart' }),
    {
      label: 'Chart',
      kind: '',
    },
  );
  const out = core.hoverLabel({ name: 'x'.repeat(200), kind: 'Chart' });
  assert.strictEqual(out.label.length, 40);
  assert.ok(out.label.endsWith('…'));
});

test('hoverLabel: with nothing readable it falls back to the kind word, never a tag or class', () => {
  assert.deepStrictEqual(core.hoverLabel({ kind: 'Chart', ancestor: 'Revenue' }), {
    label: 'Chart in Revenue',
    kind: '',
  });
  assert.deepStrictEqual(core.hoverLabel({ kind: 'Table' }), { label: 'Table', kind: '' });
  assert.deepStrictEqual(core.hoverLabel({ kind: 'Section' }), { label: 'This area', kind: '' });
  assert.deepStrictEqual(core.hoverLabel({ kind: 'Section', ancestor: 'Revenue' }), {
    label: 'This area in Revenue',
    kind: '',
  });
  assert.deepStrictEqual(core.hoverLabel({}), { label: 'This area', kind: '' });
  assert.deepStrictEqual(core.hoverLabel({ tag: 'DIV', role: 'img' }), {
    label: 'This area',
    kind: '',
  });
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

const LOC = {
  selector: '#kpi',
  role: 'img',
  name: 'Revenue',
  rect: { x: 100, y: 200, width: 40, height: 20 },
};

test('resolveTarget prefers a unique selector', async () => {
  const cdp = fakeCdp({
    'Runtime.evaluate': { result: { subtype: 'node', objectId: 'o1' } },
    'DOM.describeNode': { node: { backendNodeId: 7 } },
  });
  assert.deepStrictEqual(await core.resolveTarget(cdp, LOC), {
    backendNodeId: 7,
    match: 'selector',
  });
});

test('resolveTarget falls back to a unique role+name', async () => {
  const cdp = fakeCdp({
    'Runtime.evaluate': { result: { subtype: 'null' } },
    'DOM.getDocument': { root: { nodeId: 1 } },
    'Accessibility.queryAXTree': { nodes: [{ backendDOMNodeId: 9 }] },
  });
  assert.deepStrictEqual(await core.resolveTarget(cdp, LOC), {
    backendNodeId: 9,
    match: 'role-name',
  });
});

test('resolveTarget falls back to rect when role+name is ambiguous', async () => {
  const cdp = fakeCdp({
    'Runtime.evaluate': (p) =>
      /scrollX/.test(p.expression)
        ? { result: { value: { x: 0, y: 100 } } }
        : { result: { subtype: 'null' } },
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
    'DOM.getNodeForLocation': () => {
      throw new Error('no node');
    },
  });
  assert.strictEqual(await core.resolveTarget(none, LOC), null);
  assert.strictEqual(await core.resolveTarget(fakeCdp({}), null), null);
});

test('pin cursor css is one safe author rule with a hotspot and a crosshair fallback', () => {
  const css = require('../shell/web-pin-core').PIN_CURSOR_CSS;
  assert.match(
    css,
    /^:root:root, :root:root \* \{ cursor: url\("data:image\/svg\+xml,[^"]+"\) 8 25, crosshair !important; \}$/,
  );
  const uri = css.slice(css.indexOf('data:'), css.indexOf('")'));
  assert.doesNotMatch(uri, /[<>#]/);
});

// Minimal fake DOM: just enough surface for labelInPage.
function fakeEl(tag, opts = {}, children = []) {
  const el = {
    tagName: tag.toUpperCase(),
    attrs: opts.attrs || {},
    innerText: opts.text || '',
    textContent: opts.text || '',
    children,
    parentElement: null,
    ownerSVGElement: opts.inSvg ? {} : null,
    labels: opts.labels || null,
    getAttribute(a) {
      return a in this.attrs ? this.attrs[a] : null;
    },
    hasAttribute(a) {
      return a in this.attrs;
    },
    contains(n) {
      for (let c = n; c; c = c.parentElement) if (c === this) return true;
      return false;
    },
    closest(sel) {
      const tags = sel.split(',').filter((t) => /^[a-z]+$/.test(t));
      for (let c = this; c; c = c.parentElement) {
        if (tags.includes(c.tagName.toLowerCase())) return c;
        const r = c.attrs.role;
        if (r && sel.includes('[role=' + r + ']')) return c;
      }
      return null;
    },
    querySelectorAll(sel) {
      const out = [];
      const tags = sel.split(',').filter((t) => /^[a-z0-9]+$/.test(t));
      const walk = (n) => {
        for (const c of n.children) {
          if (
            tags.includes(c.tagName.toLowerCase()) ||
            (c.attrs.role === 'heading' && sel.includes('[role=heading]'))
          )
            out.push(c);
          walk(c);
        }
      };
      walk(this);
      return out;
    },
  };
  children.forEach((c) => {
    c.parentElement = el;
  });
  return el;
}

function labelOf(el) {
  global.document = { getElementById: () => null };
  try {
    return core.hoverLabel(JSON.parse(core.labelInPage.call(el)));
  } finally {
    delete global.document;
  }
}

test('labelInPage: a chart svg inside a labelled card reads as a chart, in that card', () => {
  const svg = fakeEl('svg', { attrs: { class: 'bar-chart' } });
  fakeEl('div', { attrs: { 'aria-label': 'Revenue' } }, [svg]);
  assert.deepStrictEqual(labelOf(svg), { label: 'Chart in Revenue', kind: '' });
});

test('labelInPage: an svg child is a chart part, and a plain svg is a graphic', () => {
  const rect = fakeEl('rect', { inSvg: true });
  assert.strictEqual(JSON.parse(core.labelInPage.call(rect)).kind, 'Chart part');
  const icon = fakeEl('svg');
  assert.strictEqual(labelOf(icon).label, 'Graphic');
});

test('labelInPage: heading inside the element names it, nested widget headings do not', () => {
  const h = fakeEl('h3', { text: 'Sales by region' });
  const card = fakeEl('section', {}, [h]);
  assert.deepStrictEqual(labelOf(card), { label: 'Sales by region', kind: '' });
  const th = fakeEl('h4', { text: 'Inner' });
  const list = fakeEl('ul', {}, [th]);
  const wrap = fakeEl('div', { text: 'x'.repeat(200) }, [list]);
  assert.strictEqual(labelOf(wrap).label, 'This area');
});

test('labelInPage: control kinds and own text, never a tag name', () => {
  assert.deepStrictEqual(labelOf(fakeEl('button', { text: 'Export' })), {
    label: 'Export',
    kind: 'Button',
  });
  assert.deepStrictEqual(labelOf(fakeEl('a', { attrs: { href: '/x' }, text: 'Docs' })), {
    label: 'Docs',
    kind: 'Link',
  });
  assert.deepStrictEqual(labelOf(fakeEl('table')), { label: 'Table', kind: '' });
  assert.deepStrictEqual(labelOf(fakeEl('img', { attrs: { alt: 'Logo' } })), {
    label: 'Logo',
    kind: 'Image',
  });
  assert.deepStrictEqual(labelOf(fakeEl('span', { text: 'Total revenue 4.2M' })), {
    label: 'Total revenue 4.2M',
    kind: '',
  });
  assert.deepStrictEqual(labelOf(fakeEl('div')), { label: 'This area', kind: '' });
});
