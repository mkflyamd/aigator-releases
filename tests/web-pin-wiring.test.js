// tests/web-pin-wiring.test.js
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const read = (f) => fs.readFileSync(path.join(__dirname, '..', 'shell', f), 'utf8');
const main = read('main.js');
const preload = read('preload.js');
const toolbar = read('toolbar.html');

function after(src, header, len = 700) {
  const i = src.indexOf(header);
  assert.ok(i >= 0, `${header} not found`);
  return src.slice(i, i + len);
}

test('toolbar web-pin channels only accept the main toolbar', () => {
  for (const ch of ['toolbar:web-pin-start', 'toolbar:web-pin-view', 'toolbar:web-pin-cancel']) {
    assert.match(after(main, `ipcMain.on('${ch}'`, 200), /_isMainToolbar\(e\)/, ch);
  }
});

test('web-pin:recapture only accepts the Gator renderer and custom app ids', () => {
  const body = after(main, "ipcMain.handle('web-pin:recapture'");
  assert.match(body, /gatorView\.webContents\.id/);
  assert.match(body, /_customAppIds\.has\(appId\)/);
});

test('custom app panes are created through createCustomApp, not createGenericPane', () => {
  assert.match(main, /for \(const appCfg of _pendingCustomApps\)[\s\S]{0,120}createCustomApp\(appCfg\)/);
  assert.match(after(main, "ipcMain.handle('custom-app:create'", 200), /createCustomApp\(appConfig\)/);
  assert.match(after(main, 'function createCustomApp(', 400), /_customAppIds\.add/);
});

test('picking stops when the active app changes', () => {
  assert.match(after(main, 'function _layoutNow()', 200), /_webPinPicking[\s\S]{0,80}_webPin\.stop\(\)/);
});

test('preload exposes only the three named web-pin methods', () => {
  assert.match(preload, /webPinRecapture: \(appId, locator, url\) =>/);
  assert.match(preload, /onWebPinCaptured:/);
  assert.match(preload, /onWebPinEvent:/);
  assert.doesNotMatch(preload, /ipcRenderer\.on\(\s*channel/);
});

test('toolbar pin controls are no-drag and wired to the three channels', () => {
  assert.match(toolbar, /\.tb-pin-group[\s\S]{0,200}-webkit-app-region: no-drag/);
  assert.match(toolbar, /\.tb-pinbar[\s\S]{0,700}-webkit-app-region: no-drag/);
  for (const ch of ['toolbar:web-pin-start', 'toolbar:web-pin-view', 'toolbar:web-pin-cancel']) {
    assert.ok(toolbar.includes(`'${ch}'`), ch);
  }
});
