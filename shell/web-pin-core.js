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

// Runs INSIDE the page via Runtime.callFunctionOn (this = the element). No closures allowed.
function describeInPage() {
  const el = this;
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const esc = (s) => (window.CSS && CSS.escape ? CSS.escape(s) : s);
  const unique = (sel) => {
    try {
      return document.querySelectorAll(sel).length === 1;
    } catch (e) {
      return false;
    }
  };
  function selectorFor(n) {
    if (n.id && unique('#' + esc(n.id))) return '#' + esc(n.id);
    for (const a of ['data-testid', 'data-test', 'aria-label']) {
      const v = n.getAttribute && n.getAttribute(a);
      if (v) {
        const s = n.tagName.toLowerCase() + '[' + a + '=' + JSON.stringify(v) + ']';
        if (unique(s)) return s;
      }
    }
    const parts = [];
    let cur = n;
    while (cur && cur.nodeType === 1 && cur !== document.documentElement && parts.length < 6) {
      let part = cur.tagName.toLowerCase();
      const sibs = cur.parentElement
        ? Array.from(cur.parentElement.children).filter((c) => c.tagName === cur.tagName)
        : [];
      if (sibs.length > 1) part += ':nth-of-type(' + (sibs.indexOf(cur) + 1) + ')';
      parts.unshift(part);
      const sel = parts.join(' > ');
      if (unique(sel)) return sel;
      cur = cur.parentElement;
    }
    return parts.join(' > ');
  }
  function textOf(n) {
    const t = clean(n.innerText);
    if (t) return t;
    const own = clean(n.textContent);
    const extras = Array.from(n.querySelectorAll('[aria-label],svg text,svg title'))
      .map((x) => clean((x.getAttribute && x.getAttribute('aria-label')) || x.textContent))
      .filter(Boolean);
    return Array.from(new Set([own, ...extras].filter(Boolean))).join('\n');
  }
  function headingFor(n) {
    let cur = n;
    for (let i = 0; cur && i < 5; i++, cur = cur.parentElement) {
      const h = cur.querySelector && cur.querySelector('h1,h2,h3,h4,h5,[role="heading"]');
      if (h && clean(h.textContent)) return clean(h.textContent).slice(0, 80);
    }
    return '';
  }
  const ariaLabel = clean(el.getAttribute && el.getAttribute('aria-label'));
  const role = (el.getAttribute && el.getAttribute('role')) || '';
  const labelledBy = el.getAttribute && el.getAttribute('aria-labelledby');
  const labelledText = labelledBy
    ? clean(
        labelledBy
          .split(/\s+/)
          .map((id) => (document.getElementById(id) || {}).textContent || '')
          .join(' '),
      )
    : '';
  const name =
    ariaLabel ||
    labelledText ||
    clean(el.getAttribute && (el.getAttribute('title') || el.getAttribute('alt')));
  const r = el.getBoundingClientRect();
  const rect = {
    x: Math.round(r.left + window.scrollX),
    y: Math.round(r.top + window.scrollY),
    width: Math.round(r.width),
    height: Math.round(r.height),
  };
  return JSON.stringify({
    tag: el.tagName,
    ariaLabel,
    role,
    name,
    heading: headingFor(el),
    text: textOf(el),
    locator: { selector: selectorFor(el), role, name, rect },
  });
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

async function resolveTarget(cdp, locator) {
  if (!locator) return null;
  if (locator.selector) {
    try {
      const expr =
        '(() => { const n = document.querySelectorAll(' +
        JSON.stringify(locator.selector) +
        '); return n.length === 1 ? n[0] : null; })()';
      const ev = await cdp.send('Runtime.evaluate', { expression: expr });
      if (ev && ev.result && ev.result.subtype === 'node' && ev.result.objectId) {
        const d = await cdp.send('DOM.describeNode', { objectId: ev.result.objectId });
        if (d && d.node && d.node.backendNodeId)
          return { backendNodeId: d.node.backendNodeId, match: 'selector' };
      }
    } catch (e) {
      /* fall through */
    }
  }
  if (locator.role && locator.name) {
    try {
      const doc = await cdp.send('DOM.getDocument', { depth: 0 });
      const ax = await cdp.send('Accessibility.queryAXTree', {
        nodeId: doc.root.nodeId,
        role: locator.role,
        accessibleName: locator.name,
      });
      const nodes = (ax && ax.nodes) || [];
      if (nodes.length === 1 && nodes[0].backendDOMNodeId) {
        return { backendNodeId: nodes[0].backendDOMNodeId, match: 'role-name' };
      }
    } catch (e) {
      /* fall through */
    }
  }
  if (locator.rect) {
    try {
      const sc = await cdp.send('Runtime.evaluate', {
        expression: '({ x: window.scrollX, y: window.scrollY })',
        returnByValue: true,
      });
      const s = (sc && sc.result && sc.result.value) || { x: 0, y: 0 };
      const r = locator.rect;
      const x = Math.round(r.x + r.width / 2 - s.x);
      const y = Math.round(r.y + r.height / 2 - s.y);
      const hit = await cdp.send('DOM.getNodeForLocation', { x, y });
      if (hit && hit.backendNodeId) return { backendNodeId: hit.backendNodeId, match: 'rect' };
    } catch (e) {
      /* fall through */
    }
  }
  return null;
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
  urlMatches,
  describeInPage,
  pageTextInPage,
  labelInPage,
  resolveTarget,
};
