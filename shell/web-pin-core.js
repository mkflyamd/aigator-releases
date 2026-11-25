'use strict';

const MAX_SIDE = 1600;
const MAX_TEXT = 20000;
const TRUNC = '\n[truncated]';

function clipFromQuad(quad, offset) {
  const xs = [quad[0], quad[2], quad[4], quad[6]];
  const ys = [quad[1], quad[3], quad[5], quad[7]];
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  return {
    x: minX + ((offset && offset.x) || 0),
    y: minY + ((offset && offset.y) || 0),
    width: Math.max(...xs) - minX,
    height: Math.max(...ys) - minY,
    scale: 1,
  };
}

function captureScale(width, height) {
  const longest = Math.max(width || 0, height || 0);
  if (!longest) return 1;
  return Math.min(2, MAX_SIDE / longest);
}

function capText(text, max = MAX_TEXT) {
  const t = String(text == null ? '' : text)
    .replace(/\n{3,}/g, '\n\n')
    .trim();
  if (t.length <= max) return t;
  return t.slice(0, max - TRUNC.length) + TRUNC;
}

const HOVER_LABEL_MAX = 40;
const HOVER_ANCESTOR_MAX = 30;
const HOVER_TEXT_MAX = 80;
const QUIET_KINDS = new Set(['', 'Text', 'Section']);

function clipLabel(s, max) {
  const t = String(s == null ? '' : s)
    .replace(/\s+/g, ' ')
    .trim();
  return t.length > max ? t.slice(0, max - 1) + '…' : t;
}

// info comes from labelInPage. Never a tag name or CSS class. Returns the label plus an
// optional dim kind word ('Chart', 'Table', ...) that the banner shows after the label.
function hoverLabel(info) {
  const i = info || {};
  const kind = clipLabel(i.kind, 20);
  const text = clipLabel(i.text, 200);
  const textLen = Number.isFinite(i.textLen) ? i.textLen : text.length;
  const own =
    clipLabel(i.name, 200) || clipLabel(i.heading, 200) || (textLen <= HOVER_TEXT_MAX ? text : '');
  if (own) {
    const quiet = QUIET_KINDS.has(kind) || kind.toLowerCase() === own.toLowerCase();
    return { label: clipLabel(own, HOVER_LABEL_MAX), kind: quiet ? '' : kind };
  }
  const ancestor = clipLabel(i.ancestor, HOVER_ANCESTOR_MAX);
  const noun = QUIET_KINDS.has(kind) ? 'This area' : kind;
  return { label: ancestor ? noun + ' in ' + ancestor : noun, kind: '' };
}

// Keys that drive element selection while picking. Anything with Ctrl, Alt or Meta is left alone.
function pickCommand(input) {
  const i = input || {};
  if (i.control || i.alt || i.meta) return null;
  if (i.key === 'Tab') return i.shift ? 'prev' : 'next';
  if (i.shift) return null;
  if (i.key === 'ArrowDown') return 'child';
  if (i.key === 'ArrowUp') return 'parent';
  if (i.key === 'Enter') return 'select';
  return null;
}

function urlMatches(a, b) {
  try {
    const ua = new URL(a);
    const ub = new URL(b);
    const path = (u) => u.pathname.replace(/\/+$/, '');
    return ua.origin === ub.origin && path(ua) === path(ub);
  } catch (e) {
    return false;
  }
}

