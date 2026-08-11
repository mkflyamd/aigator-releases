# AI Gator — Build & Install Instructions

## Prerequisites (one-time setup)

| Tool | How to get |
|---|---|
| Python 3.12+ | Already installed (dev environment) |
| Inno Setup 6 | `winget install JRSoftware.InnoSetup` |
| Python deps | `pip install pystray Pillow` |
| Code signing cert | Optional — skip the signing step or use your own cert from DigiCert/Sectigo |

---

## ⚡ Running AI Gator (two front-door launchers)

AI Gator's UI runs inside the **Electron shell** (`shell/main.js`) — there is no
browser. The native Slack / Teams / Outlook panes only render inside Electron.

**Use these two launchers for everything. Do NOT double-click `AI Gator.exe`
directly** — that runs bare Electron (no shell path) and just shows Electron's
"run a local app" splash. (Windows also tends to re-pin the Start-Menu shortcut
to that bare exe, which is why we launch through scripts, not shortcuts.)

| Launcher | What it runs | Port |
|---|---|---|
| `.\launch-installed.ps1` | The **stable app**, via the tray (backend + Electron shell) | `:8000` |
| `.\launch-dev.ps1` | A clean **dev instance** (hot-reload backend + shell + DevTools MCP) | `:8003` |

Both live at the repo root; run them from `<your-project-directory>`.

### Stable app (everyday use)

```powershell
.\launch-installed.ps1            # start it
.\launch-installed.ps1 -Restart   # force a fully clean restart
```
Runs exactly like a real install: the tray starts the backend on `:8000` and
launches the Electron shell with the correct `shell/` path. Corruption-proof.

### Dev instance (test your changes)

```powershell
.\launch-dev.ps1                  # dev backend + shell on :8003
.\launch-dev.ps1 -Port 8002       # use a different dev port
```
`launch-dev.ps1`:
1. **Clears any stale/zombie backend on the dev port first** — the #1 cause of
   "it loaded the old app" (a dead uvicorn still holding the port makes the
   shell attach to old code).
2. Starts the hot-reload backend (in its own window).
3. Waits until the backend is actually ready.
4. Launches the Electron shell attached to it, always with
   `--remote-debugging-port=9222` for the Chrome DevTools MCP.

Runs on `:8003` so it never collides with the stable app on `:8000` — you can
run **both at once**.

- JS/CSS/HTML changes → **reload the shell window** (`Ctrl+R`)
- Python changes → the backend **auto-reloads**
- No need to rebuild the installer until you're ready to distribute

### Underlying scripts (advanced / usually not called directly)

The two launchers wrap these; call them directly only if you need fine control:

| Script | Role |
|---|---|
| `dev.ps1 -Port <n>` | Just the hot-reload backend on a port (no shell) |
| `dev-shell.ps1 -Port <n>` | Just the Electron shell attached to a backend (+ MCP `:9222`) |
| `dev-workbench.ps1` | Backend against an **isolated git worktree** (`<primary>-agent-work`) for coding-agent work you want quarantined from your primary checkout |

### Troubleshooting the dev workflow

| Problem | Fix |
|---|---|
| "run a local app" / Electron splash | You launched the bare exe. Use `.\launch-installed.ps1` (or `.\launch-dev.ps1`) instead — never `AI Gator.exe` directly |
| It loaded the OLD app / classic panes | A zombie backend held the port. `.\launch-dev.ps1` clears it automatically; if a port is stuck in a zombie LISTEN, use `-Port <other>` |
| Shell still shows old JS/CSS | Reload the shell window (`Ctrl+R`) to bust the cache |
| `dev-shell.ps1` can't find Electron | Run `npm install` in `shell\` manually, then retry (or just rerun the launcher — it installs on first use) |
| MCP can't attach | The shell must be launched by `launch-dev.ps1`/`dev-shell.ps1` (they add `--remote-debugging-port=9222`); only one Electron can hold the port |
| Native panes show as classic | Enable native mode in Settings (or set `slack_pane_mode`/`teams_pane_mode`/`outlook_pane_mode` = `"native"` in `~/.config/teamspoc/config.json`) |

---

## E2E test: full WakeGator run-from-source (do this before shipping)

This exercises the **real first-run user path** for the run-from-source track:
bundling the portable Electron, renaming/branding it, and launching the app via
the tray. Run it manually before relying on a build.

> WakeGator mutates the project dir: it creates `.venv`, `node/`, `electron/`,
> and Start-Menu shortcuts. Expected. Make sure your gateway/config is set
> (`docs/gateway-setup.md`) or the app will start but gate on the API key —
> still fine for testing the *launch* itself.

