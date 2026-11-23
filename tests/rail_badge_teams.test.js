// Teams rail badge: one counting rule for every writer, and the native Teams count wins when the
// shell reports one. The real functions are cut out of app.js and run against a stub badge.

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
  for (const fn of ['teamsBadgeCount', 'publishTeamsBadge', 'updateNativeBadge']) {
    vm.runInContext(functionSource(fn), ctx);
  }
  return { ctx, badges };
}

const chat = (over) => ({ badge_unread: 1, unread_count: 1, ...over });

// Fallback rule: only chats the server marked badge_unread count; a chat read locally drops out.
{
  const { ctx } = load();
  const chats = [
    chat({ id: 'a' }),
    chat({ id: 'b', badge_unread: 0 }), // channel, notes, or my own last message
    chat({ id: 'c', _unread: false }), // marked read in Gator, server not refreshed yet
    chat({ id: 'd' }),
  ];
  assert.strictEqual(ctx.teamsBadgeCount(chats), 2);
  assert.strictEqual(ctx.teamsBadgeCount(undefined), 0);
}

// With no native count, publishing shows the fallback.
{
  const { ctx, badges } = load();
  ctx.publishTeamsBadge([chat({ id: 'a' }), chat({ id: 'b' })]);
  assert.strictEqual(badges.teams, 2);
}

// A native count overrides the chat list, including a native zero.
{
  const { ctx, badges } = load();
  ctx.publishTeamsBadge([chat({ id: 'a' }), chat({ id: 'b' })]);
  ctx.updateNativeBadge('teams', 5);
  assert.strictEqual(badges.teams, 5);
  ctx.publishTeamsBadge([chat({ id: 'a' })]); // a poll arrives; native still wins
  assert.strictEqual(badges.teams, 5);
  ctx.updateNativeBadge('teams', 0);
  assert.strictEqual(badges.teams, 0);
}

// Native goes away (signed out): fall back to the latest chat list.
{
  const { ctx, badges } = load();
  ctx.publishTeamsBadge([chat({ id: 'a' }), chat({ id: 'b' }), chat({ id: 'c' })]);
  ctx.updateNativeBadge('teams', 5);
  ctx.updateNativeBadge('teams', null);
  assert.strictEqual(badges.teams, 3);
}

console.log('rail badge teams ok');