// Runs INSIDE the page and is serialized with toString(), so it may not close over anything. Both pin time
// (describeInPage) and recapture time (scanInPage) call it, so the two sides describe elements identically.
function featuresOf(el) {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const attr = (n, a) => (n.getAttribute && n.getAttribute(a)) || '';
  const tag = el.tagName.toLowerCase();
  const type = tag === 'input' ? attr(el, 'type').toLowerCase() || 'text' : '';
  const IMPLICIT = {
    button: 'button',
    a: 'link',
    img: 'img',
    svg: 'img',
    canvas: 'img',
    table: 'table',
    ul: 'list',
    ol: 'list',
    select: 'combobox',
    textarea: 'textbox',
    h1: 'heading',
    h2: 'heading',
    h3: 'heading',
    h4: 'heading',
    h5: 'heading',
    h6: 'heading',
  };
  const role =
    attr(el, 'role').toLowerCase() || (tag === 'input' ? 'textbox' : IMPLICIT[tag] || '');
  const labelled = (n) => {
    const by = attr(n, 'aria-labelledby');
    if (!by) return '';
    return clean(
      by
        .split(/\s+/)
        .map((id) => (document.getElementById(id) || {}).textContent || '')
        .join(' '),
    );
  };
  const textOf = (n) => {
    const t = clean(n.innerText);
    if (t) return t;
    const own = clean(n.textContent);
    const extras = Array.from(n.querySelectorAll('[aria-label],svg text,svg title'))
      .map((x) => clean((x.getAttribute && x.getAttribute('aria-label')) || x.textContent))
      .filter(Boolean);
    return Array.from(new Set([own, ...extras].filter(Boolean))).join('\n');
  };
  const text = textOf(el);
  let name =
    clean(attr(el, 'aria-label')) ||
    labelled(el) ||
    clean(attr(el, 'title')) ||
    clean(attr(el, 'alt'));
  if (!name && el.labels && el.labels.length) {
    name = clean(
      Array.from(el.labels)
        .map((l) => l.textContent)
        .join(' '),
    );
  }
  if (!name && (role === 'button' || role === 'link' || role === 'heading'))
    name = text.slice(0, 120);
  const generated = (id) => /\d{4,}|^:|^(ember|react|rc_|__)|[a-f0-9]{12,}/i.test(id);
  let testId = '';
  for (const a of ['data-testid', 'data-test', 'data-qa', 'data-cy']) {
    if (attr(el, a)) {
      testId = a + '=' + attr(el, a);
      break;
    }
  }
  if (!testId && el.id && !generated(el.id)) testId = 'id=' + el.id;
  let heading = '';
  for (let cur = el, i = 0; cur && !heading && i < 5; i++, cur = cur.parentElement) {
    const h = cur.querySelector && cur.querySelector('h1,h2,h3,h4,h5,[role="heading"]');
    if (h && clean(h.textContent)) heading = clean(h.textContent).slice(0, 80);
  }
  let ancestor = '';
  for (let p = el.parentElement, i = 0; p && !ancestor && i < 5; i++, p = p.parentElement) {
    ancestor = clean(attr(p, 'aria-label')) || labelled(p);
  }
  const r = el.getBoundingClientRect();
  return {
    tag,
    type,
    role,
    name: name.slice(0, 200),
    testId,
    heading,
    ancestor: ancestor.slice(0, 80),
    text,
    rect: {
      x: Math.round(r.left + window.scrollX),
      y: Math.round(r.top + window.scrollY),
      width: Math.round(r.width),
      height: Math.round(r.height),
    },
  };
}

const LOCATOR_TEXT_MAX = 300;

// Runs INSIDE the page via Runtime.callFunctionOn (this = the element). Wrapped by elementFunction().
function describeInPage(featuresOf, textMax) {
  const f = featuresOf(this);
  const aria = this.getAttribute ? this.getAttribute('aria-label') || '' : '';
  return JSON.stringify({
    tag: f.tag.toUpperCase(),
    ariaLabel: aria.replace(/\s+/g, ' ').trim(),
    role: f.role,
    name: f.name,
    heading: f.heading,
    text: f.text,
    locator: {
      tag: f.tag,
      type: f.type,
      role: f.role,
      name: f.name,
      testId: f.testId,
      heading: f.heading,
      ancestor: f.ancestor,
      text: f.text.slice(0, textMax),
      rect: f.rect,
    },
  });
}

