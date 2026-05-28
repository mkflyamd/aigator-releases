# AI Gator — Build & Install Instructions

## Prerequisites (one-time setup)

| Tool | How to get |
|---|---|
| Python 3.12+ | Already installed (dev environment) |
| Inno Setup 6 | `winget install JRSoftware.InnoSetup` |
| Python deps | `pip install pystray Pillow` |
| Code signing cert | Optional — skip the signing step or use your own cert from DigiCert/Sectigo |

---

## ⚡ Hot-testing changes (use this while developing)

**Start here whenever you're making frontend or backend changes.** No build needed — edits to `web/` are live immediately.

```powershell
cd <your-project-directory>
.\dev.ps1
```

Then open **http://localhost:8000** in your browser.

- JS/CSS/HTML changes → just **hard-refresh** the browser (`Ctrl+Shift+R`)
- Python (`app.py`) changes → uvicorn **auto-restarts** the server
- No need to rebuild the EXE until you're ready to distribute

> **What `dev.ps1` does:** Kills any running AIGator process or uvicorn on port 8000 (including the installed tray app), then starts the dev server from the project directory with `--reload` enabled.

> **Why not just run the installed EXE?** Nuitka bundles all static files at build time. Any change to `web/static/` is invisible to the installed app until you rebuild. The dev server sidesteps this entirely.

### Troubleshooting the dev server

| Problem | Fix |
|---|---|
| `Access is denied` on port 8000 | Close the AI Gator tray app first, then rerun `.\dev.ps1` |
| Still serving old code after `dev.ps1` | Hard-refresh the browser (`Ctrl+Shift+R`) to bust the JS/CSS cache |
| Health check shows wrong `file:` path | Another uvicorn is still running — rerun `.\dev.ps1` to kill it |

---

## Regular build process

> **All commands below must be run from the project root:**
> `<your-project-directory>`
>
> Open PowerShell and run: `cd <your-project-directory>`

### Step 1 — Make your code changes

Edit files under `web/`, `skills/`, or `tray/` as needed.

### Step 2 — Delete stale launcher (only if tray script changed)

If you modified `tray/aigator_tray.py`, delete the cached exe so Nuitka rebuilds it:

```powershell
cd <your-project-directory>
Remove-Item "build\AIGator.exe" -Force -ErrorAction SilentlyContinue
```

> Skip this step if you only changed `web/` or `skills/` files — Nuitka step will be skipped automatically.

### Step 3 — Run the build script

```powershell
cd <your-project-directory>
& "build\build.bat"
```

The script runs 5 steps:
1. Downloads embedded Python 3.12 (skipped if already present)
2. Configures embedded Python site-packages (skipped if done)
3. Installs Python dependencies into embedded Python (skipped if done)
4. Builds `AIGator.exe` with Nuitka (skipped if `build\AIGator.exe` exists)
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
  AIGator.exe            ← Nuitka output (delete to force rebuild)
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
3. Force a full rebuild (Nuitka must re-embed the new ico):
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

Three things need to be cleared: server-side config, browser storage, and the server process.

**Step 1 — Delete server-side config** (PowerShell):

```powershell
# Deletes API key, OAuth tokens, Jira/Confluence/Slack credentials
Remove-Item "$env:USERPROFILE\.config\teamspoc\config.json" -Force -ErrorAction SilentlyContinue
Remove-Item "$env:USERPROFILE\.config\microsoft-graph" -Recurse -Force -ErrorAction SilentlyContinue
```

**Step 2 — Clear browser storage** (browser console, `F12` → Console on `http://localhost:8000`):

```js
localStorage.clear();
sessionStorage.clear();
```

**Step 3 — Restart the server** (PowerShell):

```powershell
.\dev.ps1
```

Open `http://localhost:8000` — you'll see the API key setup gate, then the onboarding tour.

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
