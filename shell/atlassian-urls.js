function resolveAtlassianUrls(config) {
  const data = config || {};
  let jiraUrl = '';
  if (data.jira_base_url) {
    jiraUrl = data.jira_base_url.replace(/\/$/, '');
    if (!jiraUrl.endsWith('/jira')) jiraUrl += '/jira';
  }
  return { confluenceUrl: data.confluence_base_url || '', jiraUrl };
}

module.exports = { resolveAtlassianUrls };
