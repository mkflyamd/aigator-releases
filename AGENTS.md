# AGENTS.md

High-signal guidance for agents working in the **AI Gator** repo. Supplement to `CLAUDE.md` (which has the non-negotiable project rules — read it first).

## Project rules (from CLAUDE.md — non-negotiable)

- **Name**: "AI Gator" — never "POC".
- **LLM gateway**: every LLM call goes through `web/llm/gateway.py` (`from llm.gateway import ...` works because `web/` is on `sys.path`). Never construct gateway headers/URLs inline. See `docs/gateway-setup.md`.
- **Commits**: no `Co-Authored-By` lines.
- **Human-in-the-loop**: email, Teams, and Slack messages are **draft-only** — never auto-send.

## Architecture

Two runtime components, run separately in dev:

- `web/` — FastAPI backend. Entrypoint `web.app:app` (uvicorn). `web/app.py` injects `truststore` into SSL **before** any TLS module loads (corporate MITM roots) and runs config migration (`~/.config/teamspoc` → `~/.gator`) before importing `shared`.
- `shell/` — Electron desktop app (`shell/main.js`). No browser; the UI is the Electron shell. Receives `GATOR_URL` to attach to a dev backend instead of spawning its packaged sidecar.

Mutable shared state lives in `web/shared.py` (`shared.cfg`, `shared.TOOLS`, `shared.TOOL_DISPATCH`, …). Route modules under `web/routes/` import `shared` to avoid circular deps with `app.py`.

User state lives in `~/.gator/` (`config.json`, `tasks.db`, `scheduler.db`, `outputs/`, `work/`, `plugins/`, `skills/`). Config keys: `api_key`, `llm_gateway_url`, `llm_gateway_key_header`, `llm_gateway_user_field`, `gateway_user_id` (env var overrides documented in `docs/gateway-setup.md`).

### Skills

Adding a skill needs **zero changes to `app.py`** — drop `web/skills/<name>/` with `__init__.py` and `tools.py` exporting `TOOL_DEFS`, `TOOL_STATUS`, `TOOL_HANDLERS`. The loader picks it up on restart. Full contract: `docs/How_to_add_skill.md`.

## Toolchain & setup

- **uv** (not pip). Python 3.12–3.13, Node 22+. `uv sync --locked` creates `.venv/` from `uv.lock`.
- After changing `pyproject.toml`: `uv lock`, review `uv.lock`, commit both. CI rejects stale lockfiles.
- `npm install --prefix shell` for the Electron shell.
- No enforced linter/formatter (`.ruff_cache/` exists but no config — ignore it). Follow existing conventions.
- `opencode.json` is gitignored (regenerated per-run by `run-opencode.ps1`); `version.txt` is the version source of truth.

## Dev commands

Windows one-shot (clears stale procs, starts hot-reload backend, waits for `/health`, opens Electron with `--remote-debugging-port=9222`):

```powershell
.\launch-dev.ps1                 # dev backend + shell on :8003
.\launch-dev.ps1 -Port 8002 -DebugPort 9223
```

Backend only (hot-reload, watched `*.py` under `web/`):

```powershell
.\dev.ps1            # primary instance on :8000
.\dev.ps1 -Port 8002 # workbench instance
```

macOS/Linux dev — two terminals:

```bash
uv run uvicorn web.app:app --host 127.0.0.1 --port 8003 --reload
GATOR_URL=http://127.0.0.1:8003 GATOR_DEV=1 npm --prefix shell start -- --remote-debugging-port=9222
```

**Port conventions** (don't violate): `8000` = primary/stable, `8001` = **watchdog — reserved, never use**, `8002` = workbench, `8003+` = dev instances. A dev server left on `:8000` collides with the packaged app's OpenCode-server ownership — run dev on a non-8000 port.

Reload behavior: `web/*.py` → uvicorn hot-reloads; `web/static/` → Ctrl+R in the shell; `shell/` → restart Electron.

`dev.ps1` reload-exclude patterns use **surrounding-wildcard** forms (`*node_modules*`, `*__pycache__*`), never path-style globs — Click glob-expands path globs on Windows and uvicorn rejects them as extra args.

## Tests

```bash
uv run pytest -q                                    # whole suite
uv run pytest tests/<area>/test_x.py::test_y -v     # single test
uv run pytest -q tests/test_desktop_packaging.py    # pre-release packaging checks
```

- `pytest.ini`: `asyncio_mode = auto` (async tests need no marker).
- `tests/conftest.py` adds `web/` to `sys.path` so bare imports (`import shared`) resolve. Tests live in both `tests/` and `web/tests/`.
- Pre-release: `uv lock --check && uv sync --locked`, then the Python + JS suites.

## Worktree workflow

`dev-workbench.ps1` spins up an isolated worktree at `<primary>-agent-work/` on branch `agent-work` (backend on `:8002`). After merging `agent-work` into `main`, sync the worktree with `git reset --hard main` (don't tear it down — that redoes `.venv` for nothing). **Stop the `:8002` server before `reset --hard`** (Windows file-handle issue). Full flow: `docs/dev_INSTRUCTIONS.md`.

## Build & release

PyInstaller sidecar → electron-builder. Build on the target OS (no reliable cross-compile).

```bash
uv run pyinstaller --clean --noconfirm packaging/aigator-backend.spec --distpath dist/backend --workpath build/pyinstaller-desktop
npm --prefix shell run dist -- --win --x64 --publish never   # or --mac/--linux
```

`npm run dist` auto-runs `packaging/sync_version.py` (syncs `version.txt` → `shell/package.json`). Output: `dist/installers/`. Packages are unsigned locally. Publishing a GitHub release triggers `.github/workflows/release-desktop.yml` (Win x64, macOS x64/arm64, Linux x64).

## OpenCode integration

`web/skills/opencode_agent/instance_manager.py` owns one `opencode serve` subprocess per project (ports 8100–8200, idle-reaped after 30 min). Per-project spawn locks prevent duplicate servers. The explore subagent is hardcoded to `gator-gateway/gpt-4.1` regardless of the project's main model. This Gator instance's identity = its uvicorn `--port` (derived from argv, not an env var).

## upper-fixer skill

`.claude/skills/upper-fixer/SKILL.md` orchestrates GitHub-issue fixing. Works directly on local `main` (no worktree/branch), one commit per issue, never auto-merge/push/comment/close. Risky changes (destructive shell ops, `replace_all`, >30 lines or >1 file, cross-cutting files like `web/static/style.css`) require a change-review subagent before applying. Session state: `.gator-session.json` (gitignored).
