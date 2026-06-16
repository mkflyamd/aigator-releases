---
name: jira
description: "Atlassian Jira — search issues, create tickets, manage remote links."
metadata:
  author: Mayuresh Kulkarni
  version: "1.0"
  format: agentskills-1.0
---

# Jira Workflow

- "Attach a PR / doc / link to a Jira ticket" → call jira_add_remote_link with the ticket key, URL, and title.
- "Show links on a ticket" → call jira_get_issue_links.
- NEVER call jira_create_issue directly. ALWAYS use jira_open_create_form so the user can review before submitting.
- When pinning a Jira issue via `/api/context/pin`, always include the issue URL in `meta` as `{ "url": "<browse url>/browse/<KEY>" }` — the UI uses this to let users open the ticket directly from the pins panel.
