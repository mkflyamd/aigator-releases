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
  for (const ch of [
    'toolbar:web-pin-start',
    'toolbar:web-pin-view',
    'toolbar:web-pin-cancel',
    'toolbar:web-pin-key',
  ]) {
    assert.match(after(main, `ipcMain.on('${ch}'`, 200), /_isMainToolbar\(e\)/, ch);
  }
});

test('web-pin:recapture only accepts the Gator renderer and pinnable pane ids', () => {
  const body = after(main, "ipcMain.handle('web-pin:recapture'");
  assert.match(body, /gatorView\.webContents\.id/);
  assert.match(body, /_isPinnablePane\(appId\)/);
});

test('pinnable panes are custom apps plus the built-in browser pane, nothing else', () => {
  assert.match(main, /const _PINNABLE_BUILTIN_PANES = new Set\(\['browser'\]\);/);
  assert.match(
    main,
    /const _isPinnablePane = \(id\) => _customAppIds\.has\(id\) \|\| _PINNABLE_BUILTIN_PANES\.has\(id\);/,
  );
  assert.match(main, /pinnable: _isPinnablePane\(app\)/);
  assert.match(
    after(main, 'getPane', 300),
    /_isPinnablePane\(appId\) \? _genericPanes\[appId\] : null/,
  );
  assert.match(
    main,
    /if \(_isPinnablePane\(activeExternalApp\)\) _webPin\.start\(activeExternalApp\)/,
  );
  assert.match(
    main,
    /if \(_isPinnablePane\(activeExternalApp\)\) _webPin\.pinView\(activeExternalApp\)/,
  );
  assert.match(toolbar, /\.tb\.is-pinnable \.tb-pin-group/);
  assert.match(toolbar, /state\.pinnable === 'boolean'/);
});

test('custom app panes are created through createCustomApp, not createGenericPane', () => {
  assert.match(
    main,
    /for \(const appCfg of _pendingCustomApps\)[\s\S]{0,120}createCustomApp\(appCfg\)/,
  );
  assert.match(
    after(main, "ipcMain.handle('custom-app:create'", 200),
    /createCustomApp\(appConfig\)/,
  );
  assert.match(after(main, 'function createCustomApp(', 400), /_customAppIds\.add/);
});

test('picking stops when the active app changes', () => {
  assert.match(
    after(main, 'function _layoutNow()', 200),
    /_webPinPicking[\s\S]{0,80}_webPin\.stop\(\)/,
  );
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

test('pin banner keeps its exit visible and gives a live label the room', () => {
  assert.match(toolbar, /\.tb-pinbar \.tb-btn[\s\S]{0,40}flex: 0 0 auto/);
  assert.match(toolbar, /\.tb-pinbar\.has-label \.tb-pinbar-prompt/);
  assert.match(toolbar, /classList\.toggle\('has-label'/);
  assert.match(
    toolbar,
    /@media \(max-width: 400px\)[\s\S]{0,200}\.tb-pinbar:not\(\.has-label\) \.tb-pinbar-prompt-short/,
  );
  assert.match(toolbar, /@media \(max-width: 520px\)[\s\S]{0,60}\.tb-pinbar-hint/);
  assert.match(toolbar, /\[data-theme='light'\] \.tb-pinbar-label[\s\S]{0,40}#15803d/);
});

test('pin banner shows the hovered kind dimly, hides it before the label truncates, and stays quiet for screen readers', () => {
  assert.match(toolbar, /id="tb-pinbar-label" aria-live="off"/);
  assert.match(toolbar, /id="tb-pinbar-kind" aria-live="off"/);
  assert.match(toolbar, /\.tb-pinbar-kind \{[^}]*flex: 0 0 auto;[^}]*var\(--text-dim\)/);
  assert.match(
    toolbar,
    /@media \(max-width: 480px\)[\s\S]{0,80}\.tb-pinbar\.has-kind \.tb-pinbar-kind[\s\S]{0,40}display: none/,
  );
  assert.match(toolbar, /classList\.toggle\('has-kind'/);
  assert.doesNotMatch(toolbar, /\.tb-pinbar-(label|kind)[^{]*\{[^}]*transition/);
  assert.match(main, /pinKind: _webPinKind/);
});

test('web-pin:go-to is gatorView-only, pinnable-pane-only, http(s)-only and limited to the pane home hosts except for built-in browser panes', () => {
  const body = after(main, "ipcMain.handle('web-pin:go-to'", 1700);
  assert.match(body, /gatorView\.webContents\.id/);
  assert.match(body, /_isPinnablePane\(appId\)/);
  assert.match(body, /'https:'/);
  // loadURL skips will-navigate, so a custom pane's own host restriction is re-applied here.
  // A built-in browser pane has no home site, so it is exempt.
  assert.match(
    body,
    /!_PINNABLE_BUILTIN_PANES\.has\(appId\) &&\s*\(!pane\.homeHosts\.length \|\| !_hostMatches\(parsed\.hostname, pane\.homeHosts\)\)/,
  );
  assert.match(
    body,
    /new URL\(pane\.url\)\.protocol === 'https:' && parsed\.protocol !== 'https:'/,
  );
  assert.doesNotMatch(body, /startsWith\('https:'\)/);
  assert.match(
    after(main, 'function createGenericPane(', 1800),
    /_genericPanes\[id\] = \{[^}]*homeHosts/,
  );
  assert.match(preload, /webPinGoTo: \(appId, url\) => ipcRenderer\.invoke\('web-pin:go-to'/);
});

test('keyboard picking: toolbar forwards Tab, arrows and Enter only while picking, and the cancel button keeps Enter', () => {
  assert.match(toolbar, /PIN_KEYS = new Set\(\['Tab', 'ArrowUp', 'ArrowDown', 'Enter'\]\)/);
  assert.match(
    toolbar,
    /classList\.contains\('is-pinning'\)[\s\S]{0,120}PIN_KEYS\.has\(e\.key\)[\s\S]{0,160}tb-pinbar-cancel[\s\S]{0,200}toolbar:web-pin-key/,
  );
  const body = after(main, "ipcMain.on('toolbar:web-pin-key'", 700);
  assert.match(body, /_webPinPicking/);
  assert.match(body, /_webPin\.key\(/);
});

test('pick mode is announced through a polite live region outside the hidden banner', () => {
  assert.match(toolbar, /id="tb-pin-live" role="status" aria-live="polite"/);
  assert.match(toolbar, /\.tb-pin-live \{[^}]*position: absolute[^}]*clip:/);
  assert.match(toolbar, /state\.pinAnnounce/);
  assert.match(main, /pinAnnounce: _webPinAnnounce/);
  // Sent with one push only, so a later state push does not repeat it.
  assert.match(
    main,
    /_webPinAnnounce = announce \|\| '';\s*_toolbarPushState\(\);\s*_webPinAnnounce = '';/,
  );
});

test('focus returns to the Pin button when picking ends, and Esc only cancels picking', () => {
  assert.match(
    toolbar,
    /wasPinning && !state\.pinMode && document\.hasFocus\(\)\) elPin\.focus\(\)/,
  );
  assert.match(
    toolbar,
    /e\.key === 'Escape' && elBar\.classList\.contains\('is-pinning'\)\) \{\s*ipcRenderer\.send\('toolbar:web-pin-cancel'\)/,
  );
});
