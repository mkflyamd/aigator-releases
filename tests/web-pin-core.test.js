const test = require('node:test');
const assert = require('node:assert');
const vm = require('node:vm');
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

const PIN = {
  tag: 'div',
  type: '',
  role: 'img',
  name: 'Revenue',
  testId: '',
  heading: 'Sales dashboard',
  ancestor: '',
  text: 'Revenue by region North South 4.2M',
  rect: { x: 100, y: 200, width: 300, height: 200 },
};

function cand(i, over = {}) {
  return {
    tag: 'div',
    type: '',
    role: '',
    name: '',
    testId: '',
    heading: '',
    ancestor: '',
    text: '',
    rect: { x: 0, y: 0, width: 10, height: 10 },
    i,
    ...over,
  };
}

const SAME = {
  role: 'img',
  name: 'Revenue',
  heading: 'Sales dashboard',
  text: 'Revenue by region North South 4.3M',
};

test('matchLocator: a stable test id survives a move and a rename', () => {
  const loc = { ...PIN, testId: 'data-testid=rev' };
  const moved = cand(3, {
    testId: 'data-testid=rev',
    name: 'Total revenue',
    rect: { x: 700, y: 900, width: 300, height: 200 },
  });
  const m = core.matchLocator(loc, [cand(1, { testId: 'data-testid=cost' }), moved]);
  assert.deepStrictEqual(m, { status: 'ok', index: 3, match: 'stable-id', confidence: 0.98 });
});

test('matchLocator: a moved element is still found by role and name', () => {
  const moved = cand(2, { ...SAME, rect: { x: 900, y: 40, width: 300, height: 200 } });
  const m = core.matchLocator(PIN, [cand(1, { role: 'img', name: 'Cost' }), moved]);
  assert.strictEqual(m.index, 2);
  assert.strictEqual(m.match, 'role-name');
});

test('matchLocator: a changed selector or renamed label is found by fingerprint, not position', () => {
  const renamed = cand(5, {
    ...SAME,
    name: 'Total revenue',
    rect: { x: 5, y: 5, width: 50, height: 50 },
  });
  const other = cand(6, { role: 'img', name: 'Cost', heading: 'Costs', text: 'Cost by region' });
  const m = core.matchLocator(PIN, [other, renamed]);
  assert.strictEqual(m.status, 'ok');
  assert.strictEqual(m.index, 5);
  assert.strictEqual(m.match, 'fingerprint');
  assert.ok(m.confidence >= 0.7 && m.confidence <= 1);
});

test('matchLocator: duplicate role and name are told apart by the rest of the fingerprint', () => {
  const north = cand(1, { ...SAME, heading: 'Marketing', text: 'Revenue by channel Web Retail' });
  const real = cand(2, { ...SAME });
  const m = core.matchLocator(PIN, [north, real]);
  assert.strictEqual(m.index, 2);
  assert.strictEqual(m.match, 'fingerprint');
});

test('matchLocator: indistinguishable duplicates are ambiguous unless exactly one sits where the pin was', () => {
  const a = cand(1, { ...SAME, rect: { x: 900, y: 900, width: 300, height: 200 } });
  const b = cand(2, { ...SAME, rect: { x: 1400, y: 900, width: 300, height: 200 } });
  assert.deepStrictEqual(core.matchLocator(PIN, [a, b]), { status: 'element_ambiguous' });
  const home = cand(3, { ...SAME, rect: { x: 105, y: 205, width: 300, height: 200 } });
  const m = core.matchLocator(PIN, [a, b, home]);
  assert.strictEqual(m.index, 3);
  assert.strictEqual(m.match, 'fingerprint-geometry');
  assert.ok(m.confidence <= 0.7);
  const twin = cand(4, { ...SAME, rect: { x: 110, y: 210, width: 300, height: 200 } });
  assert.deepStrictEqual(core.matchLocator(PIN, [home, twin]), { status: 'element_ambiguous' });
});

test('matchLocator: a deleted element is reported missing, not replaced by something similar-looking', () => {
  assert.deepStrictEqual(core.matchLocator(PIN, []), { status: 'element_missing' });
  const unrelated = cand(1, { role: 'img', name: 'Cost', heading: 'Costs', text: 'Cost by team' });
  assert.deepStrictEqual(core.matchLocator(PIN, [unrelated]), { status: 'element_missing' });
});

test('matchLocator: a different element in the old rectangle is never taken for the pinned one', () => {
  const squatter = cand(1, {
    role: 'img',
    name: 'Headcount',
    heading: 'People',
    text: 'Headcount by team',
    rect: { ...PIN.rect },
  });
  assert.deepStrictEqual(core.matchLocator(PIN, [squatter]), { status: 'element_missing' });
  const sameTag = cand(2, {
    heading: 'Sales dashboard',
    text: 'Unrelated footnote',
    rect: { ...PIN.rect },
  });
  assert.deepStrictEqual(core.matchLocator(PIN, [sameTag]), { status: 'element_missing' });
});

