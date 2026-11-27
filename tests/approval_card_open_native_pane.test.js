// "Open in Teams/Slack" on an approval card must open the native pane through openThirdPane, the
// same path the dock icons use. Calling gatorShell.showTeams()/showSlack() directly leaves a classic
// third pane (e.g. Calendar) open next to the native tile and squeezes the chat out.
// The real helper is cut out of app.js and run against stubs.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { test } = require('node:test');

const source = fs
  .readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8')
  .replace(/\r\n/g, '\n');

const start = source.indexOf('async function _openNativePinPane');
assert(start >= 0, '_openNativePinPane found in app.js');
const end = source.indexOf('\nfunction ', start + 10);
const helperSource = source.slice(start, end);

function run(service, id, { withOpenThirdPane = true } = {}) {
  const calls = [];
  const gatorShell = {
    showTeams: () => calls.push(['showTeams']),
    showSlack: () => calls.push(['showSlack']),
    navigateTeamsPin: async (x) => calls.push(['navigateTeamsPin', x]),
    navigateSlackPin: async (x) => calls.push(['navigateSlackPin', x]),
  };
  const sandbox = { window: { gatorShell }, calls };
  if (withOpenThirdPane) sandbox.openThirdPane = (type) => calls.push(['openThirdPane', type]);
  vm.createContext(sandbox);
  vm.runInContext(helperSource + '\nthis.fn = _openNativePinPane;', sandbox);
  return sandbox.fn(service, id).then(() => calls);
}

test('teams card opens Teams through openThirdPane, then navigates to the chat', async () => {
  const calls = await run('teams', 'chat-1');
  assert.deepStrictEqual(calls, [
    ['openThirdPane', 'teams'],
    ['navigateTeamsPin', 'chat-1'],
  ]);
});

test('slack card opens Slack through openThirdPane, then navigates to the channel', async () => {
  const calls = await run('slack', 'chan-1');
  assert.deepStrictEqual(calls, [
    ['openThirdPane', 'slack'],
    ['navigateSlackPin', 'chan-1'],
  ]);
});

test('without openThirdPane the shell is called directly before navigating', async () => {
  const teams = await run('teams', 'chat-2', { withOpenThirdPane: false });
  assert.deepStrictEqual(teams, [['showTeams'], ['navigateTeamsPin', 'chat-2']]);
  const slack = await run('slack', 'chan-2', { withOpenThirdPane: false });
  assert.deepStrictEqual(slack, [['showSlack'], ['navigateSlackPin', 'chan-2']]);
});

// After a draft is sent, _gatorNavAfterApproval must also go through openThirdPane. Calling
// gatorShell.showTeams()/showSlack()/showOutlook()/showJira() directly leaves the open coding-agent
// (or any classic) pane beside the native tile and squeezes the chat.
const navStart = source.indexOf('function _gatorNavAfterApproval');
assert(navStart >= 0, '_gatorNavAfterApproval found in app.js');
const navEnd = source.indexOf('\nfunction ', navStart + 10);
const navSource = source.slice(navStart, navEnd);

function runNav(nav, { card = null, jiraNative = true } = {}) {
  const calls = [];
  const record =
    (name) =>
    (...args) =>
      calls.push([name, ...args]);
  const gatorShell = {
    showTeams: record('showTeams'),
    showSlack: record('showSlack'),
    showOutlook: record('showOutlook'),
    showJira: record('showJira'),
    navigateTeamsPin: record('navigateTeamsPin'),
    navigateSlackPin: record('navigateSlackPin'),
    navigateJiraPin: record('navigateJiraPin'),
  };
  const sandbox = {
    window: { gatorShell, _gatorSpinOnPaneOpen: record('spin') },
    openThirdPane: record('openThirdPane'),
    _jiraNativeEnabled: () => jiraNative,
    document: {
      createElement: () => ({
        listeners: {},
        addEventListener(type, fn) {
          this.listeners[type] = fn;
        },
      }),
    },
    calls,
  };
  vm.createContext(sandbox);
  vm.runInContext(navSource + '\nthis.fn = _gatorNavAfterApproval;', sandbox);
  sandbox.fn(nav, card);
  return { calls, sandbox };
}

test('teams: sent draft opens Teams through openThirdPane, then navigates to the chat', () => {
  const { calls } = runNav({ app: 'teams', chat_id: 'chat-1' });
  assert.deepStrictEqual(calls, [
    ['openThirdPane', 'teams'],
    ['navigateTeamsPin', 'chat-1'],
  ]);
});

test('slack: sent draft opens Slack through openThirdPane, then navigates to channel:thread', () => {
  const { calls } = runNav({ app: 'slack', channel_id: 'C1', thread_ts: '1.2' });
  assert.deepStrictEqual(calls, [
    ['openThirdPane', 'slack'],
    ['navigateSlackPin', 'C1:1.2'],
  ]);
  const channelOnly = runNav({ app: 'slack', channel_id: 'C2' });
  assert.deepStrictEqual(channelOnly.calls, [
    ['openThirdPane', 'slack'],
    ['navigateSlackPin', 'C2'],
  ]);
});

test('outlook maps to the email pane type and has nothing to navigate to', () => {
  const { calls } = runNav({ app: 'outlook' });
  assert.deepStrictEqual(calls, [['openThirdPane', 'email']]);
});

test('jira (native): opens through openThirdPane, then deep-links the issue', () => {
  const { calls } = runNav({ app: 'jira', url: 'https://jira.example.com/browse/AG-1' });
  assert.deepStrictEqual(calls, [
    ['openThirdPane', 'jira'],
    ['navigateJiraPin', 'https://jira.example.com/browse/AG-1'],
  ]);
});

test('jira (classic pane): opens the in-Gator pane and leaves the native Jira view alone', () => {
  const { calls } = runNav(
    { app: 'jira', url: 'https://jira.example.com/browse/AG-1' },
    { jiraNative: false },
  );
  assert.deepStrictEqual(calls, [['openThirdPane', 'jira']]);
});

test('no direct gatorShell.show*() call and no second pane-open spin sync', () => {
  for (const nav of [
    { app: 'teams', chat_id: 'c' },
    { app: 'slack', channel_id: 'C' },
    { app: 'outlook' },
    { app: 'jira', url: 'https://jira.example.com/browse/AG-1' },
  ]) {
    const names = runNav(nav).calls.map((c) => c[0]);
    assert(!names.some((n) => /^show/.test(n)), `${nav.app}: direct show call in ${names}`);
    assert(!names.includes('spin'), `${nav.app}: openThirdPane already syncs the spin`);
  }
});

test('the "View in" link re-runs the same path; a null card does not throw', () => {
  const footer = {
    appended: null,
    appendChild(el) {
      this.appended = el;
    },
  };
  const card = { querySelector: (sel) => (sel === '.gcc-footer' ? footer : null) };
  const { calls, sandbox } = runNav({ app: 'teams', chat_id: 'chat-1' }, { card });
  assert(footer.appended, 'View link appended to the card footer');
  calls.length = 0;
  footer.appended.listeners.click({ preventDefault() {} });
  assert.deepStrictEqual(calls, [
    ['openThirdPane', 'teams'],
    ['navigateTeamsPin', 'chat-1'],
  ]);
  assert.doesNotThrow(() => sandbox.fn({ app: 'slack', channel_id: 'C' }, null));
});
