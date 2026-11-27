'use strict';

function originKey(url) {
  try {
    const u = new URL(url);
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return '';
    return u.origin.toLowerCase();
  } catch {
    return '';
  }
}

function findStarredApp(url, apps, hiddenIds) {
  const key = originKey(url);
  if (!key) return null;
  for (const app of apps) {
    if (hiddenIds && hiddenIds.has(app.id)) continue;
    if (originKey(app.url) === key) return app.id;
  }
  return null;
}

function starState(url, apps, hiddenIds) {
  const appId = findStarredApp(url, apps, hiddenIds);
  return appId ? { state: 'filled', appId } : { state: 'empty', appId: null };
}

function defaultAppName(title, url) {
  let name = String(title || '').trim();
  if (!name) {
    try {
      name = new URL(url).hostname.replace(/^www\./i, '');
    } catch {
      name = 'Web app';
    }
  }
  return name.slice(0, 40);
}

function removalNote(pinCount) {
  if (!Number.isInteger(pinCount) || pinCount < 0) {
    return 'Removing deletes any pins, settings and saved sign-in.';
  }
  if (pinCount === 0) return "Removing deletes this app's settings and saved sign-in.";
  return `Removing deletes its ${pinCount} ${pinCount === 1 ? 'pin' : 'pins'}, settings and saved sign-in.`;
}

module.exports = { originKey, findStarredApp, starState, defaultAppName, removalNote };
