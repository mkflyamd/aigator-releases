// The calendar compose deeplink has no OWA left rail: the shell adds Mail and
// Calendar links there, and removes them once the user is back in the full app.
// Also covers leaving that page (address bar, www.cnn.com) and the new-event popout.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'shell', 'main.js'), 'utf8');
const m = source.match(/const _OUTLOOK_STANDALONE_NAV_SCRIPT = `([\s\S]*?)`;\r?\n/);
assert(m, 'standalone nav script found in shell/main.js');
assert(
  /_syncOutlookStandaloneNav\(outlookView\.webContents\)/.test(source),
  'script is wired to the Outlook view',
);
assert(
  /outlookView\.webContents\.on\('will-prevent-unload', \(e\) => _confirmLeaveOutlookPage\(e, win\)\)/.test(
    source,
  ),
  'the Outlook pane asks Leave/Stay instead of silently cancelling navigation',
);

class FakeEl {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.style = {};
    this.listeners = {};
  }
  appendChild(c) {
    this.children.push(c);
    c.parent = this;
  }
  addEventListener(t, fn) {
    this.listeners[t] = fn;
  }
  remove() {
    this.removed = true;
    this.parent.children = this.parent.children.filter((c) => c !== this);
  }
}

const nav = [];
function run(pathname, body) {
  const document = {
    body,
    createElement: (t) => new FakeEl(t),
    getElementById: (id) => body.children.find((c) => c.id === id) || null,
  };
  vm.runInNewContext(m[1], { document, location: { pathname, assign: (u) => nav.push(u) } });
}

const body = new FakeEl('body');
run('/calendar/0/deeplink/compose', body);
assert.strictEqual(body.children.length, 1, 'bar added on the compose deeplink');
const bar = body.children[0];
assert.deepStrictEqual(
  bar.children.map((b) => b.textContent),
  ['Mail', 'Calendar'],
);

run('/calendar/0/deeplink/compose', body);
assert.strictEqual(body.children.length, 1, 'bar is not added twice');

bar.children[1].listeners.click();
bar.children[0].listeners.click();
assert.deepStrictEqual(nav, ['/calendar/', '/mail/'], 'buttons navigate within OWA');

run('/mail/', body);
assert.strictEqual(body.children.length, 0, 'bar removed outside the compose page');

const other = new FakeEl('body');
run('/mail/', other);
assert.strictEqual(other.children.length, 0, 'no bar on regular Outlook pages');

// Leave/Stay prompt: Leave lets the navigation proceed, Stay keeps the page.
const leaveFn = source.match(
  /function _confirmLeaveOutlookPage\(e, parentWin\) \{[\s\S]*?\r?\n\}\r?\n/,
);
assert(leaveFn, '_confirmLeaveOutlookPage found');
function leavePrompt(choice) {
  const asked = [];
  const fn = vm.runInNewContext(leaveFn[0] + '; _confirmLeaveOutlookPage;', {
    require: () => ({
      dialog: {
        showMessageBoxSync: (parent, opts) => {
          asked.push(opts.buttons);
          return choice;
        },
      },
    }),
  });
  return { fn, asked };
}