// Runs INSIDE the page (this = document). Wrapped by pageExpression(). Returns [json, ...elements]: json holds
// the features of every candidate that could be the pinned element and the elements follow it in the same
// order, so a chosen candidate can be fetched without scanning again. Zero-size nodes are skipped: a pin
// target has to be visible.
function scanInPage(featuresOf, loc, textMax) {
  const MAX = 1000;
  const SKIP = ['SCRIPT', 'STYLE', 'HEAD', 'META', 'LINK', 'HTML', 'BODY', 'NOSCRIPT'];
  const features = [];
  const els = [];
  let truncated = false;
  const all = document.querySelectorAll('*');
  for (let n = 0; n < all.length && n < 30000; n++) {
    const el = all[n];
    if (SKIP.indexOf(el.tagName) !== -1) continue;
    const tag = el.tagName.toLowerCase();
    const cheap =
      tag === loc.tag ||
      (loc.role && (el.getAttribute('role') || '').toLowerCase() === loc.role) ||
      (loc.testId && el.matches('[data-testid],[data-test],[data-qa],[data-cy],[id]'));
    if (!cheap || el.getClientRects().length === 0) continue;
    const f = featuresOf(el);
    if (f.tag !== loc.tag && f.role !== loc.role && !(loc.testId && f.testId === loc.testId))
      continue;
    if (els.length >= MAX) {
      truncated = true;
      break;
    }
    f.text = f.text.slice(0, textMax);
    f.i = els.length;
    features.push(f);
    els.push(el);
  }
  return [JSON.stringify({ features, truncated })].concat(els);
}

const SCAN_GROUP = 'gator-web-pin-scan';

function elementFunction(fn) {
  return (
    'function(){ const featuresOf = ' +
    featuresOf.toString() +
    '; return (' +
    fn.toString() +
    ').call(this, featuresOf, ' +
    LOCATOR_TEXT_MAX +
    '); }'
  );
}

function pageExpression(fn, ...args) {
  return (
    '(function(){ const featuresOf = ' +
    featuresOf.toString() +
    '; return (' +
    fn.toString() +
    ').apply(this, [featuresOf].concat(' +
    JSON.stringify(args) +
    ', [' +
    LOCATOR_TEXT_MAX +
    '])); }).call(document)'
  );
}

// Runs INSIDE the page (this = window or document); returns the visible text of the whole view.
function pageTextInPage() {
  const clean = (s) => (s || '').replace(/\n{3,}/g, '\n\n').trim();
  const body = document.body;
  let text = clean(body && body.innerText);
  if (!text) {
    const extras = Array.from(document.querySelectorAll('[aria-label],svg text'))
      .map((x) => (x.getAttribute && x.getAttribute('aria-label')) || x.textContent)
      .filter(Boolean);
    text = clean([body && body.textContent, ...extras].filter(Boolean).join('\n'));
  }
  return JSON.stringify({ text, title: document.title || '', url: location.href });
}

// Keyboard walk through the page's elements, used while picking. Runs in the page with `this`
// as the current element (or nothing before the first step). dir is next | prev | parent |
// child. Returns the element to move to, or null when there is nowhere to go. Closure-free.
function stepInPage(dir) {
  const cur = this && this.nodeType === 1 ? this : null;
  const body = document.body;
  const root = document.documentElement;
  const SKIP = /^(HTML|HEAD|BODY|SCRIPT|STYLE|NOSCRIPT|LINK|META|TEMPLATE)$/;
  const TAGS =
    /^(A|BUTTON|INPUT|SELECT|TEXTAREA|SUMMARY|IMG|SVG|CANVAS|VIDEO|IFRAME|TABLE|UL|OL|FIGURE|ARTICLE|SECTION|ASIDE|NAV|FORM|H[1-6])$/;
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (!(r.width >= 4 && r.height >= 4)) return false;
    if (typeof getComputedStyle !== 'function') return true;
    const s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none';
  };
  const attr = (el, a) => (el.getAttribute && el.getAttribute(a)) || '';
  const meaningful = (el) =>
    !SKIP.test(el.tagName) &&
    visible(el) &&
    (TAGS.test(el.tagName) ||
      !!attr(el, 'role') ||
      !!attr(el, 'aria-label') ||
      !!attr(el, 'data-testid') ||
      (el.children.length === 0 && (el.textContent || '').trim().length > 0));
  const inViewport = (el) => {
    const r = el.getBoundingClientRect();
    return r.bottom > 0 && r.top < window.innerHeight && r.right > 0 && r.left < window.innerWidth;
  };
  const indexIn = (list, n) => Array.prototype.indexOf.call(list, n);
  const after = (n) => {
    if (n.children.length) return n.children[0];
    for (let c = n; c && c !== body; c = c.parentElement) {
      const p = c.parentElement;
      if (!p) return null;
      const i = indexIn(p.children, c);
      if (i + 1 < p.children.length) return p.children[i + 1];
    }
    return null;
  };
  const before = (n) => {
    const p = n.parentElement;
    if (!p) return null;
    const i = indexIn(p.children, n);
    if (i <= 0) return p;
    let d = p.children[i - 1];
    while (d.children.length) d = d.children[d.children.length - 1];
    return d;
  };
  const walk = (start, step, accept) => {
    let n = start;
    for (let guard = 0; n && guard < 20000; guard++) {
      n = step(n);
      if (!n || n === body || n === root) return null;
      if (meaningful(n) && accept(n)) return n;
    }
    return null;
  };
  let found = null;
  if (dir === 'parent') {
    for (let p = cur && cur.parentElement; p && p !== body && p !== root; p = p.parentElement) {
      if (!SKIP.test(p.tagName) && visible(p)) {
        found = p;
        break;
      }
    }
  } else if (dir === 'child') {
    if (cur) {
      const first = (n) => {
        for (let c = after(n); c && cur.contains(c); c = after(c)) {
          if (!SKIP.test(c.tagName) && visible(c)) return c;
        }
        return null;
      };
      found = first(cur);
    }
  } else if (dir === 'next') {
    found = cur ? walk(cur, after, () => true) : walk(body, after, inViewport);
  } else if (dir === 'prev') {
    if (cur) found = walk(cur, before, () => true);
    else {
      for (let n = walk(body, after, inViewport); n; n = walk(n, after, inViewport)) found = n;
    }
  }
  if (found && found.scrollIntoView) found.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  return found;
}

