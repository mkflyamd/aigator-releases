const assert = require('assert');
const fs = require('fs');
const path = require('path');
const test = require('node:test');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'third-pane.js'),
  'utf8',
);

function extract(re, label) {
  const m = source.match(re);
  assert(m, `${label} not found in third-pane.js`);
  return m[0];
}

const code = [
  extract(/\nconst _SETUP_REDIRECTS = \{[\s\S]*?\n\};/, '_SETUP_REDIRECTS'),
  extract(/\nfunction _redirectToSetup\([^)]*\)\s*\{[\s\S]*?\n\}/, '_redirectToSetup'),
  extract(/\nfunction _redirectIfNotShown\([^)]*\)\s*\{[\s\S]*?\n\}/, '_redirectIfNotShown'),
].join('\n');

function harness(activeType) {
  const calls = { closed: 0, panels: [], scrolled: [], toasts: [] };
  const sandbox = {
    tpState: { type: activeType },
    closeThirdPane: () => {
      calls.closed++;
      sandbox.tpState.type = null;
    },
    document: {
      getElementById: (id) => ({
        closest: () => ({ scrollIntoView: () => calls.scrolled.push(id) }),
      }),
    },
    window: {
      openSettingsPanel: (tab) => calls.panels.push(tab),
      _showConnectivityToast: (msg, type) => calls.toasts.push({ msg, type }),
    },
    Promise,
  };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  return { sandbox, calls };
}

const settle = () => new Promise((resolve) => setImmediate(resolve));

for (const [type, label, section] of [
  ['jira', 'Jira', 'atlassian-detail'],
  ['confluence', 'Confluence', 'atlassian-detail'],
  ['github', 'GitHub', 'github-detail'],
]) {
  test(`${type}: a pane that could not be shown sends the user to its Settings section`, async () => {
    const { sandbox, calls } = harness(type);
    vm.runInContext(`_redirectIfNotShown('${type}', Promise.resolve(false))`, sandbox);
    await settle();
    assert.strictEqual(calls.closed, 1);
    assert.deepStrictEqual(calls.panels, ['integrations']);
    assert.deepStrictEqual(calls.scrolled, [section]);
    assert.strictEqual(calls.toasts.length, 1);
    assert(calls.toasts[0].msg.includes(label));
  });

  test(`${type}: a pane that was shown is left alone`, async () => {
    const { sandbox, calls } = harness(type);
    vm.runInContext(`_redirectIfNotShown('${type}', Promise.resolve(true))`, sandbox);
    await settle();
    assert.strictEqual(calls.closed, 0);
    assert.deepStrictEqual(calls.panels, []);
    assert.deepStrictEqual(calls.toasts, []);
  });
}

test('no redirect when the user already switched to another app', async () => {
  const { sandbox, calls } = harness('teams');
  vm.runInContext(`_redirectIfNotShown('jira', Promise.resolve(false))`, sandbox);
  await settle();
  assert.strictEqual(calls.closed, 0);
  assert.deepStrictEqual(calls.panels, []);
});

test('a non-boolean or rejected result does not redirect', async () => {
  const { sandbox, calls } = harness('jira');
  vm.runInContext(`_redirectIfNotShown('jira', undefined)`, sandbox);
  vm.runInContext(`_redirectIfNotShown('jira', Promise.reject(new Error('ipc')))`, sandbox);
  await settle();
  assert.strictEqual(calls.closed, 0);
  assert.deepStrictEqual(calls.panels, []);
});

test('third pane uses the redirect for Jira, Confluence and GitHub native branches', () => {
  assert(source.includes("_redirectIfNotShown('jira', window.gatorShell.showJira())"));
  assert(source.includes("_redirectIfNotShown('confluence', window.gatorShell.showConfluence())"));
  assert(/if \(!shown\) \{\s*_redirectToSetup\('github'\);/.test(source));
});

test('GitHub config fetch in the shell tolerates a failed request', () => {
  const main = fs.readFileSync(path.join(__dirname, '..', 'shell', 'main.js'), 'utf8');
  const fn = main.match(/async function createGitHubView\(\) \{[\s\S]*?\r?\n  GITHUB_URL =/);
  assert(fn, 'createGitHubView not found');
  assert(fn[0].includes('(await _fetchConfigJson()) || {}'));
});

function githubEnabledAfterConfig(fetchImpl) {
  const helper = extract(/\nfunction _nativeUnlessClassic\([^)]*\)\s*\{[\s\S]*?\n\}/, 'helper');
  const init = extract(
    /\nlet _githubMode = null;[\s\S]*?\n\(function _initGithubMode\(\) \{[\s\S]*?\n\}\)\(\);/,
    '_initGithubMode',
  );
  const sandbox = {
    window: { gatorShell: { isShell: true }, addEventListener: () => {} },
    fetch: fetchImpl,
    Promise,
  };
  vm.createContext(sandbox);
  vm.runInContext(`${helper}\n${init}\nthis.enabled = () => _githubNativeEnabled();`, sandbox);
  return settle().then(() => sandbox.enabled());
}

test('a failed startup config fetch does not lock GitHub into classic', async () => {
  assert.strictEqual(await githubEnabledAfterConfig(() => Promise.reject(new Error('down'))), true);
});

test('explicit classic GitHub mode is still honoured', async () => {
  const classic = () =>
    Promise.resolve({ json: () => Promise.resolve({ github_pane_mode: 'classic' }) });
  assert.strictEqual(await githubEnabledAfterConfig(classic), false);
});

test('a rejected showGitHub call redirects instead of falling back to classic', () => {
  assert(!/_githubMode = 'classic';\s*_openThirdPaneImpl\('github'\)/.test(source));
  assert(/\}, \(\) => \{\s*_redirectToSetup\('github'\);\s*\}\);/.test(source));
});
