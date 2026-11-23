# Google Workspace Integration — Architecture

## Overview

AI Gator integrates Google Workspace (Gmail, Google Calendar, and more) via the
open-source [workspace-mcp](https://github.com/taylorwilsdon/google_workspace_mcp)
server, published on [PyPI](https://pypi.org/project/workspace-mcp/) as
`workspace-mcp`. The server wraps Google's GA REST APIs (not the Preview-gated
MCP APIs) and exposes them as MCP tools over streamable-http transport.

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
  └─ HTTP MCP client ── http://127.0.0.1:8080/mcp
       └─ detached process: uvx workspace-mcp --transport streamable-http --tool-tier complete
            ├─ Reads GOOGLE_OAUTH_CLIENT_ID / SECRET and USER_GOOGLE_EMAIL from env vars
            ├─ Calls the Google REST APIs (Gmail, Calendar, Drive, ...) — GA
            └─ OAuth callback server on port 8080 (WORKSPACE_MCP_PORT)
```

The server runs as a **separate process** on the user's machine, started by
`POST /api/config/mcp/presets/spawn` (`web/routes/mcp_routes.py`). AI Gator
talks to it over streamable HTTP. No data passes through any third party — the
server calls Google's APIs directly.

## Google accounts

Settings → Apps → Google Workspace has a **Google accounts** list, shaped like
the Jira site rows:

- The user types one email per row. The first row is the default account and is
  stored in `google_accounts` in `config.json`. `google_user_email` mirrors the
  default so older configs keep working.
- **Save** validates the Client ID suffix, the secret, and every email, then
  sends a dummy authorization code to `https://oauth2.googleapis.com/token`. An
  `invalid_client` answer means Google rejects the Client ID / secret pair, and
  the save is refused. Network failures do not block the save.
- **Save always reconnects.** The running server reads the client secret and the
  default account only at launch, so every save respawns it.
- `GET /api/config/google/status` returns each account with `default` and
  `signed_in` (a credentials file exists under `~/.google_workspace_mcp/credentials/`).

### Login hint

The preset endpoint (`GET /api/config/mcp/presets/google`) sets
`USER_GOOGLE_EMAIL` in the server's env from the default account. workspace-mcp
adds `login_hint=<email>` to the Google sign-in link when it has an email, so
Google opens the right account chooser entry.

### Account resolver

`web/google_accounts.py` resolves `user_google_email` in code, before the
approval gate, for every workspace-mcp tool that takes the argument
(`web/mcp/manager.py`):

- a missing or unknown value becomes the default account;
- a value that matches a configured account is kept (case-insensitive);
- with no configured account the call returns an error naming Settings instead
  of reaching Google.

Approval cards therefore store the resolved email. The system prompt lists all
configured accounts and the default (`_append_google_account_context` in
`web/routes/chat.py`).

## Tool budget

workspace-mcp at `--tool-tier complete` exposes about 138 tools, which is more
than a model's tool limit (128 for Claude models). AI Gator never loads that
connection whole. `expand_google_umbrella` (`web/tool_pipeline.py`) replaces the
`mcp-google-workspace` connection with the `g-*` service groups the message
asks for (Gmail, Calendar, Drive, Docs, Sheets, Slides, Forms, Tasks, Contacts,
Chat, Search, Apps Script), defaulting to Gmail, Calendar and Drive. It runs for
explicit selection, the active skill, mid-turn skill activation and scheduled
runs, and the raw connection is hidden from the skill catalog. When a request
still needs more required tools than the model allows, the chat reports the
counts and asks the user to disable optional skills.

## OAuth flow

1. AI Gator injects `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`
   as env vars when it spawns the server (from shared config)
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

| File                          | Role                                                                           |
| ----------------------------- | ------------------------------------------------------------------------------ |
| `web/routes/mcp_routes.py`    | Preset definition, resolve and spawn endpoints, MCP connection CRUD            |
| `web/google_accounts.py`      | Account list, account resolver, client-secret probe                            |
| `web/routes/config_routes.py` | `POST /api/config/google` (validate and save), `GET /api/config/google/status` |
| `web/tool_pipeline.py`        | Google service groups, `expand_google_umbrella`                                |
| `web/mcp/manager.py`          | HITL gate (`_is_gated_tool`, `_summarize_gated_call`), account resolver, tool dispatch |
| `web/skills/_drafts.py`       | Draft store for HITL approval flow                                             |
| `web/routes/email.py`         | Draft approval endpoint (`/api/drafts/{id}/approve`) — replays gated MCP calls |
| `web/static/mcp_add_modal.js` | Connect wizard — preset flow, GitHub URL fetcher                               |
| `web/static/app.js`           | Draft approval card UI, chat rendering                                         |
| `web/oauth/flow.py`           | OAuth flow for remote MCP servers (not used for workspace-mcp)                 |
| `web/oauth/dcr.py`            | BYOC provider registration — Google-specific params (no `resource` param)      |

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