// Runs INSIDE the page (this = element); cheap label facts for the hover banner.
function labelInPage() {
  const el = this;
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const attr = (n, a) => (n.getAttribute && n.getAttribute(a)) || '';
  const nameOf = (n) => {
    const aria = clean(attr(n, 'aria-label'));
    if (aria) return aria;
    const by = attr(n, 'aria-labelledby');
    const labelled = by
      ? clean(
          by
            .split(/\s+/)
            .map((id) => (document.getElementById(id) || {}).textContent || '')
            .join(' '),
        )
      : '';
    if (labelled) return labelled;
    if (n.tagName === 'IMG') return clean(attr(n, 'alt'));
    if (n.labels && n.labels.length) {
      return clean(
        Array.from(n.labels)
          .map((l) => l.textContent)
          .join(' '),
      );
    }
    return '';
  };
  const NESTED =
    'table,[role=table],[role=grid],ul,ol,[role=list],svg,canvas,form,[role=dialog],[role=tablist]';
  const headingIn = (n) => {
    const found = n.querySelectorAll('h1,h2,h3,h4,h5,h6,[role=heading],caption,figcaption,legend');
    for (const h of found) {
      const host = h.closest(NESTED);
      if (host && host !== n && n.contains(host)) continue;
      const t = clean(h.textContent);
      if (t) return t;
    }
    return '';
  };
  let ancestor = '';
  for (let p = el.parentElement, i = 0; p && !ancestor && i < 3; i++, p = p.parentElement) {
    ancestor = nameOf(p) || headingIn(p);
  }
  const name = nameOf(el);
  const heading = headingIn(el);
  const tag = el.tagName.toLowerCase();
  const role = attr(el, 'role').toLowerCase();
  const chartish = (s) => /chart|graph|plot|visual/i.test(s);
  const textFull = clean(el.innerText || el.textContent);
  let kind = 'Section';
  if (el.ownerSVGElement) kind = 'Chart part';
  else if (tag === 'table' || role === 'table' || role === 'grid') kind = 'Table';
  else if (
    tag === 'svg' ||
    tag === 'canvas' ||
    tag === 'img' ||
    tag === 'picture' ||
    role === 'img'
  ) {
    const isChart = chartish(name + ' ' + role + ' ' + attr(el, 'class') + ' ' + ancestor);
    if (tag === 'svg' || tag === 'canvas') kind = isChart ? 'Chart' : 'Graphic';
    else kind = isChart && role === 'img' ? 'Chart' : 'Image';
  } else if (tag === 'video') kind = 'Video';
  else if (tag === 'button' || role === 'button') kind = 'Button';
  else if (tag === 'a' && el.hasAttribute('href')) kind = 'Link';
  else if (
    ['input', 'textarea', 'select'].includes(tag) ||
    role === 'textbox' ||
    role === 'combobox'
  )
    kind = 'Input';
  else if (tag === 'ul' || tag === 'ol' || role === 'list') kind = 'List';
  else if (/^h[1-6]$/.test(tag) || role === 'heading') kind = 'Heading';
  else if (['p', 'span', 'label'].includes(tag) || (textFull && !el.children.length)) kind = 'Text';
  return JSON.stringify({
    name,
    heading,
    text: textFull.slice(0, 200),
    textLen: textFull.length,
    kind,
    ancestor: ancestor.slice(0, 80),
  });
}

