// Regression: the mention-autocomplete dropdown ("@name" in the composer)
// kept visibly flickering back to "Searching people…" while Slack's directory
// was still warming. openMentionDropdown() schedules its own retry
// (`setTimeout(() => openMentionDropdown(query, {isRetry:true}), 750)`) for as
// long as the backend reports `warming: true`; on a large/enterprise Slack
// workspace that warm-up can take many seconds, so every retry tick used to
// synchronously wipe `_mentionDropdown.innerHTML` back to the bare loading
// placeholder — discarding already-rendered Teams/Slack results — before its
// own 250ms debounce even started re-fetching them. That synchronous wipe is
// what this test guards against: a retry for the SAME still-open query must
// resume from the persisted `_mentionResultState` instead of clearing the
// dropdown, while a genuinely new query must still reset normally.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

const letsMatch = source.match(
  /let _mentionDebounceTimer = null;[\s\S]*?let _mentionResultState = null;/,
);
assert(letsMatch, 'mention dropdown module-level state not found in app.js');

const openMatch = source.match(/function openMentionDropdown\([^)]*\)\s*\{[\s\S]*?\n\}/);
assert(openMatch, 'openMentionDropdown not found in app.js');

// A fake dropdown element that tracks its own "children" so we can inspect
// what's actually shown after innerHTML is reset, without a real DOM.
function makeDropdown() {
  const dd = {
    _children: [],
    get innerHTML() {
      return '';
    },
    set innerHTML(_v) {
      dd._children = [];
    },
    appendChild(node) {
      dd._children.push(node);
    },
    insertAdjacentHTML(_pos, html) {
      dd._children.push({ html });
    },
    querySelector() {
      return null;
    },
    remove() {},
  };
  return dd;
}

function hasPerson(dd, id) {
  return dd._children.some((c) => c && c.__person === id);
}
function hasLoadingPlaceholder(dd) {
  return dd._children.some((c) => c && c.__loading);
}

function buildSandbox() {
  const sandbox = {
    console,
    setTimeout,
    clearTimeout,
    AbortController,
    fetch: () => new Promise(() => {}), // never resolves within this synchronous test
    document: {
      createElement: (_tag) => ({
        className: '',
        textContent: '',
        __loading: true,
      }),
    },
    window: { GATOR_SLACK_WORKSPACE: null },
    SKILL_MAP: { slack: { connected: false } },
    // Referenced only inside branches this test never takes (new-dropdown /
    // resume-mismatched-provider); presence as no-ops is enough.
    closeChannelDropdown: () => {},
    _buildDropdown: () => makeDropdown(),
    _effectiveLookupProvider: () => 'all',
    _renderLookupProviderToggle: () => {},
    _addProviderSection: () => {},
    _addPersonItem: (dd, p) => dd.appendChild({ __person: p.id }),
    _fetchSlackPeople: () => new Promise(() => {}),
    _activeChannels: new Set(),
  };
  sandbox.global = sandbox;
  return sandbox;
}

const harness = `
  let _mentionSearchController = null;
  let _mentionFocusIdx = -1;
  ${letsMatch[0]}
  ${openMatch[0]}
  function __test_seed(dd, query, resultState) {
    _mentionDropdown = dd;
    _mentionLastQuery = query;
    _mentionResultState = resultState;
  }
`;

// --- Case 1: retry for the SAME active query must resume, not wipe --------
{
  const sandbox = buildSandbox();
  vm.createContext(sandbox);
  vm.runInContext(harness, sandbox);

  const dd = makeDropdown();
  dd.appendChild({ __person: 'alice' }); // simulate an already-rendered Teams result
  sandbox.__test_seed(dd, 'may', {
    provider: 'all',
    slackStatus: { configured: false, team: 'Slack' },
    teamsPeople: [{ id: 'alice' }],
    slackPeople: [],
    teamsPending: false,
    slackPending: true,
  });

  sandbox.openMentionDropdown('may', { isRetry: true });

  // Assert synchronously, before the 250ms debounce inside openMentionDropdown
  // has any chance to fire — this is exactly the window where the bug lived.
  assert(
    hasPerson(dd, 'alice'),
    'a warming retry for the same query must not synchronously wipe already-rendered results',
  );
  assert(
    !hasLoadingPlaceholder(dd),
    'a warming retry for the same query must not reset to the bare loading placeholder',
  );
  clearTimeout(sandbox._mentionDebounceTimer);
}

// --- Case 2: a genuinely new query must still fully reset ------------------
{
  const sandbox = buildSandbox();
  vm.createContext(sandbox);
  vm.runInContext(harness, sandbox);

  const dd = makeDropdown();
  dd.appendChild({ __person: 'alice' });
  sandbox.__test_seed(dd, 'may', {
    provider: 'all',
    slackStatus: { configured: false, team: 'Slack' },
    teamsPeople: [{ id: 'alice' }],
    slackPeople: [],
    teamsPending: false,
    slackPending: true,
  });

  // A brand-new query ('mar' != 'may'), not flagged as a retry.
  sandbox.openMentionDropdown('mar');

  assert(
    !hasPerson(dd, 'alice'),
    'a genuinely new query must reset the dropdown instead of reusing stale results',
  );
  assert(
    hasLoadingPlaceholder(dd),
    'a genuinely new query must show the loading placeholder again',
  );
  clearTimeout(sandbox._mentionDebounceTimer);
}

// --- Case 3: isRetry:true with no prior state (e.g. first open) still resets
{
  const sandbox = buildSandbox();
  vm.createContext(sandbox);
  vm.runInContext(harness, sandbox);

  const dd = makeDropdown();
  sandbox.__test_seed(dd, null, null);

  sandbox.openMentionDropdown('may', { isRetry: true });

  assert(
    hasLoadingPlaceholder(dd),
    'isRetry with no existing _mentionResultState must fall back to a normal reset',
  );
  clearTimeout(sandbox._mentionDebounceTimer);
}

console.log('mention_dropdown_warming_retry: all assertions passed');
