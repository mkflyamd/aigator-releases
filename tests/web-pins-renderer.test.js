const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const wp = require('../web/static/web-pins.js');
const read = (...p) => fs.readFileSync(path.join(__dirname, '..', ...p), 'utf8');

test('ageLabel buckets', () => {
  const now = 1_000_000_000_000;
  const at = (secAgo) => now / 1000 - secAgo;
  assert.equal(wp.ageLabel(at(5), now), 'just now');
  assert.equal(wp.ageLabel(at(5 * 60), now), '5 min ago');
  assert.equal(wp.ageLabel(at(3 * 3600), now), '3 h ago');
  assert.equal(wp.ageLabel(at(2 * 86400), now), '2 d ago');
  assert.equal(wp.ageLabel(at(-30), now), 'just now');
});

test('isStale flips at 30 minutes', () => {
  const now = 1_000_000_000_000;
  assert.equal(wp.isStale(now / 1000 - 29 * 60, now), false);
  assert.equal(wp.isStale(now / 1000 - 30 * 60, now), true);
});

test('errorMessage covers every shell error code and has a fallback', () => {
  for (const code of ['pane_unavailable', 'pane_not_visible', 'page_mismatch', 'timeout', 'empty_target']) {
    assert.ok(wp.errorMessage(code).length > 10, code);
  }
  assert.equal(wp.errorMessage('something_new'), wp.errorMessage('pane_unavailable'));
});

test('icon is an svg that inherits colour', () => {
  const svg = wp.icon(14);
  assert.match(svg, /^<svg/);
  assert.match(svg, /currentColor/);
  assert.match(svg, /width="14"/);
});

test('renderer never sends a message or falls back to the default tab', () => {
  const src = read('web', 'static', 'web-pins.js');
  assert.ok(!/sendMessage|chat-send|requestSubmit|\.submit\(/.test(src));
  assert.ok(!/['"]default['"]/.test(src));
});

test('app.js renders svg pin icons, a webpin card config and decorates cards', () => {
  const src = read('web', 'static', 'app.js');
  assert.match(src, /iconHtml\.startsWith\('<svg'\)/);
  assert.match(src, /if \(source === 'webpin'\)/);
  assert.match(src, /webpin: \{ icon: window\.WebPins/);
  assert.match(src, /window\.WebPins\.decorateCard\(card, p\)/);
});

test('index.html loads web-pins.js after marketplace-pane.js; css has the new rules', () => {
  const html = read('web', 'static', 'index.html');
  const a = html.indexOf('/static/marketplace-pane.js');
  const b = html.indexOf('/static/web-pins.js');
  assert.ok(a > 0 && b > a);
  const css = read('web', 'static', 'style.css');
  for (const sel of ['.pin-ref-chip.is-stale', '.wp-suggest-chip', '.wp-fly', '.pin-card-icon.has-thumb']) {
    assert.ok(css.includes(sel), sel);
  }
});
