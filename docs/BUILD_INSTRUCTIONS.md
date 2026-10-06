# AI Gator development and build guide

AI Gator has two runtime components:

- `shell/`: the Electron desktop application.
- `web/`: the Python/FastAPI backend.

Development runs those components separately for fast reloads. Distribution builds compile the backend into a PyInstaller sidecar and bundle it with Electron through `electron-builder`. End users do not install Electron, Node.js, Python, or uv.

## Prerequisites

| Tool    |           Version | Purpose                                                  |
| ------- | ----------------: | -------------------------------------------------------- |
| Git     |           current | Source checkout                                          |
| uv      |           current | Python installation, locking, environments, and commands |
| Node.js |               22+ | Electron and electron-builder                            |
| npm     | bundled with Node | JavaScript dependencies                                  |

Platform notes:

- Windows: PowerShell 7 is recommended. Existing `.ps1` launchers also work in Windows PowerShell.
- macOS: install Xcode Command Line Tools. Native packages must be built on macOS.
- Linux: use a desktop session with the standard Electron/Chromium libraries supplied by mainstream desktop distributions, and install `bubblewrap` (see "Linux: bubblewrap" below). The `.deb` declares it; the AppImage cannot, so AppImage users must install it themselves.

The project pins Python compatibility and dependencies in `pyproject.toml` and `uv.lock`. Do not install project dependencies with global pip.

## Initial checkout

Run from the repository root on every platform:

```bash
git clone https://github.com/mkflyamd/aigator-releases.git
cd aigator-releases
uv sync --locked
npm install --prefix shell
```

`uv sync --locked` installs a compatible Python automatically when needed and creates `.venv/` from the committed lockfile. Configure the gateway in `~/.config/teamspoc/config.json`; see [gateway-setup.md](gateway-setup.md).

After changing `pyproject.toml`, run `uv lock`, review `uv.lock`, and commit both files. Use `uv sync --locked` in clean environments and CI to reject stale lockfiles.

## Run in development

Use a non-production port such as `8003`. The Electron shell receives `GATOR_URL`, so it attaches to the dev backend instead of starting its packaged sidecar.

### Windows: one-command launcher

```powershell
.\launch-dev.ps1
```

Use `-Port 8002` or `-DebugPort 9223` when the defaults are occupied. The launcher clears stale processes, starts the reloadable backend, waits for health, and opens Electron. Run `uv sync --locked` first so `.venv` exists for the PowerShell launcher.

### macOS and Linux: two terminals

Terminal 1:

```bash
uv run uvicorn web.app:app --host 127.0.0.1 --port 8003 --reload
```

Terminal 2:

```bash
GATOR_URL=http://127.0.0.1:8003 \
GATOR_DEV=1 \
npm --prefix shell start -- --remote-debugging-port=9222
```

Development behavior:

- Python changes reload automatically through uvicorn.
- The backend started by hand (as above) has no `AIGATOR_SHELL_KEY`, so `GET /` and `GET /api/csrf` stay open and the page also works in an ordinary browser. In the packaged app (or when the shell spawns the backend itself) those two routes require a per-launch key that only the AI Gator window sends, and opening `http://127.0.0.1:8000/` in a browser returns 403.
- Changes under `web/static/` require reloading the Electron window.
- Changes under `shell/` require restarting Electron.
- The Chrome DevTools protocol is available on port `9222` in the commands above.
- Stop both processes when finished. Do not install the development backend as a system service.

## Release installers

`Get-AIGator.ps1` and `Get-AIGator.sh` install the latest native package published on GitHub. They do not install from source or use the legacy `WakeGator.*` bootstrap flow.

