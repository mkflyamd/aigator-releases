# User Identity — Design

## Goal

Tie AI Gator usage to an individual user. A person is identified by the account they connect (Microsoft 365, Slack, or Google). A user with no connected account is not an active user and has no identity. No groups, roles, or new sign-in screen.

The first consumer is the daily usage report (`web/usage_report.py`, separate spec), which sends the identity with each report.

## Identity record

Stored in `secure_store` under `identity/profile`:

```json
{
  "id": "jane.doe@amd.com",
  "name": "Jane Doe",
  "source": "microsoft",
  "emails": {
    "microsoft": "jane.doe@amd.com",
    "slack": "jane.doe@amd.com",
    "google": "jane.doe@gmail.com"
  }
}
```

- `id` is the lowercased email of the primary account.
- The primary account is the first available in this order: Microsoft, Slack, Google.
- `emails` holds the email from every connected account, so one person with several accounts is one identity.
- `source` names the primary account.

## Component: `web/identity.py`

| Function | Purpose |
|---|---|
| `get_identity() -> dict \| None` | Returns the stored record, or `None` if no account has ever been connected. |
| `refresh_identity() -> None` | Reads each connected account, updates `emails`, recomputes `id`, `name`, `source`, and saves. Never raises. |

The record is kept after a token expires or an account is disconnected, so the identity stays stable.

### Where each email comes from

- **Microsoft:** the `graph/token` access-token claims (`upn`, then `preferred_username`, then `email`; `name`). This is the logic `/api/auth/status` already uses; it moves into a shared helper in `identity.py` and `/api/auth/status` calls it.
- **Slack:** after the Slack connection is saved, call `auth.test` for the user ID, then `users.info` for that user's `profile.email`. The `users:read` and `users:read.email` scopes are already requested.
- **Google:** after a Google provider's OAuth callback succeeds, request `https://openidconnect.googleapis.com/v1/userinfo` with the stored access token and read `email`. A source that returns no email contributes nothing.

### When `refresh_identity()` runs

- After the Slack token is saved (`skills/slack/mcp_client.py::_save_token`).
- After a successful Google OAuth callback (`oauth/flow.py::handle_callback`).
- After a successful Microsoft device sign-in (`/api/auth/device/poll`).
- Once at backend startup.

Each call site wraps it so a failure cannot break the connection.

## API

`GET /api/identity` returns `get_identity()` as JSON, or `{"identity": null}` when none exists. It is read-only, so it needs no CSRF dependency.

## Errors

- A failed Slack or Google lookup is logged at warning level, with no token values, and leaves the previous record unchanged. The next trigger retries.
- A malformed or missing token yields no email for that source.

## Tests

- Microsoft claims produce the id, name, and source.
- A Slack lookup with a mocked Slack response fills `emails.slack`.
- A Google userinfo response fills `emails.google`.
- With all three connected, the primary is Microsoft and `emails` holds all three.
- With only Slack and Google connected, the primary is Slack.
- A failed lookup keeps the existing record.
- After the Microsoft token expires, `get_identity()` still returns the record.
- `/api/identity` returns the record, and `{"identity": null}` when empty.
- `/api/auth/status` returns the same email as before.
