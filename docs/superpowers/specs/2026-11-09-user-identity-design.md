# User Identity — Design

## Goal

Tie AI Gator usage to an individual user, identified by the Microsoft 365 account they signed in with. A user with no Microsoft sign-in has no identity and is not an active user. No groups, roles, or new sign-in screen.

The consumer is the daily usage report (`web/usage_report.py`, see the usage-report spec), which reports under this identity.

## Component: `web/identity.py`

| Function                         | Purpose                                                                                                                                                                 |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `email_from_token(token) -> str` | Reads the token claims and returns the lowercased email from `upn`, then `preferred_username`, then `email`. Returns `""` for a malformed token or a claim without `@`. |
| `get_identity() -> dict \| None` | Reads the stored `graph/token` and returns `{"id": email, "name": name}`, or `None` when there is no token or no email.                                                 |

Nothing extra is stored. The stored access token keeps its claims after it expires, so the identity stays available until the user signs out.

## Tests

`tests/test_identity.py`:

- `upn`, `preferred_username` and `email` are tried in that order, and the result is lowercased.
- A claim without `@`, a malformed token and an empty token give no email.
- `get_identity()` works from an expired stored token and returns `None` with no token.
