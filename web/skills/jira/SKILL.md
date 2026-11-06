---
name: jira
description: 'Atlassian Jira — search issues, create tickets, manage remote links.'
metadata:
  author: Mayuresh Kulkarni
  version: '1.0'
  format: agentskills-1.0
---

# Jira Workflow

## Instance routing — read this first

Multiple Jira instances may be connected. Each tool's description says which site it covers.

**For any READ (full URL or bare key):**

1. Call `jira_get_issue` — it handles all connected sites automatically including Rovo.
2. Call Rovo MCP Jira tools ONLY if `jira_get_issue` reports the issue was not found or the site is not connected. Do not call them in parallel when the URL matches a native site.
3. Only tell the user the issue was not found after ALL tools have returned 404/error.

**For any WRITE (full URL or bare key):**

1. Call the native `jira_*` tool directly (e.g. `jira_add_comment`, `jira_update_issue`). Pass the full URL or bare key — target resolution is automatic.
2. Use the native `jira_*` tools for writes. Only if none covers the change, call the raw MCP write tool; it appears as an approval card and nothing is applied until the user approves. If Jira rejects a field change made with direct credentials (labels, components, custom fields), Gator retries the same approved change through Rovo on the same site automatically; there is no second approval. If a write tool returns "multiple sites", ask the user for the full URL.

## Write operations — non-negotiable rules (read before any write)

1. **ALWAYS use native `jira_*` tools** for ANY write (comment, update, create, transition, watcher, link, attachment). Use a raw Rovo MCP write tool only when no native tool covers the change; it is held as an approval card and nothing is applied until the user approves. Gator reaches Rovo itself when a native write needs it.
2. **Creating a ticket**: call `jira_get_project_meta` first to find required fields, ask the user for missing values, then call `jira_open_create_form`. Never call `jira_create_issue` directly — it is disabled.
3. **If a write tool returns a "multiple sites" error**: ask the user to provide the full issue URL so the correct site can be identified unambiguously.

## Other rules

- "Attach a PR / doc / link to a Jira ticket" → call jira_add_remote_link with the ticket key, URL, and title.
- "Show links on a ticket" → call jira_get_issue_links.
- To create a ticket: call jira_get_project_meta → ask for missing required fields → call jira_open_create_form. Do NOT use run_python to parse metadata.
- When pinning a Jira issue via `/api/context/pin`, always include the issue URL in `meta` as `{ "url": "<browse url>/browse/<KEY>" }` — the UI uses this to let users open the ticket directly from the pins panel.
