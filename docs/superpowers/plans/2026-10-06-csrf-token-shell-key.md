# CSRF token behind a shell key — implementation plan

Spec: `docs/superpowers/specs/2026-10-06-csrf-token-shell-key-design.md`. One task, TDD.

## Task 1: shell key

Files: `web/security.py`, `web/routes/health.py`, `shell/main.js`, `tests/test_shell_key.py` (new),
`tests/test_desktop_packaging.py` (one static assertion), docs.

1. Tests first (`tests/test_shell_key.py`), using FastAPI `TestClient` on `web.app`:
   - key set (monkeypatch `security._SHELL_KEY`): `GET /api/csrf` and `GET /` give 403 without the
     header and with a wrong value, 200 with `X-AIGator-Shell-Key: aigator-fake-api-key` configured as
     the key; the 200 body of `/api/csrf` contains the real token.
   - key unset: both 200 with no header.
   - `verify_csrf`-guarded route still needs `X-CSRF-Token` (unchanged).
   - env scrub: set `AIGATOR_SHELL_KEY`, `importlib.reload(security)`, assert `_SHELL_KEY` equals it and
     `AIGATOR_SHELL_KEY` is not in `os.environ`.
   - `sandbox.build_env({"AIGATOR_SHELL_KEY": "x", ...}, ...)` output has no `AIGATOR_SHELL_KEY`.
2. `web/security.py`: `_SHELL_KEY = os.environ.pop("AIGATOR_SHELL_KEY", "") or None` at import;
   `async def require_shell_key(x_aigator_shell_key: str | None = Header(default=None))` that returns
   when `_SHELL_KEY is None`, else 403 unless `secrets.compare_digest`. Update the module docstring.
3. `web/routes/health.py`: `dependencies=[Depends(require_shell_key)]` on `GET /api/csrf` and `GET /`.
4. `shell/main.js`: `const SHELL_KEY = SPAWN_BACKEND ? require('crypto').randomBytes(32).toString('hex') : ''`;
   `backendEnv.AIGATOR_SHELL_KEY = SHELL_KEY` in `startBackend` (only when set); in the existing
   `gatorSession.webRequest.onBeforeSendHeaders`, add `details.requestHeaders['X-AIGator-Shell-Key']`
   when `SHELL_KEY` is set and `new URL(details.url).origin === new URL(GATOR_URL).origin` (guard the
   URL parse with try/catch). Add a static assertion in `tests/test_desktop_packaging.py` that
   `main.js` contains `AIGATOR_SHELL_KEY` and `X-AIGator-Shell-Key`.
5. Docs: tracker row `_05` -> implemented; sandbox spec Known gaps: replace the Linux localhost
   paragraph with "closed by the shell key (M_..._05); a network-approved Linux run can still reach
   the localhost API but cannot get the token"; BUILD_INSTRUCTIONS note on browser-only dev mode.
6. Run focused tests (`tests/test_shell_key.py`, `tests/test_desktop_packaging.py`,
   `tests/code_sandbox`, `web/tests/test_outlook_native_hitl.py`). Commit without Co-Authored-By.
