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

module.exports = { originKey, findStarredApp, starState, defaultAppName };
