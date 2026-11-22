const test = require('node:test');
const assert = require('node:assert');
const { createStarController } = require('../web/static/custom-app-star.js');

function harness({ failRemove = false } = {}) {
  const log = [];
  const toasts = [];
  const app = { id: 'custom-news', name: 'News', url: 'https://news.example.com' };
  const controller = createStarController({
    api: {
      create: async (name, url) => (log.push(['api.create', name, url]), { ...app, name, url }),
      rename: async (id, name) => (log.push(['api.rename', id, name]), { ...app, name }),
      remove: async (id) => {
        log.push(['api.remove', id]);
        if (failRemove) throw new Error('HTTP 500');
      },
    },
    shell: {
      createCustomApp: async (a) => log.push(['shell.create', a.id]),
      customAppSetHidden: async (id, h) => log.push(['shell.hidden', id, h]),
      customAppTeardown: async (id) => log.push(['shell.teardown', id]),
      customAppOpenRename: (id) => log.push(['shell.openRename', id]),
    },
    ui: {
      registerApp: (a) => log.push(['ui.register', a.id]),
      unregisterApp: (id) => log.push(['ui.unregister', id]),
      relabelApp: (id, n) => log.push(['ui.relabel', id, n]),
      getApp: (id) => (id === app.id ? app : null),
      closeIfActive: (id) => log.push(['ui.close', id]),
      showApp: (id) => log.push(['ui.show', id]),
      reloadList: () => log.push(['ui.reload']),
      toast: (t) => {
        const handle = {
          ...t,
          dismissed: false,
          dismiss() {
            handle.dismissed = true;
          },
        };
        toasts.push(handle);
        return handle;
      },
    },
  });
  return { controller, log, toasts, app };
}

const names = (log) => log.map((l) => l[0]);

test('add creates the app, registers it, shows it and offers Undo', async () => {
  const { controller, log, toasts } = harness();
  await controller.handle({ kind: 'add', url: 'https://news.example.com', name: 'News' });
  assert.deepStrictEqual(names(log), [
    'api.create',
    'shell.create',
    'ui.register',
    'ui.reload',
    'ui.show',
  ]);
  assert.strictEqual(toasts[0].message, 'Added to your web apps');
  assert.deepStrictEqual(
    toasts[0].actions.map((a) => a.label),
    ['Rename', 'Undo'],
  );
});

test('Rename on the add toast opens the toolbar bubble for the new app and keeps it', async () => {
  const { controller, log, toasts } = harness();
  await controller.handle({ kind: 'add', url: 'https://news.example.com', name: 'News' });
  log.length = 0;
  toasts[0].actions[0].run();
  assert.deepStrictEqual(log, [['shell.openRename', 'custom-news']]);
});

test('Undo on the add toast deletes the app for real', async () => {
  const { controller, log, toasts } = harness();
  await controller.handle({ kind: 'add', url: 'https://news.example.com', name: 'News' });
  log.length = 0;
  await toasts[0].actions[1].run();
  assert.deepStrictEqual(names(log), [
    'shell.hidden',
    'ui.close',
    'ui.unregister',
    'api.remove',
    'shell.teardown',
    'ui.reload',
  ]);
});

test('rename patches the app and relabels the dock', async () => {
  const { controller, log } = harness();
  await controller.handle({ kind: 'rename', appId: 'custom-news', name: 'World News' });
  assert.deepStrictEqual(log.slice(0, 2), [
    ['api.rename', 'custom-news', 'World News'],
    ['ui.relabel', 'custom-news', 'World News'],
  ]);
});

test('remove hides the app first and deletes nothing until the Undo window ends', async () => {
  const { controller, log, toasts } = harness();
  await controller.handle({ kind: 'remove', appId: 'custom-news' });
  assert.deepStrictEqual(names(log), ['shell.hidden', 'ui.close', 'ui.unregister']);
  assert.strictEqual(toasts[0].message, 'Removed News from your web apps');
  assert(controller.hasPending());
});

