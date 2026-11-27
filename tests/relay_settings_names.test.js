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

const code = ['baseName', 'agentName', 'agentState', 'agentContext', 'endName', 'untilText']
  .map(fn)
  .join('\n');

function world(agents, tabs) {
  const ctx = {
    state: { agents },
    _genAgentTerminals: { k: { sessions: tabs || {} } },
    _genAgentLabel: (agent) => agent.charAt(0).toUpperCase() + agent.slice(1),
    Date,
  };
  vm.createContext(ctx);
  vm.runInContext(`${code};\nthis.api = { agentName, agentContext, endName, untilText };`, ctx);
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

// context line is project and state
{
  const sleeping = agent('aaaa1111', { state: 'suspended' });
  const api = world([sleeping]);
  assert.strictEqual(api.agentContext(sleeping), 'aigator-releases · Sleeping');
}

// a pair's end shows the live name while open, else the stored name, else a plain fallback
{
  const open = agent('aaaa1111', { name: 'Opus' });
  const api = world([open]);
  assert.strictEqual(api.endName({ id: open.id, name: 'old' }), 'Opus');
  assert.strictEqual(api.endName({ id: 'pty:gone', name: 'Memory leak' }), 'Memory leak');
  assert.strictEqual(api.endName({ id: 'pty:gone', name: '' }), 'A closed agent');
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
