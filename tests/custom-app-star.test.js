const test = require('node:test');
const assert = require('node:assert');
const { createStarController } = require('../web/static/custom-app-star.js');

function harness() {
  const log = [];
  const toasts = [];
  const app = { id: 'custom-news', name: 'News', url: 'https://news.example.com' };
  const controller = createStarController({
    api: {
      create: async (name, url) => (log.push(['api.create', name, url]), { ...app, name, url }),
      rename: async (id, name) => (log.push(['api.rename', id, name]), { ...app, name }),
      remove: async (id) => log.push(['api.remove', id]),
    },
    shell: {
      createCustomApp: async (a) => log.push(['shell.create', a.id]),
      customAppSetHidden: async (id, h) => log.push(['shell.hidden', id, h]),
      customAppTeardown: async (id) => log.push(['shell.teardown', id]),
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
        const handle = { ...t, dismissed: false, dismiss() { handle.dismissed = true; } };
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
  assert.deepStrictEqual(names(log), ['api.create', 'shell.create', 'ui.register', 'ui.reload', 'ui.show']);
  assert.strictEqual(toasts[0].message, 'Added to Gator apps');
  assert.deepStrictEqual(toasts[0].actions.map((a) => a.label), ['Undo']);
});

test('Undo on the add toast deletes the app for real', async () => {
  const { controller, log, toasts } = harness();
  await controller.handle({ kind: 'add', url: 'https://news.example.com', name: 'News' });
  log.length = 0;
  await toasts[0].actions[0].run();
  assert.deepStrictEqual(names(log), [
    'shell.hidden', 'ui.close', 'ui.unregister', 'api.remove', 'shell.teardown', 'ui.reload',
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
  assert.strictEqual(toasts[0].message, 'Removed News from Gator apps');
  assert(controller.hasPending());
});

test('Undo restores the pane and the dock entry without deleting', async () => {
  const { controller, log, toasts } = harness();
  await controller.handle({ kind: 'remove', appId: 'custom-news' });
  log.length = 0;
  toasts[0].actions[0].run();
  assert.deepStrictEqual(log, [['shell.hidden', 'custom-news', false], ['ui.register', 'custom-news']]);
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

test('a second removal commits the first immediately', async () => {
  const { controller, log } = harness();
  await controller.handle({ kind: 'remove', appId: 'custom-news' });
  log.length = 0;
  await controller.handle({ kind: 'remove', appId: 'custom-news' });
  assert.strictEqual(names(log)[0], 'api.remove');
});
