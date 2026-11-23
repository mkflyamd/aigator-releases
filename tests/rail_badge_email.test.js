// Email rail badge: every writer goes through publishEmailBadge, and the desktop Outlook count
// wins when the app has one. The real functions are cut out of app.js and run against a stub badge.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function functionSource(name) {
  const start = source.indexOf(`function ${name}(`);
  assert(start > 0, `${name} found in app.js`);
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i++) {
    if (source[i] === '{') depth++;
    if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`${name} not closed`);
}

function load() {
  const badges = {};
  const ctx = {
    window: {},
    updateRailBadge: (id, n) => {
      badges[id] = n;
    },
  };
  vm.createContext(ctx);
  for (const fn of ['teamsBadgeCount', 'publishTeamsBadge', 'publishEmailBadge', 'updateNativeBadge']) {
    vm.runInContext(functionSource(fn), ctx);
  }
  return { ctx, badges };
}

// No Outlook count: the Graph total is shown.
{
  const { ctx, badges } = load();
  ctx.publishEmailBadge(8);
  assert.strictEqual(badges.email, 8);
}

// Outlook count overrides Graph, including zero, and survives later Graph polls.
{
  const { ctx, badges } = load();
  ctx.publishEmailBadge(8);
  ctx.updateNativeBadge('email', 5);
  assert.strictEqual(badges.email, 5);
  ctx.publishEmailBadge(8);
  assert.strictEqual(badges.email, 5);
  ctx.updateNativeBadge('email', 0);
  assert.strictEqual(badges.email, 0);
}

// Outlook closes: back to the latest Graph total, not a stale native number.
{
  const { ctx, badges } = load();
  ctx.publishEmailBadge(8);
  ctx.updateNativeBadge('email', 5);
  ctx.publishEmailBadge(7);
  ctx.updateNativeBadge('email', null);
  assert.strictEqual(badges.email, 7);
}

// Teams still behaves the same alongside Email.
{
  const { ctx, badges } = load();
  ctx.updateNativeBadge('email', 5);
  ctx.updateNativeBadge('teams', 4);
  assert.strictEqual(badges.teams, 4);
  assert.strictEqual(badges.email, 5);
}

console.log('rail badge email ok');