// Address bar: typing www.cnn.com on the compose page must navigate there. That page
// has a beforeunload handler, so Electron cancels the load unless will-prevent-unload
// calls preventDefault.
const toolbarHtml = fs.readFileSync(path.join(__dirname, '..', 'shell', 'toolbar.html'), 'utf8');
const normalize = toolbarHtml.match(/if \(!\/\^https\?:[^\n]*navUrl = 'https:\/\/' \+ navUrl;/);
assert(normalize, 'toolbar address bar adds https:// to bare hostnames');
const typedToUrl = (typed) =>
  vm.runInNewContext('var navUrl = typed;' + normalize[0] + ' navUrl', { typed });
assert.strictEqual(typedToUrl('www.cnn.com'), 'https://www.cnn.com');
assert.strictEqual(typedToUrl('http://example.com'), 'http://example.com');

const navHandler = source.match(
  /ipcMain\.on\('toolbar:navigate', (\(e, url\) => \{[\s\S]*?\r?\n\})\);\r?\n\r?\nipcMain\.on\('toolbar:save-custom-app'/,
);
assert(navHandler, 'toolbar:navigate handler found');

const COMPOSE = 'https://outlook.cloud.microsoft/calendar/0/deeplink/compose';

function typeInAddressBar(typed, { beforeUnload, listener }) {
  const page = { url: COMPOSE };
  const wc = {
    isDestroyed: () => false,
    loadURL: async (url) => {
      let cancelled = false;
      if (beforeUnload) {
        cancelled = true;
        if (listener) listener({ preventDefault: () => (cancelled = false) });
      }
      if (!cancelled) page.url = url;
    },
  };
  const handler = vm.runInNewContext('(' + navHandler[1] + ')', {
    _isMainToolbar: () => true,
    viewForApp: () => ({ webContents: wc }),
    activeExternalApp: 'outlook',
    console,
    _liveToolbarWebContents: () => null,
  });
  handler({}, typedToUrl(typed));
  return new Promise((resolve) => setImmediate(() => resolve(page.url)));
}

(async () => {
  const leave = leavePrompt(0);
  assert.strictEqual(
    await typeInAddressBar('www.cnn.com', {
      beforeUnload: true,
      listener: (e) => leave.fn(e, {}),
    }),
    'https://www.cnn.com',
    'www.cnn.com loads after choosing Leave',
  );
  assert.strictEqual(JSON.stringify(leave.asked), JSON.stringify([['Leave', 'Stay']]));

  const stay = leavePrompt(1);
  assert.strictEqual(
    await typeInAddressBar('www.cnn.com', { beforeUnload: true, listener: (e) => stay.fn(e, {}) }),
    COMPOSE,
    'choosing Stay keeps the compose page',
  );

  assert.strictEqual(
    await typeInAddressBar('www.cnn.com', { beforeUnload: true, listener: null }),
    COMPOSE,
    'without a will-prevent-unload handler the load is silently cancelled (the original bug)',
  );
  assert.strictEqual(
    await typeInAddressBar('www.cnn.com', { beforeUnload: false, listener: null }),
    'https://www.cnn.com',
    'pages without unsaved changes navigate straight away',
  );

  // New-event popout: only Outlook https URLs open, in a window on the Outlook session
  // that asks Leave/Stay before closing with unsaved changes.
  const isCompose = vm.runInNewContext(
    source.match(/function _isOutlookComposeUrl\(url\) \{[\s\S]*?\r?\n\}\r?\n/)[0] +
      '; _isOutlookComposeUrl;',
    { URL },
  );
  assert(isCompose('https://outlook.office.com/calendar/0/deeplink/compose?subject=x'));
  assert(isCompose(COMPOSE));
  assert(!isCompose('http://outlook.office.com/calendar/0/deeplink/compose'), 'https only');
  assert(!isCompose('https://outlook.office.com.evil.example/x'), 'host is matched exactly');
  assert(!isCompose('https://www.cnn.com'), 'only Outlook URLs');
  assert(!isCompose('not a url'));
  const popout = source.match(
    /ipcMain\.handle\('outlook-pane:open-compose-window'[\s\S]*?\r?\n\}\);\r?\n/,
  );
  assert(popout, 'popout IPC handler found');
  assert(/session\.fromPartition\(OUTLOOK_PARTITION\)/.test(popout[0]), 'uses the Outlook session');
  assert(/attachToolbarToWindow\(compose\)/.test(popout[0]), 'has the browser toolbar');
  assert(/_confirmLeaveOutlookPage\(e, compose\)/.test(popout[0]), 'asks before discarding edits');
  assert(
    /compose\.on\('closed'[\s\S]*?\.send\('outlook-pane:compose-closed', String\(url\)\)/.test(
      popout[0],
    ),
    'tells the opener when the compose window closes',
  );
  const preload = fs.readFileSync(path.join(__dirname, '..', 'shell', 'preload.js'), 'utf8');
  assert(/openOutlookCompose:[^\n]*outlook-pane:open-compose-window/.test(preload));
  assert(
    /onOutlookComposeClosed:[\s\S]*?ipcRenderer\.on\('outlook-pane:compose-closed'[\s\S]*?ipcRenderer\.removeListener\('outlook-pane:compose-closed'/.test(
      preload,
    ),
    'preload exposes a subscription that can be removed',
  );

  console.log('outlook_standalone_nav ok');
})();