test('matchLocator: a locator with only position and tag cannot identify anything', () => {
  const bare = { tag: 'div', type: '', rect: PIN.rect };
  assert.deepStrictEqual(core.matchLocator(bare, [cand(1, { rect: { ...PIN.rect } })]), {
    status: 'element_missing',
  });
  assert.deepStrictEqual(core.matchLocator(null, [cand(1)]), { status: 'element_missing' });
});

test('matchLocator: numbers changing on a live dashboard do not break the match', () => {
  const loc = { ...PIN, role: '', name: '', text: 'Revenue 4.2M vs 3.9M last year' };
  const now = cand(1, { heading: 'Sales dashboard', text: 'Revenue 4.5M vs 4.2M last year' });
  const m = core.matchLocator(loc, [now]);
  assert.strictEqual(m.status, 'ok');
  assert.strictEqual(m.match, 'fingerprint');
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

function scanCdp(features) {
  return fakeCdp({
    'Runtime.evaluate': { result: { objectId: 'scan' } },
    'Runtime.callFunctionOn': (p) =>
      /this\[0\]/.test(p.functionDeclaration)
        ? { result: { value: JSON.stringify({ features, truncated: false }) } }
        : { result: { objectId: 'el' + p.arguments[0].value } },
    'DOM.describeNode': (p) => ({ node: { backendNodeId: Number(p.objectId.slice(2)) + 100 } }),
    'Runtime.releaseObjectGroup': {},
  });
}

test('resolveTarget returns the matched node with its method and confidence, and releases the scan', async () => {
  const cdp = scanCdp([cand(0), cand(1, { ...SAME })]);
  assert.deepStrictEqual(await core.resolveTarget(cdp, PIN), {
    status: 'ok',
    backendNodeId: 101,
    match: 'role-name',
    confidence: 0.9,
  });
  assert.ok(cdp.calls.includes('Runtime.releaseObjectGroup'));
});

test('resolveTarget reports missing or ambiguous without describing any node', async () => {
  const none = scanCdp([cand(0, { name: 'Cost', role: 'img', heading: 'Costs', text: 'Cost' })]);
  assert.deepStrictEqual(await core.resolveTarget(none, PIN), { status: 'element_missing' });
  assert.ok(!none.calls.includes('DOM.describeNode'));
  assert.ok(none.calls.includes('Runtime.releaseObjectGroup'));
  const twins = scanCdp([
    cand(0, { ...SAME, rect: { x: 900, y: 900, width: 300, height: 200 } }),
    cand(1, { ...SAME, rect: { x: 1500, y: 900, width: 300, height: 200 } }),
  ]);
  assert.deepStrictEqual(await core.resolveTarget(twins, { ...PIN, role: '', name: '' }), {
    status: 'element_ambiguous',
  });
  assert.deepStrictEqual(await core.resolveTarget(fakeCdp({}), null), {
    status: 'element_missing',
  });
});

test('resolveTarget treats a page with no scan result as missing', async () => {
  const cdp = fakeCdp({ 'Runtime.evaluate': { result: { subtype: 'null' } } });
  assert.deepStrictEqual(await core.resolveTarget(cdp, PIN), { status: 'element_missing' });
});

function domEl(tag, opts = {}, children = []) {
  const el = fakeEl(tag, opts, children);
  const r = opts.rect || { left: 1, top: 2, width: 30, height: 40 };
  const box = { ...r, right: r.left + r.width, bottom: r.top + r.height };
  el.getBoundingClientRect = () => box;
  el.nodeType = 1;
  el.scrolled = 0;
  el.scrollIntoView = () => {
    el.scrolled++;
  };
  el.getClientRects = () => (r.width && r.height ? [r] : []);
  el.matches = () => false;
  el.id = (opts.attrs && opts.attrs.id) || '';
  el.querySelector = (sel) => el.querySelectorAll(sel)[0] || null;
  return el;
}

function inPageContext(extra = {}) {
  return vm.createContext({
    window: { scrollX: 0, scrollY: 100 },
    document: { getElementById: () => null, ...extra },
  });
}

test('describeInPage runs standalone in the page and records the semantic fingerprint', () => {
  const h = domEl('h3', { text: 'Sales dashboard' });
  const chart = domEl('div', {
    attrs: { 'data-testid': 'rev', 'aria-label': 'Revenue', role: 'img' },
    text: 'Revenue 4.2M',
  });
  domEl('section', { attrs: { 'aria-label': 'Overview' } }, [h, chart]);
  const fn = vm.runInContext(
    '(' + core.elementFunction(core.describeInPage) + ')',
    inPageContext(),
  );
  const info = JSON.parse(fn.call(chart));
  assert.strictEqual(info.ariaLabel, 'Revenue');
  assert.strictEqual(info.text, 'Revenue 4.2M');
  assert.deepStrictEqual(info.locator, {
    tag: 'div',
    type: '',
    role: 'img',
    name: 'Revenue',
    testId: 'data-testid=rev',
    heading: 'Sales dashboard',
    ancestor: 'Overview',
    text: 'Revenue 4.2M',
    rect: { x: 1, y: 102, width: 30, height: 40 },
  });
});

test('featuresOf ignores generated ids and takes a button name from its text', () => {
  const run = (el) => vm.runInContext('(' + core.featuresOf.toString() + ')', inPageContext())(el);
  assert.strictEqual(run(domEl('div', { attrs: { id: 'r1234567' } })).testId, '');
  assert.strictEqual(
    run(domEl('div', { attrs: { id: 'revenue-card' } })).testId,
    'id=revenue-card',
  );
  const b = run(domEl('button', { text: 'Export' }));
  assert.deepStrictEqual([b.role, b.name], ['button', 'Export']);
});

test('scanInPage returns visible candidates and their elements in the same order', () => {
  const a = domEl('div', { attrs: { role: 'img', 'aria-label': 'Revenue' }, text: 'a' });
  const hidden = domEl('div', { rect: { left: 0, top: 0, width: 0, height: 0 } });
  const other = domEl('p', { text: 'b' });
  const b = domEl('div', { attrs: { role: 'img', 'aria-label': 'Cost' }, text: 'c' });
  const ctx = inPageContext({ querySelectorAll: () => [a, hidden, other, b] });
  const out = vm.runInContext(core.pageExpression(core.scanInPage, PIN), ctx);
  const { features, truncated } = JSON.parse(out[0]);
  assert.strictEqual(truncated, false);
  assert.deepStrictEqual(
    features.map((f) => [f.i, f.name]),
    [
      [0, 'Revenue'],
      [1, 'Cost'],
    ],
  );
  assert.strictEqual(out[1], a);
  assert.strictEqual(out[2], b);
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

test('pickCommand maps only the picking keys and ignores chords', () => {
  const c = core.pickCommand;
  assert.strictEqual(c({ key: 'Tab' }), 'next');
  assert.strictEqual(c({ key: 'Tab', shift: true }), 'prev');
  assert.strictEqual(c({ key: 'ArrowDown' }), 'child');
  assert.strictEqual(c({ key: 'ArrowUp' }), 'parent');
  assert.strictEqual(c({ key: 'Enter' }), 'select');
  for (const bad of [
    { key: 'Tab', control: true },
    { key: 'Enter', alt: true },
    { key: 'ArrowUp', meta: true },
    { key: 'ArrowUp', shift: true },
    { key: 'a' },
    null,
  ])
    assert.strictEqual(c(bad), null);
});

function stepTree() {
  const hidden = domEl('div', { rect: { left: 0, top: 0, width: 0, height: 0 }, text: 'x' });
  const title = domEl('h2', { text: 'Sales' });
  const num = domEl('span', { text: '4.2M' });
  const card = domEl('div', { attrs: { 'aria-label': 'Revenue' } }, [num]);
  const wrap = domEl('div', {}, [hidden, title, card]);
  const below = domEl('p', {
    text: 'far below',
    rect: { left: 0, top: 5000, width: 50, height: 20 },
  });
  const body = domEl('body', {}, [wrap, below]);
  const html = domEl('html', {}, [body]);
  const step = (dir, from) => {
    const ctx = vm.createContext({
      window: { innerWidth: 800, innerHeight: 600 },
      document: { body, documentElement: html },
    });
    return vm.runInContext('(' + core.stepInPage.toString() + ')', ctx).call(from || null, dir);
  };
  return { step, title, num, card, wrap, below, hidden };
}

test('stepInPage walks meaningful visible elements in document order', () => {
  const { step, title, num, card, below } = stepTree();
  assert.strictEqual(step('next'), title);
  assert.strictEqual(step('next', title), card);
  assert.strictEqual(step('next', card), num);
  assert.strictEqual(step('next', num), below);
  assert.strictEqual(step('next', below), null);
  assert.strictEqual(step('prev', below), num);
  assert.strictEqual(step('prev', card), title);
  assert.strictEqual(step('prev', title), null);
});

test('stepInPage starts inside the viewport and scrolls the element into view', () => {
  const { step, title, below } = stepTree();
  assert.strictEqual(step('next'), title);
  assert.strictEqual(title.scrolled, 1);
  assert.strictEqual(step('prev'), title.parentElement.children[2].children[0]);
  assert.strictEqual(below.scrolled, 0);
});

test('stepInPage moves to the outer and inner element and stops at the edges', () => {
  const { step, num, card, wrap, hidden, title } = stepTree();
  assert.strictEqual(step('parent', num), card);
  assert.strictEqual(step('parent', card), wrap);
  assert.strictEqual(step('parent', wrap), null);
  assert.notStrictEqual(hidden, undefined);
  assert.strictEqual(step('child', wrap), title);
  assert.strictEqual(step('child', card), num);
  assert.strictEqual(step('child', num), null);
  assert.strictEqual(step('child'), null);
  assert.strictEqual(step('parent'), null);
});
