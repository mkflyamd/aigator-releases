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
