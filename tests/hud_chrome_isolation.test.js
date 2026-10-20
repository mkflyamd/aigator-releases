const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'shell', 'main.js'), 'utf8').replace(/\r\n/g, '\n');

// The pop-out window injects its titlebar into whatever HTML the widget is. Run the real injection.
const start = source.indexOf('const hudCSS = `');
const endMarker = "  if (!html.includes('</body>')) shell = shell + hudStateScript + resizeScript;\n";
const end = source.indexOf(endMarker);
assert.ok(start > 0 && end > start, 'HUD injection block not found in shell/main.js');
const block = source.slice(start, end + endMarker.length);

function inject(html) {
  const ctx = { html, _hudIconUrl: 'file:///icon.png', GATOR_URL: 'http://127.0.0.1:1' };
  vm.runInNewContext(block + '\nthis.shell = shell; this.hudCSS = hudCSS; this.titlebar = titlebar;', ctx);
  return ctx;
}

const { hudCSS, titlebar } = inject('<div>w</div>');

// Widget CSS shares the document with the chrome, so the chrome must not live in it: a widget rule such as
// button{padding:8px 16px} or a fixed z-index:99999 header would otherwise squeeze or cover the controls.
assert.ok(!/#_hud_bar|\._hud_cb|#_hud_controls/.test(hudCSS), 'chrome rules must be in the shadow root, not the document stylesheet');
assert.ok(/<div id="_hud_host" style="[^"]*"><template shadowrootmode="open"><style>/.test(titlebar), 'titlebar is a shadow host');
const hostStyle = titlebar.match(/id="_hud_host" style="([^"]*)"/)[1];
const decls = hostStyle.split(';').filter(Boolean);
assert.ok(decls.length >= 8 && decls.every((d) => d.endsWith('!important')), 'every host declaration is !important: ' + hostStyle);
for (const need of ['all:initial', 'position:fixed', 'z-index:2147483647', 'opacity:1', 'display:block']) {
  assert.ok(decls.includes(need + '!important'), 'host sets ' + need);
}
for (const id of ['_hud_bar', '_hud_controls', '_hud_min', '_hud_max', '_hud_close']) {
  assert.ok(titlebar.indexOf('id="' + id + '"') > titlebar.indexOf('<template'), id + ' is inside the shadow root');
}
assert.ok(/body\._hud_minimized > \*:not\(#_hud_host\)/.test(hudCSS), 'minimizing hides the widget but keeps the chrome host');

// Full documents and bare fragments both get the chrome and the minimize/resize scripts, once.
const shapes = {
  fullDoc: ['<!DOCTYPE html><html><head><style>button{padding:8px 16px}</style></head><body><button>Go</button></body></html>', '<button>Go</button>'],
  fragment: ['<div style="padding:12px"><button style="padding:7px 16px">Post</button></div>', '<button style="padding:7px 16px">Post</button>'],
  bodyAttrs: ['<html><head></head><body class="x"><p>hi</p></body></html>', '<p>hi</p>'],
};
for (const [name, [html, marker]] of Object.entries(shapes)) {
  const { shell } = inject(html);
  assert.strictEqual(shell.split('id="_hud_host"').length - 1, 1, name + ': one chrome host');
  assert.strictEqual(shell.split("classList.add('_hud_minimized')").length - 1, 1, name + ': minimize state script injected once');
  assert.strictEqual(shell.split('hudControls.resizeTo').length - 1, 1, name + ': resize script injected once');
  assert.ok(shell.includes(marker), name + ': widget content kept');
}

console.log('hud_chrome_isolation: PASS');
