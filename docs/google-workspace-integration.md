# Google Workspace Integration — Architecture

## Overview

AI Gator integrates Google Workspace (Gmail, Google Calendar, and more) via the
open-source [workspace-mcp](https://github.com/taylorwilsdon/google_workspace_mcp)
server, published on [PyPI](https://pypi.org/project/workspace-mcp/) as
`workspace-mcp`. The server wraps Google's GA REST APIs (not the Preview-gated
MCP APIs) and exposes them as MCP tools over stdio transport.

## Why workspace-mcp

Google publishes official remote MCP servers for Gmail and Calendar
(`gmailmcp.googleapis.com`, `calendarmcp.googleapis.com`), but they are gated
behind the [Google Workspace Developer Preview Program](https://developers.google.com/workspace/preview)
and cannot be enabled without program enrollment (approval takes days and is
selective).

The `workspace-mcp` server (3k+ stars, MIT licensed, actively maintained)
provides the same functionality using the GA Google REST APIs that have been
available since 2014 — no Preview enrollment needed. It covers 12 Google
Workspace services with 120+ tools:

- **Gmail**: search, read, draft, send, labels, filters, attachments
- **Google Calendar**: events, free/busy, Out of Office, Focus Time
- **Google Drive, Docs, Sheets, Slides, Forms, Tasks, Contacts, Chat, Custom Search, Apps Script**

## How it runs

```
AI Gator (port 8000)
  └─ stdio MCP client (web/mcp/stdio_client.py)
       └─ subprocess: uvx workspace-mcp --tools gmail calendar
            ├─ Reads GOOGLE_OAUTH_CLIENT_ID / SECRET from env vars
            ├─ Calls Gmail REST API (gmail.googleapis.com) — GA
            ├─ Calls Calendar REST API (calendar-json.googleapis.com) — GA
            └─ OAuth callback server on port 8080 (WORKSPACE_MCP_PORT)
```

The server runs as a **separate process** on the user's machine. AI Gator
communicates with it over stdin/stdout (JSON-RPC per the MCP spec). No data
passes through any third party — the server calls Google's APIs directly.

## OAuth flow

1. AI Gator injects `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`
   as env vars on the stdio connection (from shared config)
2. On first tool call (e.g. "check my Gmail"), the server has no stored
   credentials and returns an auth URL
3. The user clicks the URL, signs in to Google, authorizes the app
4. Google redirects to `http://localhost:8080/oauth2callback` (the server's
   own callback endpoint — separate from AI Gator's `/oauth/callback`)
5. The server exchanges the auth code for tokens, stores them in
   `~/.google_workspace_mcp/credentials/`, and returns the tool result
6. Subsequent calls use the stored tokens (refreshed automatically)

**Required redirect URIs in Google Cloud Console:**
- `http://localhost:8080/oauth2callback` (workspace-mcp's callback)
- `http://127.0.0.1:8000/oauth/callback` (AI Gator's own OAuth, for other MCP servers)

## Shared credentials

One Google Cloud OAuth client (Web application type) is created once and shared
across all users via config:

```json
{
  "google_oauth_client_id": "....apps.googleusercontent.com",
  "google_oauth_client_secret": "GOCSPX-..."
}
```

The preset resolve endpoint (`POST /api/config/mcp/presets/resolve`) reads these
from config and injects them as env vars on the connection. Users never see or
touch the client_id/secret — they just click "Connect Google Workspace" and
sign in with Google.

## Generic preset system

The Google Workspace integration is one instance of a generic preset mechanism
designed for any service that needs credentials injected as env vars:

1. **Preset declaration** (`web/routes/mcp_routes.py`): defines the server
   config (command, args, env_mapping, env_defaults)
2. **Resolve endpoint** (`POST /api/config/mcp/presets/resolve`): reads shared
   config values and returns a complete `MCPConnectionRequest` payload with env
   vars filled in
3. **Wizard flow** (`_runPresetFlow` in `mcp_add_modal.js`): calls resolve,
   then `POST /api/config/mcp` to save as a normal MCP connection

Future presets (GitHub, Atlassian, Slack, etc.) can use the same mechanism by
declaring their own `env_mapping` entries.

## Human-in-the-loop gate

Destructive tools are gated with the same draft-approval HITL pattern used for
email/Teams/Slack sends. The gate (`web/mcp/manager.py`) intercepts:

- **Unconditionally gated**: `send_gmail_message`, `trash_thread`,
  `trash_message`, `mark_thread_spam`, `mark_message_spam`,
  `batch_delete_emails`, `manage_gmail_filter`
- **Conditionally gated** (only for destructive actions): `manage_event`
  (create/update/delete/rsvp), `manage_out_of_office`, `manage_focus_time`,
  `manage_gmail_label` (delete)

Gated calls are parked in the draft store (`web/skills/_drafts.py`) and surfaced
as an approval card in the chat. The actual MCP call only runs from the
CSRF-gated `/api/drafts/{id}/approve` endpoint, which the in-process agent loop
cannot reach.

## Key files

| File | Role |
|---|---|
| `web/routes/mcp_routes.py` | Preset definition, resolve endpoint, MCP connection CRUD |
| `web/mcp/manager.py` | HITL gate (`_is_gated_tool`, `_summarize_gated_call`), tool dispatch |
| `web/mcp/stdio_client.py` | Stdio transport — spawns and communicates with the server process |
| `web/skills/_drafts.py` | Draft store for HITL approval flow |
| `web/routes/email.py` | Draft approval endpoint (`/api/drafts/{id}/approve`) — replays gated MCP calls |
| `web/static/mcp_add_modal.js` | Connect wizard — preset flow, GitHub URL fetcher |
| `web/static/app.js` | Draft approval card UI, chat rendering |
| `web/oauth/flow.py` | OAuth flow for remote MCP servers (not used for workspace-mcp) |
| `web/oauth/dcr.py` | BYOC provider registration — Google-specific params (no `resource` param) |

## Corporate proxy support

- `UV_SYSTEM_CERTS=true` — set at app startup so `uvx` loads system CA store
  instead of bundled certs (Zscaler/MITM proxies)
- `_SYSTEM_SSL_CONTEXT` in `url_fetcher.py` — httpx uses system trust store for
  GitHub README fetching
- `_github_auth_headers()` — authenticated GitHub API calls (5000/hour vs
  60/hour unauthenticated)

## References

- **workspace-mcp GitHub**: https://github.com/taylorwilsdon/google_workspace_mcp
- **workspace-mcp PyPI**: https://pypi.org/project/workspace-mcp/
- **MCP Protocol**: https://modelcontextprotocol.io/
- **Google OAuth 2.0 for Desktop Apps**: https://developers.google.com/identity/protocols/oauth2/native-app
- **Google OAuth 2.0 Scopes**: https://developers.google.com/identity/protocols/oauth2/scopes
- **Google Workspace Developer Preview Program**: https://developers.google.com/workspace/preview
