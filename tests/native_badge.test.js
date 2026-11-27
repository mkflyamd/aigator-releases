// The native apps put their own unread counts in the window title; the rail badge reads those
// so it shows the same number the user sees in Slack and Teams.

const assert = require('assert');
const { slackBadgeFromTitle, teamsBadgeFromTitle } = require('../shell/native-badge.js');

// Slack: "N new item(s)" counts DMs and mentions. A bare "*" prefix means unread channels only.
assert.strictEqual(slackBadgeFromTitle('ext-amd-oracle (Channel) - AMD - 1 new item - Slack'), 1);
assert.strictEqual(slackBadgeFromTitle('Alice (DM) - AMD - 12 new items - Slack'), 12);
assert.strictEqual(slackBadgeFromTitle('* general (Channel) - AMD - Slack'), 0);
assert.strictEqual(slackBadgeFromTitle('general (Channel) - AMD - Slack'), 0);

// Slack not signed in / still loading: no opinion, so the rail keeps its last value.
assert.strictEqual(slackBadgeFromTitle(''), null);
assert.strictEqual(slackBadgeFromTitle('Slack | Sign in'), null);

// Teams: "(N) Chat | ..." is the count. A title with no count is also what a loading or
// signed-out Teams page shows, so it is no opinion (null) and the chat-list count is used.
assert.strictEqual(teamsBadgeFromTitle('(6) Chat | Kulkarni, Mayuresh (You) | Microsoft Teams'), 6);
assert.strictEqual(teamsBadgeFromTitle('(4) Chat | NaN Doctor Skill | Microsoft Teams'), 4);
assert.strictEqual(teamsBadgeFromTitle('Chat | NaN Doctor Skill | Microsoft Teams'), null);
assert.strictEqual(teamsBadgeFromTitle('Chat | Microsoft Teams'), null);

// Teams not loaded / signing in: null so the caller falls back to the chat-list count.
assert.strictEqual(teamsBadgeFromTitle(''), null);
assert.strictEqual(teamsBadgeFromTitle('Sign in to your account'), null);
assert.strictEqual(teamsBadgeFromTitle(undefined), null);
// The signed-out / loading page is titled just "Microsoft Teams": not a count of zero.
assert.strictEqual(teamsBadgeFromTitle('Microsoft Teams'), null);

console.log('native badge title parsing ok');
