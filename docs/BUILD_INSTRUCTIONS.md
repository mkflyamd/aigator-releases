# AI Gator development and build guide

AI Gator has two runtime components:

- `shell/`: the Electron desktop application.
- `web/`: the Python/FastAPI backend.

Development runs those components separately for fast reloads. Distribution builds compile the backend into a PyInstaller sidecar and bundle it with Electron through `electron-builder`. End users do not install Electron, Node.js, Python, or uv.

## Prerequisites

| Tool | Version | Purpose |
|---|---:|---|
| Git | current | Source checkout |
| uv | current | Python installation, locking, environments, and commands |
| Node.js | 22+ | Electron and electron-builder |
| npm | bundled with Node | JavaScript dependencies |

Platform notes:

- Windows: PowerShell 7 is recommended. Existing `.ps1` launchers also work in Windows PowerShell.
- macOS: install Xcode Command Line Tools. Native packages must be built on macOS.
- Linux: use a desktop session with the standard Electron/Chromium libraries supplied by mainstream desktop distributions.

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
- Changes under `web/static/` require reloading the Electron window.
- Changes under `shell/` require restarting Electron.
- The Chrome DevTools protocol is available on port `9222` in the commands above.
- Stop both processes when finished. Do not install the development backend as a system service.

## Run the source-install experience

This exercises the downloader used by source-based alpha installations. It creates `.venv/`, `node/`, and `electron/` in the checkout.

### Windows

```powershell
.\WakeGator.ps1
```

### macOS and Linux

```bash
bash WakeGator.sh
```

The legacy source installers currently maintain their own bootstrap flow. Prefer `uv sync --locked` for developer environments and native release packages for end users.

## Build native desktop packages locally

Build on the target operating system. PyInstaller sidecars and native installers are not reliably cross-compiled. The `dev` dependency group installed by `uv sync --locked` includes PyInstaller and test tools.

### 1. Build the backend sidecar

### Windows

```powershell
uv run pyinstaller --clean --noconfirm packaging\aigator-backend.spec --distpath dist\backend --workpath build\pyinstaller-desktop
```

### macOS and Linux

```bash
uv run pyinstaller --clean --noconfirm packaging/aigator-backend.spec --distpath dist/backend --workpath build/pyinstaller-desktop
```

Expected output:

- Windows: `dist/backend/aigator-backend.exe`
- macOS/Linux: `dist/backend/aigator-backend`

### 2. Build the Electron package

From the repository root:

### Windows x64

```powershell
npm --prefix shell exec electron-builder -- --win --x64 --publish never
```

### macOS Apple silicon

```bash
npm --prefix shell exec electron-builder -- --mac --arm64 --publish never
```

### macOS Intel

```bash
npm --prefix shell exec electron-builder -- --mac --x64 --publish never
```

### Linux x64

```bash
npm --prefix shell exec electron-builder -- --linux --x64 --publish never
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

Then run the project's relevant Python and JavaScript test suites. Finally, run the workflow manually and smoke-test each produced operating-system package.

## Troubleshooting

| Problem | Fix |
|---|---|
| `uv sync --locked` reports a stale lock | Run `uv lock`, review and commit `uv.lock`, then retry |
| Electron is missing during development | Run `npm install --prefix shell` |
| Backend does not start | Run the sidecar directly and inspect stderr; verify `dist/backend/` exists before packaging |
| Shell opens old code | Stop old Electron/backend processes and use a different dev port |
| Native package contains no backend | Re-run the PyInstaller step before electron-builder |
| macOS build cannot create DMG | Build on macOS with Xcode Command Line Tools installed |
| Linux AppImage will not execute | `chmod +x` the file and verify FUSE/AppImage support |
| Windows or macOS warns on launch | Configure code signing; local packages are unsigned by default |
| Release assets are missing | Check the `Build desktop release` workflow and its per-platform artifact uploads |
