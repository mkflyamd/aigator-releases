const assert = require('assert');
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

// Model-generated widget HTML runs in an opaque origin: scripts yes, same-origin never.
const sandboxes = [...src.matchAll(/class="gator-widget-frame" sandbox="([^"]*)"/g)].map((m) => m[1]);
assert.strictEqual(sandboxes.length, 1, 'one widget frame template');
const tokens = sandboxes[0].split(/\s+/);
assert.ok(tokens.includes('allow-scripts'), 'widget scripts still run');
assert.ok(!tokens.includes('allow-same-origin'), 'widget frames have an opaque origin');
for (const t of tokens) {
  assert.ok(
    ['allow-scripts', 'allow-forms', 'allow-modals', 'allow-pointer-lock'].includes(t),
    'unexpected sandbox token ' + t
  );
}

// No widget frame in any front-end file regains same-origin through another template.
for (const f of ['app.js', 'demo-media.js']) {
  const text = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', f), 'utf8');
  const sandboxed = [...text.matchAll(/sandbox="([^"]*)"/g)].map((m) => m[1]);
  for (const s of sandboxed) {
    assert.ok(!/allow-same-origin/.test(s), f + ' has a sandbox with allow-same-origin: ' + s);
  }
}

// The frame script is nonced like the other inline widget script, so it runs under the page CSP.
assert.ok(
  /<script nonce="\$\{window\.__CSP_NONCE__ \|\| ''\}">window\._GATOR="\$\{_gatorOrigin\}";\$\{gatorWidgetFrameScript\(\)\}\$\{gatorWidgetStorageScript\(gatorWidgetStoreLoad\(_storeKey\)\)\}<\\\/script>/.test(src),
  'resize script is injected in the nonced script'
);

// No parent code reads the widget document or the CSRF token on a widget's behalf.
assert.ok(!/\.contentDocument/.test(src.replace(/third-pane/g, '')), 'app.js never reads a frame contentDocument');

console.log('widget_sandbox: PASS');
