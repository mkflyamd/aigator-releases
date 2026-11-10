# User Identity — Design

## Goal

Tie AI Gator usage to an individual user, identified by the Microsoft 365 account they signed in with. A user with no Microsoft sign-in has no identity and is not an active user. No groups, roles, or new sign-in screen.

The consumer is the daily usage report (`web/usage_report.py`, see the usage-report spec), which reports under this identity.

## Identity record

Stored in `secure_store` under `identity/profile`:

```json
{
  "id": "jane.doe@amd.com",
  "name": "Jane Doe"
}
```

`id` is the lowercased email taken from the Microsoft token claims.

## Component: `web/identity.py`

| Function | Purpose |
|---|---|
| `get_identity() -> dict \| None` | Returns the stored record, or `None` if the user has never signed in to Microsoft. |
| `refresh_identity() -> None` | Reads the `graph/token` claims (`upn`, then `preferred_username`, then `email`; and `name`), updates the record, and saves. Never raises. |

The claim-reading logic already in `/api/auth/status` moves into a shared helper in `identity.py`, and `/api/auth/status` calls it.

The record is kept after the token expires, so the identity stays stable.

## When `refresh_identity()` runs

- After a successful Microsoft device sign-in (`/api/auth/device/poll`).
- Once at backend startup.

Each call site wraps it so a failure cannot break sign-in.

## Errors

A malformed or missing token leaves the existing record unchanged.

## Tests

- Token claims produce the id and name.
- `upn`, `preferred_username`, and `email` are tried in that order.
- A malformed token keeps the existing record.
- After the token expires, `get_identity()` still returns the record.
- `/api/auth/status` returns the same email as before.