Both scripts resolve release metadata through the GitHub API, select the package for the detected operating system and architecture, verify it with `SHA256SUMS.txt` or the GitHub-provided SHA-256 asset digest, and log every operation. The Unix installer accepts `--no-launch`; the Windows NSIS finish screen controls launch behavior. Pass `-KeepDownload` or `--keep-download` to retain temporary files for troubleshooting. Use `-DryRun` or `--dry-run` to exercise release selection, download, and verification without installing or launching AI Gator. CI runs these dry-run flows against mocked release metadata and package downloads on its supported operating systems.

Supported targets are Windows x64, macOS x64/arm64, and Linux x64. Windows runs the NSIS package, macOS copies the application from the DMG to `~/Applications`, and Linux installs the AppImage for the current user without requiring root access.

## Build native desktop packages locally

Build on the target operating system. PyInstaller sidecars and native installers are not reliably cross-compiled. The `dev` dependency group installed by `uv sync --locked` includes PyInstaller and test tools.

### 1. Build the backend sidecar

### Windows

```powershell
uv run pyinstaller --clean --noconfirm packaging\aigator-backend.spec --distpath dist --workpath build\pyinstaller-desktop
```

### macOS and Linux

```bash
uv run pyinstaller --clean --noconfirm packaging/aigator-backend.spec --distpath dist --workpath build/pyinstaller-desktop
```

Expected output:

- Windows: `dist/backend/aigator-backend.exe`
- macOS/Linux: `dist/backend/aigator-backend`
- Plus the bundle folder `dist/backend/_internal/` (onedir build; ship the whole `dist/backend/` folder).

### 2. Build the Electron package

`version.txt` is the version source of truth. Before packaging, synchronize Electron metadata:

```bash
uv run python packaging/sync_version.py
```

The `npm run dist` command performs this synchronization automatically. From the repository root:

### Windows x64

```powershell
npm --prefix shell run dist -- --win --x64 --publish never
```

### macOS Apple silicon

```bash
npm --prefix shell run dist -- --mac --arm64 --publish never
```

### macOS Intel

```bash
npm --prefix shell run dist -- --mac --x64 --publish never
```

### Linux x64

```bash
npm --prefix shell run dist -- --linux --x64 --publish never
```

Packages are written to `dist/installers/`:

- Windows: NSIS `.exe`
- macOS: `.dmg` and `.zip`
- Linux: `.AppImage` and `.deb`

Local packages are unsigned unless signing credentials are configured. Windows SmartScreen and macOS Gatekeeper may warn about unsigned artifacts.

## Smoke-test a local package

Test on a machine without the repository's `.venv` or `node_modules` on `PATH`.

1. Install or launch the generated artifact.
2. Confirm one AI Gator window opens and no browser tab opens.
3. Confirm the app reaches `/health` and displays the configured version.
4. Confirm closing the app also stops `aigator-backend`.
5. Exercise one native pane and one backend tool.
6. Reopen the app and verify session/config persistence.

For Linux AppImage testing:

```bash
chmod +x dist/installers/*.AppImage
./dist/installers/*.AppImage
```

## Automated release builds

Publishing a GitHub release triggers `.github/workflows/release-desktop.yml`. Native GitHub runners build:

- Windows x64
- macOS x64
- macOS arm64
- Linux x64

The workflow uses `uv sync --locked` and `uv run` for the backend build, then attaches all packages and `SHA256SUMS.txt` to the release. A manual workflow dispatch builds the same packages as workflow artifacts without publishing a release.

The release workflow currently disables automatic signing discovery. Configure Windows signing and Apple signing/notarization credentials before broad distribution.

## Tests before release

Run the targeted packaging checks:

```bash
uv run pytest -q tests/test_desktop_packaging.py
```

Verify the dependency graph before release:

```bash
uv lock --check
uv sync --locked
```

Before committing, run the same generated-file checks that CI runs:

```bash
.venv/Scripts/pre-commit run --all-files --show-diff-on-failure   # Windows
# or
.venv/bin/pre-commit run --all-files --show-diff-on-failure       # macOS/Linux
```

**Important — three rules that prevent repeated CI failures:**

