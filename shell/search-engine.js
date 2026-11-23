'use strict';

// The search engine used by every address bar and as the Browser pane's start page.
const fs = require('fs');

const ENGINES = {
  bing: {
    name: 'Bing',
    home: 'https://www.bing.com/',
    search: 'https://www.bing.com/search?q=',
  },
  google: {
    name: 'Google',
    home: 'https://www.google.com/',
    search: 'https://www.google.com/search?q=',
  },
  duckduckgo: {
    name: 'DuckDuckGo',
    home: 'https://duckduckgo.com/',
    search: 'https://duckduckgo.com/?q=',
  },
};
const DEFAULT_ENGINE = 'bing';

const isEngineId = (id) => typeof id === 'string' && Object.hasOwn(ENGINES, id);

// Remembers the chosen engine in a small JSON file. A missing or unreadable file means the default.
function createStore(file) {
  let current = DEFAULT_ENGINE;
  try {
    const saved = JSON.parse(fs.readFileSync(file, 'utf8')).engine;
    if (isEngineId(saved)) current = saved;
  } catch {}

  return {
    get: () => current,
    set(id) {
      if (!isEngineId(id)) return false;
      current = id;
      try {
        fs.writeFileSync(file, JSON.stringify({ engine: id }));
      } catch {}
      return true;
    },
    searchUrl: () => ENGINES[current].search,
    homeUrl: () => ENGINES[current].home,
  };
}

const listEngines = () => Object.entries(ENGINES).map(([id, e]) => ({ id, name: e.name }));

module.exports = { ENGINES, DEFAULT_ENGINE, isEngineId, createStore, listEngines };
