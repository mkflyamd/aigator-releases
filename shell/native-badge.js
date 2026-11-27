// Native Slack and Teams put their own unread counts in the window title. null means the
// title gives no opinion. Slack's title only ends in "- Slack" once signed in, so no count
// there is a real zero. Teams shows the same title while loading or signed out, so only a
// positive Teams count is trusted.

function slackBadgeFromTitle(title) {
  if (typeof title !== 'string' || !/ - Slack$/.test(title)) return null;
  const m = title.match(/(\d+) new items?\b/);
  return m ? parseInt(m[1], 10) : 0;
}

function teamsBadgeFromTitle(title) {
  if (typeof title !== 'string' || !/\| Microsoft Teams$/.test(title)) return null;
  const m = title.match(/^\((\d+)\)/);
  return m ? parseInt(m[1], 10) : null;
}

module.exports = { slackBadgeFromTitle, teamsBadgeFromTitle };
