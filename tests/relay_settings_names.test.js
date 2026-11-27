// Agent messaging settings name agents the way their terminal tabs do, never with a hex id.
// The real functions are cut out of relay-settings.js and run against fake state.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'relay-settings.js'),
  'utf8',
);

function fn(name) {
  const match = source.match(new RegExp(`  function ${name}\\([^)]*\\) \\{[\\s\\S]*?\\n  \\}`));
  assert(match, `${name} not found`);
  return match[0];
}

const code = [
  'baseName',
  'agentName',
  'agentState',
  'agentSummary',
  'sortedAgents',
  'agentShown',
  'agentCounts',
  'projectLabel',
  'pickerText',
  'endName',
  'untilText',
  'pausedReason',
]
  .map(fn)
  .join('\n');

function world(agents, tabs, ui) {
  const ctx = {
    state: { agents },
    ui: ui || { query: '', filter: 'all' },
    _genAgentTerminals: { k: { sessions: tabs || {} } },
    _genAgentLabel: (agent) => agent.charAt(0).toUpperCase() + agent.slice(1),
    Date,
  };
  vm.createContext(ctx);
  vm.runInContext(
    `${code};\nthis.api = { agentName, agentSummary, sortedAgents, agentShown, agentCounts, pickerText, endName, untilText, pausedReason };`,
    ctx,
  );
  return ctx.api;
}

const agent = (id, extra) => ({
  id: `pty:${id}`,
  name: '',
  project_id: 'aigator-releases',
  state: 'live',
  agent: 'claude',
  ...extra,
});

// the tab's own name wins
{
  const a = agent('aaaa1111', { name: 'session title' });
  const api = world([a], { aaaa1111: { label: 'Design head' } });
  assert.strictEqual(api.agentName(a), 'Design head');
}

// no tab: the session title, then "<Agent> session"
{
  const titled = agent('aaaa1111', { name: 'Fix the login bug' });
  const bare = agent('bbbb2222');
  const api = world([titled, bare]);
  assert.strictEqual(api.agentName(titled), 'Fix the login bug');
  assert.strictEqual(api.agentName(bare), 'Claude session');
}

// same name twice reads "Opus" and "Opus (2)"
{
  const first = agent('aaaa1111', { name: 'Opus' });
  const second = agent('bbbb2222', { name: 'Opus' });
  const api = world([first, second]);
  assert.strictEqual(api.agentName(first), 'Opus');
  assert.strictEqual(api.agentName(second), 'Opus (2)');
}

// no name shows a hex id
{
  const agents = [agent('a3267b7a'), agent('4da2bc70')];
  const api = world(agents);
  agents.forEach((a) => assert(!/[0-9a-f]{8}/.test(api.agentName(a)), api.agentName(a)));
}

// summary counts running, sleeping and blocked agents
{
  assert(/^No agents are open/.test(world([]).agentSummary()));
  const one = agent('aaaa1111', { name: 'Opus' });
  assert.strictEqual(
    world([one]).agentSummary(),
    '1 agent is open: 1 running, 0 sleeping. All accept messages.',
  );
  const sleeping = agent('bbbb2222', { name: 'Sonnet', state: 'suspended', opted_out: true });
  assert.strictEqual(
    world([one, sleeping]).agentSummary(),
    '2 agents are open: 1 running, 1 sleeping. 1 blocked.',
  );
}

// running first, then sleeping, then by name; the filter and search narrow the list
{
  const zed = agent('aaaa1111', { name: 'Zed' });
  const abe = agent('bbbb2222', { name: 'Abe', state: 'suspended' });
  const bob = agent('cccc3333', { name: 'Bob', opted_out: true });
  const plain = (v) => JSON.parse(JSON.stringify(v));
  const ids = (api) =>
    plain(
      api
        .sortedAgents()
        .filter(api.agentShown)
        .map((a) => a.id),
    );
  assert.deepStrictEqual(ids(world([abe, zed, bob])), [bob.id, zed.id, abe.id]);
  const sleepingOnly = world([zed, abe, bob], null, { query: '', filter: 'Sleeping' });
  assert.deepStrictEqual(ids(sleepingOnly), [abe.id]);
  const blockedOnly = world([zed, abe, bob], null, { query: '', filter: 'Blocked' });
  assert.deepStrictEqual(ids(blockedOnly), [bob.id]);
  const searched = world([zed, abe, bob], null, { query: ' ZE', filter: 'all' });
  assert.deepStrictEqual(ids(searched), [zed.id]);
  assert.deepStrictEqual(plain(world([zed, abe, bob]).agentCounts()), {
    all: 3,
    Running: 2,
    Sleeping: 1,
    Blocked: 1,
  });
}

// the picker names the project only when agents from several projects are open
{
  const one = agent('aaaa1111', { name: 'Opus' });
  const same = agent('bbbb2222', { name: 'Sonnet' });
  const other = agent('cccc3333', { name: 'Memory leak', project_id: 'other-project' });
  assert.strictEqual(world([one, same]).pickerText(one), 'Opus');
  const api = world([one, same, other]);
  assert.strictEqual(api.pickerText(other), 'Memory leak · other-project');
  assert.strictEqual(api.pickerText(one), 'Opus · aigator-releases');
}

// a pair's end shows the live name while open, else the stored name, else a plain fallback
{
  const open = agent('aaaa1111', { name: 'Opus' });
  const api = world([open]);
  assert.strictEqual(api.endName({ id: open.id, name: 'old' }), 'Opus');
  assert.strictEqual(api.endName({ id: 'pty:gone', name: 'Memory leak' }), 'Memory leak (closed)');
  assert.strictEqual(api.endName({ id: 'pty:gone', name: '' }), 'Closed agent');
}

// pause reasons read as sentences
{
  const api = world([]);
  assert.strictEqual(api.pausedReason({ paused: 'limit_reached' }), 'Hourly limit reached');
  assert.strictEqual(api.pausedReason({ paused: 'repeated' }), 'Same message sent several times');
}

// the deadline names tomorrow when it is not today
{
  const api = world([]);
  const now = new Date();
  const laterToday = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59);
  const nextDay = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 0, 30);
  assert(!/tomorrow/.test(api.untilText(laterToday.toISOString())));
  assert(/^tomorrow /.test(api.untilText(nextDay.toISOString())));
}

console.log('relay settings names: ok');
