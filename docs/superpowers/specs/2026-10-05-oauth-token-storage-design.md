# OAuth Token Storage Design

> **Update:** the Windows-only scope below is superseded for macOS and Linux by [2026-10-05-secure-store-macos-linux-design.md](2026-10-05-secure-store-macos-linux-design.md).

**Finding:** `H_Local_OAuth_token_theft_from_filesystem_01` (High)
**Tracker:** [threatmodel-remediation.md](../../security/threatmodel-remediation.md)
**Status:** Design approved in conversation; pending written-spec sign-off before implementation plan.

## Problem

AI Gator stores OAuth and personal-access tokens as plaintext JSON under the user profile. Any
process running as the same user can read them. Inventory of what exists today:

| Store | Contents | Writer | Direct readers |
|---|---|---|---|
| `~/.config/microsoft-graph/token.json` | Graph refresh/access token | `web/skills/m365-email/graph_client.py` (`_save_token`) | `graph_client.py`, `web/routes/auth.py`, `web/routes/teams.py`, `m365-teams/scripts/read_chats.py`, `web/skills/_m365/helpers.py` |
| `~/.config/microsoft-graph/teams_token.json` | Browser-captured Teams token | `web/routes/auth.py` (3 sites) | `_m365/helpers.py`, `routes/auth.py`, `routes/teams.py` |
| `~/.config/microsoft-graph/skype_token.json`, `skypetoken.json` | Skype swap cache | `read_chats.py` | `read_chats.py` |
| `~/.config/slack-mcp/token.json`, `.pkce_pending.json` | Slack token, PKCE verifier | `web/skills/slack/mcp_client.py` | `mcp_client.py`, `routes/auth.py` |
| `~/.gator/oauth/<provider>.json` | MCP provider config plus `token` block | `web/oauth/storage.py` | `web/oauth/flow.py`, `web/routes/mcp_routes.py` |
| `~/.gator/config.json` | `jira_api_token`, `jira_pat`, `confluence_pat`, `github_token` | `web/routes/config_routes.py` via `web/config.py` | `web/app.py` (copies into env), `web/mcp/url_fetcher.py` |

`config.py` also copies `config.json` to `config.json.bak` on every save, so the PATs persist in
backup copies too. There is no encryption, no DPAPI, and no Graph/Slack/Teams clear route. All
token handling is hand-rolled JSON (no MSAL). The seven non-canonical `graph_client.py` files are
15-line wrappers around `m365-email/graph_client.py`, so a fix there propagates.

**Report requirement:** migrate all OAuth and PAT tokens to OS-native secure storage and remove
JSON token files. **Acceptance:** tokens stored only in secure storage; no JSON token files in
runtime directories; encrypted at rest if no vault; short-lived access tokens with refresh
rotation; working revoke/clear controls.

## Design

### 1. `web/secure_store.py` (new, stdlib only)

API: `get(name) -> str | None`, `set(name, value)`, `delete(name)`, `list_names(prefix="")`.
Windows backend uses DPAPI (`CryptProtectData` / `CryptUnprotectData` through `ctypes`, current-user
scope, UI forbidden, fixed application entropy). Each secret is one binary blob under
`~/.gator/secrets/<safe-name>.bin`, written atomically (temp file then `os.replace`). Names such as
`graph/token`, `graph/teams_token`, `slack/token`, `oauth/<provider_id>`, `config/jira_pat`.

DPAPI blobs rather than Credential Manager: Credential Manager caps a credential blob at about
2.5 KB, which is smaller than many Graph access tokens, and remediation step 2 allows per-user
encryption at rest. The module has no third-party dependency so the skill scripts, which run as
separate Python processes, can load it by file path the way the graph wrappers already do.

Only the Windows backend is implemented (AI Gator ships only on Windows). The interface is
backend-neutral so Keychain / Secret Service can be added later. On an unsupported OS the module
raises an explicit error and never falls back to plaintext.

### 2. Route every reader and writer through it

- `web/oauth/storage.py`: keep its `load/save/delete/update_token` signatures; swap the file I/O
  for `secure_store` (`oauth/<provider_id>`). All generic-MCP OAuth callers are unchanged.
- Graph: `graph_client.py` `_save_token` / token load use `secure_store`; replace the direct
  `token.json` / `teams_token.json` reads in `routes/auth.py`, `routes/teams.py`, `read_chats.py`,
  `_m365/helpers.py` with calls to the same accessor. Keep `TOKEN_FILE` only if a caller still
  needs the symbol.
- Slack: `mcp_client.py` token and PKCE state go through `secure_store`.
- `config.json` PATs: `load_config()` overlays the four PAT keys from `secure_store`;
  `save_config()` / `update_config()` move those keys into `secure_store` and drop them from the
  JSON. All other code that reads `cfg["jira_pat"]` etc. is unchanged, and `app.py`'s copy into
  environment variables is unchanged.

### 3. One-time migration (read-through)

When an accessor finds no secret in `secure_store` but a legacy plaintext file or config key
exists, it imports it: encrypt, decrypt to verify, then delete the plaintext. If verification fails
the plaintext is left in place and an error is logged. Idempotent and safe to interrupt. A startup
sweep in `app.py` finishes anything not yet touched and scrubs the PAT keys out of
`config.json.bak*` and `*.damaged` copies (unparseable copies are deleted). Plaintext deletion
overwrites the file first; on SSDs this is best effort.

### 4. Lifetime and rotation

Graph, Slack and the generic OAuth flow already refresh and adopt a rotated refresh token, and
access tokens are about an hour. No behavior change; add tests that lock in adoption of a rotated
refresh token for each flow.

### 5. User controls

`POST /api/auth/clear` (state-changing, so it follows the existing CSRF pattern in
`routes/auth.py`) deletes all `secure_store` entries or one provider's. Where the provider
supports revocation (Slack, generic OAuth with an RFC 7009 endpoint) it also revokes server-side,
best effort. Microsoft tokens are cleared locally only. `/api/config/mcp/oauth/forget` is pointed
at `secure_store`. One "Clear stored credentials" button in Settings.

## Testing

Characterization tests first, since almost nothing covers these paths today: Graph token
round-trip and refresh, `oauth/storage` load/save/update, config PAT round-trip. Then
`secure_store` unit tests (round-trip, corrupted blob returns an error not plaintext), migration
tests (plaintext gone, idempotent, failed verification keeps plaintext), a test that no code path
writes token JSON, and clear-route tests.

## Acceptance mapping

| Criterion | Met by |
|---|---|
| Stored only in OS-native secure storage | Sections 1-2 |
| No JSON token files in runtime dirs | Sections 2-3 (migration and sweep) |
| Encrypted at rest | DPAPI |
| Short-lived access tokens, refresh rotation | Section 4 (existing, now tested) |
| Revoke/clear controls work | Section 5 |

## Known limitation

DPAPI protects against other users and offline theft. It does not stop malware running as the same
user, which can call `CryptUnprotectData` too. This meets the report's acceptance criteria and is
stated plainly in the writeup.

## Out of scope (second pass)

LLM API keys, `google_oauth_client_secret`, MCP `auth_value` and `mcp_spawn_specs` env values in
`config.json`; the in-memory environment-variable copy of PATs that child processes inherit (the
Code-runner finding); macOS and Linux backends; server-side revocation for Microsoft tokens.

## Risk to verify in the implementation plan

Skill scripts load shared code by path; confirm `secure_store` resolves the same way in the frozen
build.
