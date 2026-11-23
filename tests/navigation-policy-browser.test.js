const test = require('node:test');
const assert = require('node:assert');
const Module = require('module');

const opened = [];
const realLoad = Module._load;
Module._load = function (request, ...rest) {
  if (request === 'electron') {
    return {
      shell: { openExternal: (url) => (opened.push(url), Promise.resolve()) },
      BrowserWindow: function () {},
    };
  }
  return realLoad.call(this, request, ...rest);
};
const { applyNavigationPolicy } = require('../shell/navigation-policy');
Module._load = realLoad;

function stubView() {
  const loaded = [];
  const wc = {
    loaded,
    handler: null,
    session: {},
    setMaxListeners() {},
    isDestroyed: () => false,
    loadURL: (url) => loaded.push(url),
    setWindowOpenHandler(fn) {
      wc.handler = fn;
    },
    on() {},
  };
  return { webContents: wc };
}
const tick = () => new Promise((r) => setTimeout(r, 5));

test('a browser pane loads outside links in the pane, not the system browser', async () => {
  opened.length = 0;
  const view = stubView();
  applyNavigationPolicy(view, { homeHosts: ['bing.com'], openLinksInPane: true });
  const result = view.webContents.handler({ url: 'https://example.org/page' });
  await tick();
  assert.strictEqual(result.action, 'deny');
  assert.deepStrictEqual(view.webContents.loaded, ['https://example.org/page']);
  assert.deepStrictEqual(opened, []);
});

test('sign-in and blank popups still get a child window in a browser pane', () => {
  const view = stubView();
  applyNavigationPolicy(view, { homeHosts: ['bing.com'], openLinksInPane: true });
  assert.strictEqual(view.webContents.handler({ url: 'https://login.microsoftonline.com/x' }).action, 'allow');
  assert.strictEqual(view.webContents.handler({ url: 'about:blank' }).action, 'allow');
  assert.deepStrictEqual(view.webContents.loaded, []);
});

test('without the option an outside link still goes to the system browser', async () => {
  opened.length = 0;
  const view = stubView();
  applyNavigationPolicy(view, { homeHosts: ['bing.com'] });
  const result = view.webContents.handler({ url: 'https://example.org/page' });
  await tick();
  assert.strictEqual(result.action, 'deny');
  assert.deepStrictEqual(view.webContents.loaded, []);
  assert.deepStrictEqual(opened, ['https://example.org/page']);
});

test('a browser pane never loads non-web schemes from window.open', async () => {
  const view = stubView();
  applyNavigationPolicy(view, { homeHosts: [], openLinksInPane: true });
  const result = view.webContents.handler({ url: 'file:///C:/secret.txt' });
  await tick();
  assert.strictEqual(result.action, 'deny');
  assert.deepStrictEqual(view.webContents.loaded, []);
});