### Run it

```powershell
cd <your-project-directory>

# Optional — force a true first run (re-download Electron; delete .venv/node too
# for a full cold start):
Remove-Item electron -Recurse -Force -ErrorAction SilentlyContinue

.\WakeGator.ps1
```

### Watch the console (expected order)

1. Python 3.12 found
2. Node runtime (present, or downloads)
3. OpenCode (present, or installs)
4. Spinner: **"Downloading Electron 43.0.0"** (~150 MB) → **"Electron 43.0.0 ready."**
5. **"Branded the app icon (taskbar shows the gator)."** ← the rcedit step
6. venv + dependencies
7. "Waking the gator" → **an Electron window opens** (never a browser)

### Verify — the 5 checks

| # | Check | Where | Pass = |
|---|---|---|---|
| 1 | Launches in Electron | screen | App opens in an app window, no browser tab |
| 2 | Taskbar icon | Windows taskbar (bottom) | **Gator** icon; does **not** flip to the blue Electron atom |
| 3 | Installed apps | Settings → Installed apps | **"AI Gator"** listed; **no "Electron"** |
| 4 | Process name | Task Manager → Details | **`AI Gator.exe`** (not `electron.exe`) |
| 5 | No silent browser fallback | close app, delete `electron\`, then tray → "Open AI Gator" | **"Electron missing — re-run WakeGator"** dialog (never a browser) |

Also confirm the shell **attached** (didn't self-spawn a second backend): only one
tray-managed backend should be on `:8000`, and Task Manager should show no extra
stray uvicorn from Electron.

### If something fails, collect

- Console output around the failing step
- `%LOCALAPPDATA%\AIGator\logs\aigator.log` (tray + launch log)
- For a missing/atom icon, confirm rcedit applied:
  ```powershell
  (Get-Item "electron\AI Gator.exe").VersionInfo | Format-List ProductName, FileDescription
  # expect ProductName = AI Gator, FileDescription = AI Gator
  ```

---

## Regular build process

> **All commands below must be run from the project root:**
> `<your-project-directory>`
>
> Open PowerShell and run: `cd <your-project-directory>`

### Step 1 — Make your code changes

Edit files under `web/`, `skills/`, or `tray/` as needed.

### Step 2 — Delete stale launcher (only if tray script changed)

If you modified `tray/aigator_tray.py`, delete the cached exe so PyInstaller rebuilds it:

```powershell
cd <your-project-directory>
Remove-Item "build\AIGator.exe" -Force -ErrorAction SilentlyContinue
```

> Skip this step if you only changed `web/` or `skills/` files — the PyInstaller step will be skipped automatically.

### Step 3 — Run the build script

```powershell
cd <your-project-directory>
& "build\build.bat"
```

The script runs 5 steps:
1. Downloads embedded Python 3.12 (skipped if already present)
2. Configures embedded Python site-packages (skipped if done)
3. Installs Python dependencies into embedded Python (skipped if done)
4. Builds `AIGator.exe` with PyInstaller (skipped if `build\AIGator.exe` exists)
5. Packages everything with Inno Setup → outputs `build\dist\AIGatorInstaller.exe`

**Typical build time:** ~2 min (full) / ~30 sec (Inno Setup only)

### Step 4 — Distribute

Hand out `build\dist\AIGatorInstaller.exe`. Users double-click it — no Python needed.

---

## What the installer does

- Installs to `%APPDATA%\AIGator\`
- Bundles embedded Python runtime at `%APPDATA%\AIGator\python\`
- Puts app source at `%APPDATA%\AIGator\app\`
- Creates Start Menu shortcut
- Creates startup shortcut (auto-launches on login)
- On re-install: automatically kills running AI Gator processes and uninstalls the old version first

---

## Folder structure after build

```
build/
  build.bat              ← run this
  installer.iss          ← Inno Setup config
  make_icon.py           ← regenerate icons (run manually if needed)
  AIGator.exe            ← PyInstaller output (delete to force rebuild)
  python_dist/           ← embedded Python (auto-downloaded)
  dist/
    AIGatorInstaller.exe ← final installer to distribute
