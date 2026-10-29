const assert = require('assert');
const fs = require('fs');
const path = require('path');
const test = require('node:test');

const { resolveAtlassianUrls } = require('../shell/atlassian-urls');

test('returns empty URLs when config is missing or has no Atlassian entries', () => {
  assert.deepStrictEqual(resolveAtlassianUrls(null), { confluenceUrl: '', jiraUrl: '' });
  assert.deepStrictEqual(resolveAtlassianUrls({}), { confluenceUrl: '', jiraUrl: '' });
});

test('Jira URL gets a single /jira suffix and no trailing slash', () => {
  const jira = (url) => resolveAtlassianUrls({ jira_base_url: url }).jiraUrl;
  assert.strictEqual(jira('https://example.atlassian.net'), 'https://example.atlassian.net/jira');
  assert.strictEqual(jira('https://example.atlassian.net/'), 'https://example.atlassian.net/jira');
  assert.strictEqual(
    jira('https://example.atlassian.net/jira'),
    'https://example.atlassian.net/jira',
  );
});

test('Confluence URL is passed through unchanged', () => {
  assert.strictEqual(
    resolveAtlassianUrls({ confluence_base_url: 'https://example.atlassian.net/wiki' })
      .confluenceUrl,
    'https://example.atlassian.net/wiki',
  );
});

test('packaged app includes the atlassian-urls module', () => {
  const pkg = JSON.parse(
    fs.readFileSync(path.join(__dirname, '..', 'shell', 'package.json'), 'utf8'),
  );
  assert(pkg.build.files.includes('atlassian-urls.js'));
});
