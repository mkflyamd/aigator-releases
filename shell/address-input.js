'use strict';

// Turns what a user typed in the address bar into something to load, the way a browser omnibox
// does: real addresses navigate, everything else becomes a web search.
const SEARCH_URL = 'https://www.bing.com/search?q=';

const SCHEME = /^[a-z][a-z0-9+.-]*:/i;
const HOST_PORT = /^(\[[0-9a-f:.]+\]|[^\s:/?#@\[\]]+)(?::(\d{1,5}))?$/i;
const IPV4 = /^\d{1,3}(?:\.\d{1,3}){3}$/;
const DOMAIN =
  /^(?:[\p{L}\p{N}](?:[\p{L}\p{N}-]*[\p{L}\p{N}])?\.)+(?:[\p{L}]{2,}|xn--[a-z0-9-]+)$/iu;

function search(text) {
  return { kind: 'search', url: SEARCH_URL + encodeURIComponent(text), explicit: false };
}

function toUrl(text, scheme, explicit) {
  try {
    const parsed = new URL(`${scheme}://${text}`);
    return { kind: 'url', url: parsed.href, explicit };
  } catch {
    return search(text);
  }
}

function resolveAddressInput(raw) {
  const text = String(raw == null ? '' : raw).trim();
  if (!text) return null;

  if (/^https?:\/\//i.test(text)) {
    try {
      return { kind: 'url', url: new URL(text).href, explicit: true };
    } catch {
      return null;
    }
  }
  if (/\s/.test(text)) return search(text);

  const authority = text.split(/[/?#]/, 1)[0];
  const hostPort = authority.match(HOST_PORT);
  // "localhost:3000" looks like a scheme to SCHEME, so only treat it as one when it is not host:port.
  if (SCHEME.test(text) && !hostPort) return null;
  if (!hostPort) return search(text);

  const host = hostPort[1].toLowerCase();
  const hasPort = !!hostPort[2];
  const isIp = IPV4.test(host) || host.startsWith('[');
  const isLocal = host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local');
  if (isIp || isLocal) return toUrl(text, 'http', false);
  if (DOMAIN.test(host)) return toUrl(text, 'https', false);
  // A bare intranet name only counts as an address when a port makes the intent clear.
  if (hasPort && !host.includes('.')) return toUrl(text, 'http', false);
  return search(text);
}

const NAME_NOT_RESOLVED = (err) =>
  !!err && (err.code === 'ERR_NAME_NOT_RESOLVED' || err.errno === -105);
// Only a bare hostname is safe to hand to a search engine; a path or query may carry tokens
// or internal identifiers that must not leave the machine after a typo.
const isBareHost = (typed) => /^[^\s/?#@:]+$/.test(String(typed).trim());
const ABORTED = (err) => !!err && (err.code === 'ERR_ABORTED' || err.errno === -3);

// Loads what the user typed into `wc`. A guessed address that does not resolve (for example
// "foo.bar") falls back to a search, like a browser. `onError` gets real failures only;
// ERR_ABORTED is what loadURL rejects with when a redirect or unload prompt replaces the load.
function loadAddressInput(wc, typed, onError) {
  const target = resolveAddressInput(typed);
  if (!target) {
    if (onError) onError(new Error('That address cannot be opened here.'), String(typed || ''));
    return;
  }
  wc.loadURL(target.url).catch((error) => {
    if (ABORTED(error)) return;
    if (
      target.kind === 'url' &&
      !target.explicit &&
      isBareHost(typed) &&
      NAME_NOT_RESOLVED(error)
    ) {
      const fallback = search(String(typed).trim());
      wc.loadURL(fallback.url).catch((err) => {
        if (!ABORTED(err) && onError) onError(err, fallback.url);
      });
      return;
    }
    if (onError) onError(error, target.url);
  });
  try {
    wc.focus();
  } catch {}
}

module.exports = { SEARCH_URL, resolveAddressInput, loadAddressInput };