```

---

## Updating the app icon (permanent process)

1. Drop your new image at `tray\aigator_icon.png` (PNG, ideally 256×256 or larger)
2. Regenerate the `.ico` file used by the exe and Start Menu shortcut:
   ```powershell
   cd <your-project-directory>
   python build\make_icon.py
   # Reads tray\aigator_icon.png → writes build\aigator_icon.ico
   ```
   This reads your PNG and writes `build\aigator_icon.ico` automatically.
3. Force a full rebuild (PyInstaller must re-embed the new ico):
   ```powershell
   cd <your-project-directory>
   Remove-Item "build\AIGator.exe" -Force -ErrorAction SilentlyContinue
   & "build\build.bat"
   ```

> `make_icon.py` uses your existing `tray\aigator_icon.png` if present. It only draws the default gator if no PNG exists.

---

## Restarting the server during development

| Situation | What to do |
|---|---|
| Code changed, watchdog running | `curl -X POST http://localhost:8001/restart` |
| Watchdog itself changed | Kill both ports, re-run `python web/watchdog.py` from project root |
| Everything is broken | Run `web\start.bat` from the project root |

The watchdog on port 8001 supervises uvicorn on port 8000. Use its `/restart` endpoint to pick up `web/app.py` changes without manual port-killing.

---

## Testing as a new user (clean slate)

### Full reset (simulate brand-new user)

Three things need to be cleared: server-side config, app storage, and the server process.

**Step 1 — Delete server-side config** (PowerShell):

```powershell
# Deletes API key, OAuth tokens, Jira/Confluence/Slack credentials
Remove-Item "$env:USERPROFILE\.config\teamspoc\config.json" -Force -ErrorAction SilentlyContinue
Remove-Item "$env:USERPROFILE\.config\microsoft-graph" -Recurse -Force -ErrorAction SilentlyContinue
```

**Step 2 — Clear app storage** (in the Electron shell window, open DevTools with the DevTools MCP or the debug port `:9222`, then in the Console):

```js
localStorage.clear();
sessionStorage.clear();
```

**Step 3 — Restart the app** (PowerShell):

```powershell
.\launch-installed.ps1 -Restart
```

The app reopens in the Electron shell — you'll see the API key setup gate, then the onboarding tour.

### Cold auth test (clear tokens + webview sessions, keep API key)

For testing the Settings > Apps dashboard, sign-in flows, and native-pane auth
without re-entering your LLM gateway key. Clears agent tokens (M365 FOCI,
Teams `Chat.ReadWrite`, Slack OAuth), Electron `persist:*` webview sessions
(Slack/Teams/Outlook cookies + localStorage), and stale caches — but leaves
`~/.config/teamspoc/config.json` (API key, model, gateway) and MCP OAuth
tokens (`~/.gator/oauth/`) intact.

```powershell
.\reset-auth.ps1
```

The script stops all running instances first (so Windows file handles release
and `-ErrorAction SilentlyContinue` doesn't silently skip locked files), clears
token files for all known ports (8000/8002/8003), verifies the deletion, and
prints what to run next. Use `-KeepRunning` to clear state without killing
processes (some files may not delete if held open).

After cleaning, start fresh with `.\launch-dev.ps1` (or `.\launch-installed.ps1`),
then open Settings → Apps. The dashboard should show all dots red/grey, "Not
signed in" everywhere. Confirm with `curl http://localhost:8003/api/auth/status`
— should return `{"authenticated": false, "reason": "No token file"}`.

> **Don't run stable + dev at the same time when testing auth.** The stable
> app's tray does "identity sweeps" that can kill the dev Electron renderer
> mid-flow (manifests as an SSL handshake error in the console). Use one
> instance at a time for auth testing.

### Reset onboarding tour only (keep auth & chat history)

```js
localStorage.removeItem('onboarding-dismissed');
localStorage.removeItem('onboarding-step');
localStorage.removeItem('ob-help-coach-shown');
location.reload();
```

### Reset onboarding + chat history (keep auth)

```js
// Save auth-related keys, clear everything else
const apiKey = localStorage.getItem('gator-api-key');
localStorage.clear();
sessionStorage.clear();
if (apiKey) localStorage.setItem('gator-api-key', apiKey);
location.reload();
```

### Restart tour from the UI

Click **?** (help button, top-right) → **Restart Tour**

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `AIGator.exe already built, skipping` but you have tray changes | `cd <your-project-directory>` then `Remove-Item build\AIGator.exe -Force` |
| `AIGatorInstaller.exe` locked during build | Close any open installer window, rerun |
| Inno Setup not found | `winget install JRSoftware.InnoSetup` |
| App doesn't start after install | Check `%LOCALAPPDATA%\AIGator\logs\aigator.log` |
| Tray icon doesn't appear (stale lock) | `Remove-Item "$env:LOCALAPPDATA\AIGator\tray.lock" -Force` |
