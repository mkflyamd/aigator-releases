# CSRF token behind a shell key (finding M_Localhost_CSRF_token_exposure_via_browse_05)

## Problem

The CSRF token that guards every human-approval route (draft send, sandbox approve, Jira create and
others) is served to anyone who can reach the local API: `GET /` embeds it in the page and
`GET /api/csrf` returns it as JSON. Anything that can open a connection to 127.0.0.1 can therefore
obtain a valid token and approve its own requests. Three paths matter:

1. a network-approved Linux code-runner run (shares the host network, so it reaches 127.0.0.1);
2. a DNS-rebinding web page in the user's browser;
3. any other local process that is not AI Gator's window (including an unsandboxed `run_shell`).

## Decision

The Electron shell proves it is the shell with a per-launch secret that the sandboxed code and
other local processes do not have.

- Electron generates 32 random bytes (hex) at start, only when it spawns the backend itself, and
  passes them to the backend in the environment variable `AIGATOR_SHELL_KEY`.
- Electron adds the header `X-AIGator-Shell-Key: <key>` to every request its default session sends to
  the AI Gator backend origin (`GATOR_URL`), in the existing `onBeforeSendHeaders` hook. Requests to
  any other origin never carry it.
- The backend reads `AIGATOR_SHELL_KEY` once at import and removes it from `os.environ`, so child
  processes (pip, shells, sandboxed runs) cannot inherit it. `web/security.py` gets a FastAPI
  dependency `require_shell_key`; it is applied to `GET /` and `GET /api/csrf` only. When a key is
  configured, a request without the exact key gets 403. The comparison is constant time.
- When no key is configured (backend started by hand, `GATOR_URL` dev setups, tests) behaviour is
  unchanged. This is the documented dev mode; the packaged app always sets the key.

Nothing else changes: the CSRF token stays per process, `verify_csrf` is unchanged, static files and
`/health` stay open.

## Why this and not the alternatives

- Host or Origin checks stop DNS rebinding but not a local process, which can set any header.
- Blocking loopback in the Linux sandbox needs a user-mode network stack, which is out of proportion.
- A cookie set by `/` is obtainable by the same bare GET.

## Behaviour change to document

In the packaged app the API page is served only to the AI Gator window. Opening
`http://127.0.0.1:<port>/` in an ordinary browser returns 403. Run the backend by hand (no
`AIGATOR_SHELL_KEY`) for browser-only development.

## Out of scope and known limits

- Same-user malware that can read the backend's memory or attach to Electron is out of scope.
- The key protects only the token endpoints. Other unauthenticated GET/POST routes that are not
  CSRF-guarded are separate findings.
- OAuth callbacks (`/oauth/callback`) stay open because the system browser must reach them.

## Acceptance

- With a key set, `GET /` and `GET /api/csrf` return 403 without the header or with a wrong one, and
  200 with the right one.
- With no key set, both return 200 as before.
- `AIGATOR_SHELL_KEY` is absent from `os.environ` after `web.security` is imported.
- The sandbox environment allow-list does not contain `AIGATOR_SHELL_KEY`.
- `shell/main.js` generates the key, passes it in the backend env, and adds the header only for the
  backend origin.