**Rule 1: Always use the pinned pre-commit, never `npx prettier`.**
CI pins prettier at v3.6.2 (`.pre-commit-config.yaml`). The version bundled in
`shell/node_modules` is different and formats files differently — files that look
clean locally will fail CI. Only `.venv/Scripts/pre-commit` uses the pinned version.

**Rule 2: Review `git diff --stat` before every commit.**
Pre-commit may rewrite files you did not intentionally change (`.secrets.baseline`,
CSS, JS). If pre-commit rewrites a file you did not touch, investigate before staging
it — another agent may have uncommitted changes in that file that you would be
inadvertently committing. Never commit files outside the scope of your change.

**Rule 3: Check for other agents' work before starting.**
Before starting work on a branch run `git status` and `git stash list`. If another
agent has uncommitted changes, coordinate with them first. Mixing two agents'
uncommitted work in a single commit breaks tests and is hard to untangle.

Pre-commit may intentionally rewrite files. In particular, `detect-secrets`
updates `.secrets.baseline` when a detected test fixture moves, and Prettier may
reformat JavaScript or CSS. After pre-commit rewrites files, stage only the intended
changes and **re-run pre-commit until it passes with no modifications**:

```bash
# Loop until clean — typically 1-2 passes
.venv/Scripts/pre-commit run --all-files   # Windows
git add -u
.venv/Scripts/pre-commit run --all-files   # must print "Passed" with no rewrites
```

Do not commit until `git status --short` contains only the intended changes and
`git diff --check` is clean.

Then run the project's relevant Python and JavaScript test suites. Finally, run the workflow manually and smoke-test each produced operating-system package.

## Code sandbox

AI Gator runs model-written `run_python` code in an OS sandbox: Windows AppContainer (built in, no admin), macOS Seatbelt (`/usr/bin/sandbox-exec`, built in), Linux bubblewrap. If the sandbox cannot start, running code is blocked and Settings shows the reason; the user may allow unsandboxed runs there unless the admin policy requires the sandbox.

### Linux: bubblewrap

```bash
sudo apt install bubblewrap      # Debian/Ubuntu
sudo dnf install bubblewrap      # Fedora/RHEL
bwrap --unshare-all --ro-bind / / -- true && echo ok
```

If the last command fails, unprivileged user namespaces are disabled or restricted (for example `kernel.unprivileged_userns_clone=0`, or the Ubuntu 24.04+ AppArmor restriction `kernel.apparmor_restrict_unprivileged_userns=1` without a bwrap profile). Ask the administrator to allow them for bubblewrap; AI Gator does not change system settings.

### Admin policy file

`%ProgramData%\AIGator\sandbox-policy.json` (Windows), `/Library/Application Support/AIGator/sandbox-policy.json` (macOS), `/etc/aigator/sandbox-policy.json` (Linux; must be root-owned and not group/world-writable):

```json
{"code_runner": "enabled", "network": "ask", "filesystem": "ask", "require_sandbox": false}
```

`code_runner: disabled` blocks code execution, `network: deny` refuses network requests, `filesystem: strict` refuses extra paths, `require_sandbox: true` hides the user opt-out. A present but invalid file fails closed (`network: deny`, `filesystem: strict`, `require_sandbox: true`). The file must be UTF-8 without a BOM (a BOM makes it invalid). On Windows the file's ACL is not checked, so restrict write access to `%ProgramData%\AIGator` to administrators.

### Code sandbox smoke test (release gate)

Verification status, stated plainly: the Linux launcher was run for real only in WSL Ubuntu (bubblewrap 0.11.1); the macOS Seatbelt profile has never been run on a real Mac (its builder is unit tested only). On Windows, the six real-run tests passed on the development machine on 2026-10-06 (run-folder write, denied read outside it, network denial, tree kill, stale-ACE sweep, extra-path grants), and Windows 10, antivirus/EDR reactions, long paths and loopback exemptions are untested. The Mac and Linux smoke tests below are release gates and have not been run yet.