test('Undo restores the pane and the dock entry, reopens the app, and deletes nothing', async () => {
  const { controller, log, toasts } = harness();
  await controller.handle({ kind: 'remove', appId: 'custom-news' });
  log.length = 0;
  await toasts[0].actions[0].run();
  assert.deepStrictEqual(log, [
    ['shell.hidden', 'custom-news', false],
    ['ui.register', 'custom-news'],
    ['ui.show', 'custom-news'],
  ]);
  assert(!controller.hasPending());
  assert(toasts[0].dismissed);
});

test('expiry deletes the app and its pane', async () => {
  const { controller, log, toasts } = harness();
  await controller.handle({ kind: 'remove', appId: 'custom-news' });
  log.length = 0;
  await toasts[0].onExpire();
  assert.deepStrictEqual(names(log), ['api.remove', 'shell.teardown', 'ui.reload']);
  assert(!controller.hasPending());
});

test('a failed delete on expiry unhides the pane, tells the user and relists the app', async () => {
  const warn = console.warn;
  console.warn = () => {};
  try {
    const { controller, log, toasts } = harness({ failRemove: true });
    await controller.handle({ kind: 'remove', appId: 'custom-news' });
    log.length = 0;
    await toasts[0].onExpire();
    assert.deepStrictEqual(log, [
      ['api.remove', 'custom-news'],
      ['shell.hidden', 'custom-news', false],
      ['ui.reload'],
    ]);
    assert.match(toasts[1].message, /Could not remove News/);
    assert(!controller.hasPending());
  } finally {
    console.warn = warn;
  }
});

test('a failed delete on Undo of an add also unhides the pane and tells the user', async () => {
  const warn = console.warn;
  console.warn = () => {};
  try {
    const { controller, log, toasts } = harness({ failRemove: true });
    await controller.handle({ kind: 'add', url: 'https://news.example.com', name: 'News' });
    log.length = 0;
    await toasts[0].actions[1].run();
    assert.deepStrictEqual(names(log), [
      'shell.hidden',
      'ui.close',
      'ui.unregister',
      'api.remove',
      'shell.hidden',
      'ui.reload',
    ]);
    assert.deepStrictEqual(log[4], ['shell.hidden', 'custom-news', false]);
    assert.match(toasts[1].message, /Could not remove News/);
  } finally {
    console.warn = warn;
  }
});

test('a second removal commits the first immediately', async () => {
  const { controller, log } = harness();
  await controller.handle({ kind: 'remove', appId: 'custom-news' });
  log.length = 0;
  await controller.handle({ kind: 'remove', appId: 'custom-news' });
  assert.strictEqual(names(log)[0], 'api.remove');
});

test('custom app names from page titles are never interpolated into innerHTML unescaped', () => {
  const src = require('node:fs').readFileSync(
    require('node:path').join(__dirname, '..', 'web', 'static', 'app.js'),
    'utf8',
  );
  assert(!/\$\{s\.label\}/.test(src), 'slash menu badge escapes the label');
  assert(
    !/aria-label="Remove \$\{skill\.label\}/.test(src),
    'chip aria-label is set through the DOM',
  );
});

test('Settings shows a one-line empty state that teaches the address bar star', () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const js = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');
  assert(
    js.includes(
      'No web apps yet. Open any site, then click the star in the address bar to add it.',
    ),
  );
  assert(js.includes("empty.className = 'custom-apps-empty'"));
});

test('Settings Remove names what is deleted and tears down the pane and saved sign-in', () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const js = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');
  const fn = js.match(/async function _removeCustomApp[\s\S]*?\n\}/)[0];
  assert(fn.includes('/api/web-pins/count?app_id='));
  assert(fn.includes('will be deleted.'));
  assert(fn.includes("'Its settings and saved sign-in'"));
  assert(fn.includes('customAppTeardown(appId)'));
});

test('only one star toast shows at a time and the empty state uses the readable dim text token', () => {
  const read = (...p) =>
    require('node:fs').readFileSync(require('node:path').join(__dirname, '..', ...p), 'utf8');
  const js = read('web', 'static', 'custom-app-star.js');
  assert(/if \(currentToast\) currentToast\.dismiss\(\)/.test(js));
  const css = read('web', 'static', 'style.css');
  assert(/\.custom-apps-empty \{[^}]*color: var\(--text-dim\)/.test(css));
});