const MIN_CONFIDENCE = 0.7;
const MIN_MARGIN = 0.15;
const MIN_EVIDENCE = 0.3;
const GEOMETRY_CAP = 0.7;

function normText(s) {
  return String(s == null ? '' : s)
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

// Values change on a live dashboard and labels do not, so words containing digits are ignored.
function words(s) {
  return new Set(
    normText(s)
      .split(/[^\p{L}\p{N}]+/u)
      .filter((w) => w && !/\d/.test(w)),
  );
}

function similarity(a, b) {
  const na = normText(a);
  const nb = normText(b);
  if (na === nb) return 1;
  const wa = words(na);
  const wb = words(nb);
  if (!wa.size || !wb.size) return 0;
  let inter = 0;
  wa.forEach((w) => {
    if (wb.has(w)) inter++;
  });
  return inter / (wa.size + wb.size - inter);
}

const FINGERPRINT_FIELDS = [
  ['name', 0.25],
  ['heading', 0.25],
  ['text', 0.3],
  ['ancestor', 0.1],
];
const TAG_WEIGHT = 0.1;

// 0..1 for how well a candidate matches the pinned element, or null when the locator carries too little
// semantic evidence (name, heading, text, ancestor) to identify anything by fingerprint.
function fingerprintScore(loc, c) {
  let evidence = 0;
  let got = 0;
  for (const [field, weight] of FINGERPRINT_FIELDS) {
    if (!normText(loc[field])) continue;
    evidence += weight;
    got += weight * similarity(loc[field], c[field]);
  }
  if (evidence < MIN_EVIDENCE) return null;
  const sameKind = loc.tag === c.tag && (loc.type || '') === (c.type || '');
  return (got + (sameKind ? TAG_WEIGHT : 0)) / (evidence + TAG_WEIGHT);
}

function overlapRatio(a, b) {
  if (!a || !b) return 0;
  const w = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x);
  const h = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y);
  if (w <= 0 || h <= 0) return 0;
  const inter = w * h;
  return inter / (a.width * a.height + b.width * b.height - inter);
}

// Decides which candidate, if any, is the element that was pinned. Layers, strongest first: a stable test id,
// role plus accessible name, a semantic fingerprint (name, nearest heading, text, ancestor, element type).
// Position is only a last tie-break between candidates the fingerprint cannot separate, and never identifies
// an element on its own. Every accepted match must be unique; otherwise the pin is reported as missing or
// ambiguous rather than rebound to a guess.
function matchLocator(loc, candidates) {
  const ok = (c, match, confidence) => ({ status: 'ok', index: c.i, match, confidence });
  if (!loc || !Array.isArray(candidates)) return { status: 'element_missing' };
  let pool = candidates;
  if (loc.testId) {
    const hits = pool.filter((c) => c.testId === loc.testId && c.tag === loc.tag);
    if (hits.length === 1) return ok(hits[0], 'stable-id', 0.98);
    if (hits.length > 1) pool = hits;
  }
  if (loc.role && normText(loc.name)) {
    const hits = pool.filter((c) => c.role === loc.role && normText(c.name) === normText(loc.name));
    if (hits.length === 1) return ok(hits[0], 'role-name', 0.9);
    if (hits.length > 1) pool = hits;
  }
  const scored = pool
    .map((c) => ({ c, s: fingerprintScore(loc, c) }))
    .filter((x) => x.s !== null)
    .sort((a, b) => b.s - a.s);
  if (!scored.length || scored[0].s < MIN_CONFIDENCE) return { status: 'element_missing' };
  const best = scored[0];
  const tied = scored.filter((x) => best.s - x.s < MIN_MARGIN);
  if (tied.length === 1) return ok(best.c, 'fingerprint', best.s);
  const near = tied.filter((x) => overlapRatio(loc.rect, x.c.rect) >= 0.5);
  if (near.length === 1) {
    return ok(near[0].c, 'fingerprint-geometry', Math.min(near[0].s, GEOMETRY_CAP));
  }
  return { status: 'element_ambiguous' };
}