Windows: `python -m pytest tests/code_sandbox/test_launcher_windows.py -q -s -m real_sandbox` (6 tests; the network test may skip if `1.1.1.1:443` is unreachable) passed on the dev machine on 2026-10-06; re-run it on any Windows machine you ship from.

The macOS and Linux launchers are covered by unit tests on Windows (and Linux through WSL Ubuntu). Before a release, also run on a real Mac and on a real Linux desktop (installed package, not a dev checkout):

1. `python3 tests/code_sandbox/posix_sandbox_check.py macos` (or `linux`) from a checkout on that machine: `probe` is `null`, `default.read_secret`, `default.read_secret_via_data_volume` (on macOS the same secret through `/System/Volumes/Data`), `default.read_extra` and `default.net_external` start with `DENIED`, `default.token` is `null`, `with_extra.read_extra` is `OK:extra-data`, `tree_kill.timed_out` is `true`, `leftover_sleepers` is `0`.
2. In the installed app ask: "Use run_python to make a PNG chart in OUTPUT_DIR": the file is returned.
3. Ask: "Use run_python to read ~/Documents/<some file>": an approval card appears; Approve runs it once; asking again shows a new card; Deny is not retried.
4. Ask for a network call to `example.com:443`: card mentions network for the whole run; approved run succeeds; unapproved run fails with the `[sandbox]` hint.
5. Rename `bwrap` away (Linux) or run on a machine without it: Settings shows the notice and the opt-out checkbox; code is blocked until opted out.

Record the result (date, OS version, pass/fail per step) in the PR before release.

Known gaps: `run_shell` is not sandboxed and bypasses this control; `packages=[...]` pip installs of any PyPI name run unsandboxed in the server process with the full environment and need no approval; network approval is all-or-nothing per run (the host is shown but not enforced); on Linux a network-approved run shares the host network namespace, so the code can still reach AI Gator's localhost API, but it cannot get the CSRF token (served only to the AI Gator shell via a per-launch shell key, `M_Localhost_CSRF_token_exposure_via_browse_05`), so it cannot approve its own requests (Windows AppContainer blocks loopback; macOS denies `localhost:*` in the profile, not verified on a real Mac); on Windows the run lock is per process, so two backends running at once (dev and desktop) share the container SID and ledger and one backend's launch-time sweep can revoke the other's grants; the macOS `/System/Volumes/Data` deny rule has not been run on a real Mac; same-user malware and OS sandbox escapes are out of scope.

## Troubleshooting

| Problem                                                | Fix                                                                                                                                    |
| ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| `uv sync --locked` reports a stale lock                | Run `uv lock`, review and commit `uv.lock`, then retry                                                                                 |
| `ModuleNotFoundError: No module named 'annotated_doc'` | The venv is broken — the running dev server locked a package during install. Stop the dev server and run `uv sync --locked` to repair. |
| Electron is missing during development                 | Run `npm install --prefix shell`                                                                                                       |
| Backend does not start                                 | Run the sidecar directly and inspect stderr; verify `dist/backend/` exists before packaging                                            |
| Shell opens old code                                   | Stop old Electron/backend processes and use a different dev port                                                                       |
| Native package contains no backend                     | Re-run the PyInstaller step before electron-builder                                                                                    |
| macOS build cannot create DMG                          | Build on macOS with Xcode Command Line Tools installed                                                                                 |
| Linux AppImage will not execute                        | `chmod +x` the file and verify FUSE/AppImage support                                                                                   |
| Windows or macOS warns on launch                       | Configure code signing; local packages are unsigned by default                                                                         |
| Code runs fail with "code sandbox is unavailable"      | Linux: install `bubblewrap` and allow unprivileged user namespaces (see "Code sandbox"); Windows/macOS: see the reason in Settings     |
| Release assets are missing                             | Check the `Build desktop release` workflow and its per-platform artifact uploads                                                       |
