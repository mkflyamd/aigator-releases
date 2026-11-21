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
  const t = String(text == null ? '' : text).replace(/\n{3,}/g, '\n\n').trim();
  if (t.length <= max) return t;
  return t.slice(0, max - TRUNC.length) + TRUNC;
}

function hoverLabel(info) {
  const i = info || {};
  const raw = i.ariaLabel || i.role || i.heading || (i.tag ? String(i.tag).toLowerCase() : '') || 'element';
  const s = String(raw).replace(/\s+/g, ' ').trim();
  return s.length > 60 ? s.slice(0, 59) + '…' : s;
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
    try { return document.querySelectorAll(sel).length === 1; } catch (e) { return false; }
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
    ? clean(labelledBy.split(/\s+/).map((id) => (document.getElementById(id) || {}).textContent || '').join(' '))
    : '';
  const name = ariaLabel || labelledText || clean(el.getAttribute && (el.getAttribute('title') || el.getAttribute('alt')));
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

// Runs INSIDE the page (this = element); cheap label info for the hover banner.
function labelInPage() {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const el = this;
  let heading = '';
  for (let cur = el, i = 0; cur && !heading && i < 5; i++, cur = cur.parentElement) {
    const h = cur.querySelector && cur.querySelector('h1,h2,h3,h4,h5,[role="heading"]');
    if (h) heading = clean(h.textContent).slice(0, 80);
  }
  return JSON.stringify({
    ariaLabel: clean(el.getAttribute && el.getAttribute('aria-label')),
    role: (el.getAttribute && el.getAttribute('role')) || '',
    heading,
    tag: el.tagName,
  });
}

async function resolveTarget(cdp, locator) {
  if (!locator) return null;
  if (locator.selector) {
    try {
      const expr =
        '(() => { const n = document.querySelectorAll(' + JSON.stringify(locator.selector) +
        '); return n.length === 1 ? n[0] : null; })()';
      const ev = await cdp.send('Runtime.evaluate', { expression: expr });
      if (ev && ev.result && ev.result.subtype === 'node' && ev.result.objectId) {
        const d = await cdp.send('DOM.describeNode', { objectId: ev.result.objectId });
        if (d && d.node && d.node.backendNodeId) return { backendNodeId: d.node.backendNodeId, match: 'selector' };
      }
    } catch (e) { /* fall through */ }
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
    } catch (e) { /* fall through */ }
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
    } catch (e) { /* fall through */ }
  }
  return null;
}

module.exports = {
  MAX_SIDE, MAX_TEXT, clipFromQuad, captureScale, capText, hoverLabel, urlMatches,
  describeInPage, pageTextInPage, labelInPage, resolveTarget,
};