// Finds the pinned element on the current page. Resolves to { status: 'ok', backendNodeId, match, confidence }
// or { status: 'element_missing' | 'element_ambiguous' }; it never substitutes another capture.
async function resolveTarget(cdp, locator) {
  if (!locator) return { status: 'element_missing' };
  let scan = null;
  try {
    const ev = await cdp.send('Runtime.evaluate', {
      expression: pageExpression(scanInPage, locator),
      objectGroup: SCAN_GROUP,
    });
    scan = ev && ev.result && ev.result.objectId ? ev.result.objectId : null;
    if (!scan) return { status: 'element_missing' };
    const head = await cdp.send('Runtime.callFunctionOn', {
      objectId: scan,
      functionDeclaration: 'function(){ return this[0]; }',
      returnByValue: true,
    });
    const { features } = JSON.parse(head.result.value);
    const m = matchLocator(locator, features);
    if (m.status !== 'ok') return m;
    const el = await cdp.send('Runtime.callFunctionOn', {
      objectId: scan,
      functionDeclaration: 'function(i){ return this[i + 1]; }',
      arguments: [{ value: m.index }],
      objectGroup: SCAN_GROUP,
    });
    const d = await cdp.send('DOM.describeNode', { objectId: el.result.objectId });
    if (!d || !d.node || !d.node.backendNodeId) return { status: 'element_missing' };
    return {
      status: 'ok',
      backendNodeId: d.node.backendNodeId,
      match: m.match,
      confidence: Math.round(m.confidence * 100) / 100,
    };
  } finally {
    if (scan) {
      await cdp.send('Runtime.releaseObjectGroup', { objectGroup: SCAN_GROUP }).catch(() => {});
    }
  }
}

// Pushpin pointer shown over the page while pin mode is on. The needle tip is the
// hotspot (8,25) so the head sits up-right of the element being picked.
const PIN_CURSOR_HOTSPOT = '8 25';
const PIN_CURSOR_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24">' +
  '<g transform="rotate(45 12 12)" stroke-linejoin="round" stroke-linecap="round">' +
  '<path d="M9 3h6l-.8 6.2L17 12v2H7v-2l2.8-2.8L9 3zM12 14v7" fill="none" stroke="%23fff" stroke-width="3"/>' +
  '<path d="M12 14v7" fill="none" stroke="%230a0f1a" stroke-width="2"/>' +
  '<path d="M12 14v7" fill="none" stroke="%2394a3b8" stroke-width="1"/>' +
  '<path d="M9 3h6l-.8 6.2L17 12v2H7v-2l2.8-2.8L9 3z" fill="%23ef4444" stroke="%230a0f1a" stroke-width="1"/>' +
  '</g></svg>';
// Author origin because Electron's removeInsertedCSS cannot remove user-origin CSS, so a
// user-origin pointer would stay after pin mode ends. The doubled :root outranks the
// page's own !important cursor rules, which are almost always a single tag or class.
const PIN_CURSOR_CSS =
  ':root:root, :root:root * { cursor: url("data:image/svg+xml,' +
  PIN_CURSOR_SVG.replace(/"/g, "'").replace(/</g, '%3C').replace(/>/g, '%3E') +
  '") ' +
  PIN_CURSOR_HOTSPOT +
  ', crosshair !important; }';

module.exports = {
  PIN_CURSOR_CSS,
  MAX_SIDE,
  MAX_TEXT,
  clipFromQuad,
  captureScale,
  capText,
  hoverLabel,
  pickCommand,
  urlMatches,
  featuresOf,
  describeInPage,
  scanInPage,
  elementFunction,
  pageExpression,
  pageTextInPage,
  labelInPage,
  stepInPage,
  matchLocator,
  resolveTarget,
};
