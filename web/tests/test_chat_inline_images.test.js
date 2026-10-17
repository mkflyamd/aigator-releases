/**
 * Chat renders generated images inline instead of as bare links.
 *
 * applyInline must turn ![alt](url) into an <img> only for /api/files/ paths and
 * allowlisted https hosts; every other URL stays a plain link so model output
 * cannot beacon data out through an image request. A failed image is swapped for
 * an "unavailable" card by a delegated capture-phase listener (CSP forbids inline
 * onerror handlers).
 */

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.js'), 'utf8');

function slice(startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  assert.notStrictEqual(start, -1, `${startMarker} must exist in app.js`);
  const end = source.indexOf(endMarker, start);
  assert.notStrictEqual(end, -1, `${endMarker} must follow ${startMarker}`);
  return source.slice(start, end);
}

const code =
  slice('function escapeHtml(', '\n}\n') +
  '\n}\n' +
  slice('function gatorActionAttrs(', '\n}\n') +
  '\n}\n' +
  slice('const INLINE_IMAGE_HOSTS', '\n// ── end inline images') +
  '\nthis.applyInline = applyInline;';
const ctx = { window: {}, URL };
vm.createContext(ctx);
vm.runInContext(code, ctx);
const render = (md) => ctx.applyInline(ctx.escapeHtml ? ctx.escapeHtml(md) : md);

const TXT2IMG = 'https://mcp-platform.amd.com/mcp/txt2img/images/a42668ca.png?token=abc.def&x=1';

(function allowedHostRendersImage() {
  const out = render(`![flower](${TXT2IMG})`);
  assert.ok(out.includes('<img '), `expected <img>, got: ${out}`);
  assert.ok(out.includes('class="chat-inline-img"'), out);
  assert.ok(out.includes('alt="flower"'), out);
  assert.ok(out.includes('referrerpolicy="no-referrer"'), out);
  assert.ok(
    out.includes(
      'src="/api/inline-image?url=https%3A%2F%2Fmcp-platform.amd.com%2Fmcp%2Ftxt2img%2Fimages%2Fa42668ca.png%3Ftoken%3Dabc.def%26x%3D1"',
    ),
    `remote images must load through the caching proxy: ${out}`,
  );
  assert.ok(
    out.includes(
      'data-orig-src="https://mcp-platform.amd.com/mcp/txt2img/images/a42668ca.png?token=abc.def&amp;x=1"',
    ),
    `original URL must be kept for download/save: ${out}`,
  );
  assert.ok(!out.includes('<a '), `image must not also be linkified: ${out}`);
})();

(function imageHasDownloadAndSaveActions() {
  const out = render('![chart](/api/files/r/chart.png)');
  assert.ok(out.includes('class="chat-inline-img-wrap is-loading"'), out);
  assert.ok(out.includes('class="chat-inline-img-actions"'), out);
  assert.ok(/data-call="gatorImageDownload"/.test(out), `no Download action: ${out}`);
  assert.ok(/data-call="gatorImageSave"/.test(out), `no Save action: ${out}`);
  assert.ok(!/\sonclick=/i.test(out), 'inline handlers are blocked by CSP');
  assert.ok(!out.includes('<a '), 'actions are buttons, not links');
})();

(function actionsAreWiredAndAllowlisted() {
  const allow = slice('const GATOR_ACTIONS', ']);');
  assert.ok(allow.includes("'gatorImageDownload'"), 'gatorImageDownload not in GATOR_ACTIONS');
  assert.ok(allow.includes("'gatorImageSave'"), 'gatorImageSave not in GATOR_ACTIONS');
  const handlers = slice('async function _fetchChatImage(', '\n// ── end inline images');
  assert.ok(handlers.includes("'/api/inline-image?url='"), 'download must use the proxy route');
  assert.ok(handlers.includes("'/api/inline-image/save'"), 'Save as must use the save route');
  assert.ok(!handlers.includes('showSaveFilePicker'), 'Electron lacks a reliable save picker');
})();

(function apiFilesPathRendersImage() {
  const out = render('![chart](/api/files/4163339f0736/chart.png)');
  assert.ok(out.includes('<img '), out);
  assert.ok(out.includes('src="/api/files/4163339f0736/chart.png"'), out);
  assert.ok(!out.includes('file-temp-tag'), `no link marker on an image: ${out}`);
})();

(function otherHostsStayLinks() {
  for (const url of [
    'https://evil.example/pixel.png?d=secret',
    'https://mcp-platform.amd.com.evil.example/x.png',
    'https://mcp-platform.amd.com@evil.example/x.png',
    'http://mcp-platform.amd.com/x.png',
    '/api/other/endpoint',
    '/api/files/../secret',
  ]) {
    const out = render(`![x](${url})`);
    assert.ok(!out.includes('<img'), `must not render <img> for ${url}: ${out}`);
    assert.ok(!out.includes('!<a'), `stray "!" before link for ${url}: ${out}`);
    assert.ok(out.includes('<a '), `must fall back to a link for ${url}: ${out}`);
  }
})();

(function altTextCannotBreakOutOfAttribute() {
  const out = render('![a" onerror="x](/api/files/r/f.png)');
  assert.ok(!/alt="a" onerror/.test(out), `alt broke out of its attribute: ${out}`);
  assert.ok(out.includes('&quot;'), out);
})();

(function jiraKeyInAltDoesNotCorruptTag() {
  ctx.window.GATOR_JIRA_URL = 'https://jira.example';
  const out = render('![PROJ-123 diagram](/api/files/r/f.png)');
  assert.ok(!/alt="[^"]*<a /.test(out), `Jira autolink leaked into alt: ${out}`);
  ctx.window.GATOR_JIRA_URL = undefined;
})();

(function plainMarkdownLinkUnchanged() {
  const out = render('[doc](https://example.com/a)');
  assert.ok(out.includes('<a href="https://example.com/a"'), out);
  assert.ok(!out.includes('<img'), out);
})();

// ── Broken-image UX wiring (source inspection; no DOM in this harness) ─────────

(function loadingPlaceholderIsClearedOnLoad() {
  assert.ok(render('![x](/api/files/r/f.png)').includes('chat-inline-img-wrap is-loading'));
  assert.ok(
    /document\.addEventListener\(\s*'load'[\s\S]{0,400}?remove\('is-loading'\)[\s\S]{0,40}?,\s*true,?\s*\)/.test(
      source,
    ),
    'app.js must clear is-loading from a capture-phase load listener',
  );
})();

(function brokenImageHandlerIsDelegatedAndCspSafe() {
  assert.ok(
    /document\.addEventListener\(\s*'error'[\s\S]{0,400}?,\s*true,?\s*\)/.test(source),
    "app.js must register a capture-phase document 'error' listener for inline images",
  );
  const rendered = slice('const INLINE_IMAGE_HOSTS', '\n// ── end inline images');
  assert.ok(!/onerror\s*=/.test(rendered), 'inline onerror attribute is blocked by CSP');
  assert.ok(rendered.includes('chat-img-broken'), 'broken-image card class missing');
  assert.ok(!rendered.includes('Retry'), 'expired images cannot be retried');
  assert.ok(!rendered.includes('Open link'), 'expired links do not open');
})();

console.log('ok');
