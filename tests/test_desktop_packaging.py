import importlib.util
import json
from pathlib import Path

from PIL import Image
import yaml


ROOT = Path(__file__).parent.parent


def _load_backend_entry():
    spec = importlib.util.spec_from_file_location(
        "aigator_backend_entry", ROOT / "packaging" / "backend_entry.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_electron_builder_bundles_backend_and_platform_targets():
    package = json.loads((ROOT / "shell" / "package.json").read_text(encoding="utf-8"))
    package_lock = json.loads(
        (ROOT / "shell" / "package-lock.json").read_text(encoding="utf-8")
    )
    build = package["build"]
    version = (ROOT / "version.txt").read_text(encoding="utf-8").strip()

    assert package["version"] == version
    assert package_lock["version"] == version
    assert package_lock["packages"][""]["version"] == version
    assert package["devDependencies"]["electron-builder"]
    assert {entry["to"] for entry in build["extraResources"]} >= {
        "backend",
        "tray/aigator_icon.png",
    }
    assert build["win"]["target"] == ["nsis"]
    assert set(build["mac"]["target"]) == {"dmg", "zip"}
    assert set(build["linux"]["target"]) == {"AppImage", "deb"}


def test_shared_desktop_icon_meets_platform_size_requirements():
    with Image.open(ROOT / "tray" / "aigator_icon.png") as icon:
        assert icon.size == (512, 512)


def test_release_workflow_builds_every_supported_platform():
    workflow_path = ROOT / ".github" / "workflows" / "release-desktop.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)
    includes = workflow["jobs"]["build"]["strategy"]["matrix"]["include"]

    assert {entry["name"] for entry in includes} == {
        "Windows x64",
        "macOS x64",
        "macOS arm64",
        "Linux x64",
    }
    macos_targets = [entry for entry in includes if entry["name"].startswith("macOS")]
    assert all(entry["startup_attempts"] >= 360 for entry in macos_targets)
    assert "${{ matrix.startup_attempts }}" in workflow_text
    assert workflow[True]["release"]["types"] == ["published"]
    assert "astral-sh/setup-uv@" in workflow_text
    assert "uv sync --locked" in workflow_text
    assert "uv run python packaging/sync_version.py" in workflow_text
    assert 'printf \'%s\\n\' "${GITHUB_REF_NAME#v}" > version.txt' in workflow_text
    assert "uv run pyinstaller" in workflow_text
    assert "npm ci --ignore-scripts" in workflow_text
    assert "Smoke-test packaged backend" in workflow_text
    assert "mapfile" not in workflow_text
    assert 'while IFS= read -r match; do' in workflow_text
    assert "http://127.0.0.1:18765/health" in workflow_text
    assert 'health["version"] == sys.argv[2]' in workflow_text
    assert 'health["api_contract"] == "2026-08-17-pins-chat-v1"' in workflow_text
    assert "http://127.0.0.1:18765/api/context/pin" in workflow_text
    assert "http://127.0.0.1:18765/api/context/pins" in workflow_text
    assert "http://127.0.0.1:18765/api/chat" in workflow_text
    assert 'http://127.0.0.1:18765/api/chat/stream/$task_id' in workflow_text
    assert "always() && github.event_name == 'release'" in workflow_text
    assert workflow["jobs"]["checksums"]["needs"] == "build"


def test_release_installers_verify_native_packages_before_installing():
    powershell = (ROOT / "Get-AIGator.ps1").read_text(encoding="utf-8")
    shell = (ROOT / "Get-AIGator.sh").read_text(encoding="utf-8")

    for script in (powershell, shell):
        assert "releases?per_page=20" in script
        assert "SHA256SUMS.txt" in script
        assert "Checksum verified" in script
        assert "WakeGator" not in script
    assert "Get-FileHash" in powershell
    assert "Start-Process" in powershell
    assert "sha256sum" in shell
    assert 'selected[0].get("digest", "")' in shell
    assert 'EXPECTED_HASH="$ASSET_DIGEST"' in shell
    assert "AI Gator.app" in shell
    assert "AppImage" in shell


def test_packaged_shell_uses_bundled_backend_sidecar():
    main = (ROOT / "shell" / "main.js").read_text(encoding="utf-8")

    assert "process.resourcesPath" in main
    assert "aigator-backend.exe" in main
    spec = (ROOT / "packaging" / "aigator-backend.spec").read_text(encoding="utf-8")

    assert "app.isPackaged ? 8000 : 8002" in main
    assert "`http://127.0.0.1:${GATOR_PORT}`" in main
    assert "http://localhost:${GATOR_PORT}" not in main
    assert "http.request(GATOR_URL + '/api/context/pin'" in main
    assert "backendEnv.TMPDIR = runtimeDir" in main
    assert "windowsHide: true" in main
    assert "pyProc.kill()" in main
    assert "EXPECTED_API_CONTRACT" in main
    assert "health.api_contract !== EXPECTED_API_CONTRACT" in main
    assert "health.version !== app.getVersion()" in main
    assert "showStartupError(error)" in main
    health = (ROOT / "web" / "routes" / "health.py").read_text(encoding="utf-8")

    assert 'root / "tray" / "aigator_icon.png"' in spec
    assert 'Path(getattr(sys, "_MEIPASS"))' in health
    assert '"api_contract": API_CONTRACT' in health
    assert "console=False" in spec


def test_toolbar_callbacks_tolerate_destroyed_webcontents():
    """Toolbar polling must not crash Electron during view teardown."""
    main = (ROOT / "shell" / "main.js").read_text(encoding="utf-8")

    assert "function _liveToolbarWebContents()" in main
    assert "const wc = toolbarView && toolbarView.webContents;" in main
    assert "return wc && !wc.isDestroyed() ? wc : null;" in main
    assert "let _toolbarNavPoll = setInterval" in main
    assert "clearInterval(_toolbarNavPoll);" in main


def test_slack_pane_show_has_no_bespoke_handler():
    """Regression test: slack-pane:show used to duplicate external-pane:show's
    "reload home if already active" logic and drift out of sync with it,
    which is why re-clicking Slack in the rail after navigating its pane
    away (e.g. via the toolbar address bar) used to silently do nothing.
    Slack must go through the generic external-pane:show handler instead.
    """
    main = (ROOT / "shell" / "main.js").read_text(encoding="utf-8")
    preload = (ROOT / "shell" / "preload.js").read_text(encoding="utf-8")

    assert "ipcMain.handle('slack-pane:show'" not in main
    assert "ipcRenderer.invoke('external-pane:show', 'slack')" in preload
    assert "appName === 'slack'" in main
    assert "getLastSlackUrl()" in main


def test_toolbar_address_bar_defers_select_past_native_mouseup():
    """Regression test: calling elUrlInput.select() synchronously inside the
    focus handler gets clobbered by the native mouseup that follows a click
    (which collapses the selection to a caret), so the first click into the
    address bar looked selected but Backspace only cleared a caret, not the
    whole URL. The select() call must be deferred past that mouseup.
    """
    toolbar = (ROOT / "shell" / "toolbar.html").read_text(encoding="utf-8")

    assert "setTimeout(() => elUrlInput.select(), 0);" in toolbar


def test_topbar_reserves_a_visible_drag_grip_when_tabs_overflow():
    style = (ROOT / "web" / "static" / "style.css").read_text(encoding="utf-8")

    assert ".topbar-drag-spacer::after" in style
    assert "content: '⠿';" in style
    assert "min-width: 64px;" in style
    assert "body.gator-split .topbar-drag-spacer:not(.ca-topbar-active)" in style
    assert "flex: 0 0 32px;" in style


def test_window_drag_is_manual_not_native_app_region():
    """Regression test: window dragging must not depend on native
    -webkit-app-region hit-testing in the Gator topbar. That's an unreliable
    upstream Electron/Chromium behavior once more than one WebContentsView is
    attached to a window (electron/electron#43320, no upstream fix) —
    scrolling the tab strip was found (via CDP) to corrupt the whole window's
    drag-region hit-test map, even for pixels outside gatorView's own bounds,
    and giving the drag grip its own exclusive, non-overlapping
    WebContentsView still didn't fix it. The fix instead drives dragging
    manually: the renderer forwards screenX/screenY over IPC on
    mousedown/mousemove, and the main process moves the window with
    setBounds() (never setPosition(), which has a DPI-scaling resize bug —
    electron/electron#9477)."""
    main = (ROOT / "shell" / "main.js").read_text(encoding="utf-8")
    preload = (ROOT / "shell" / "preload.js").read_text(encoding="utf-8")
    app_js = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
    style = (ROOT / "web" / "static" / "style.css").read_text(encoding="utf-8")

    assert "ipcMain.on('win:drag-start'" in main
    assert "ipcMain.on('win:drag-move'" in main
    assert "ipcMain.on('win:drag-end'" in main
    assert "win.setBounds({" in main
    assert "win.setPosition(" not in main

    assert "winDragStart: (screenX, screenY) => ipcRenderer.send('win:drag-start'" in preload
    assert "winDragMove: (screenX, screenY) => ipcRenderer.send('win:drag-move'" in preload
    assert "winDragEnd: () => ipcRenderer.send('win:drag-end')" in preload

    assert "function setupManualWindowDrag()" in app_js
    assert "window.gatorShell.winDragStart(e.screenX, e.screenY);" in app_js
    assert "window.gatorShell.winDragMove(pending.x, pending.y);" in app_js
    assert "window.gatorShell.winDragEnd();" in app_js

    topbar_rule_start = style.index(".topbar {")
    topbar_rule_end = style.index("\n}", topbar_rule_start)
    assert "-webkit-app-region: drag;" not in style[topbar_rule_start:topbar_rule_end]
    spacer_rule_start = style.index(".topbar-drag-spacer {")
    spacer_rule_end = style.index("\n}", spacer_rule_start)
    assert "-webkit-app-region: drag;" not in style[spacer_rule_start:spacer_rule_end]


def test_packaged_backend_supports_sandboxed_python_execution():
    entry = (ROOT / "packaging" / "backend_entry.py").read_text(encoding="utf-8")
    runner = (ROOT / "web" / "skills" / "code_runner" / "tools.py").read_text(encoding="utf-8")

    assert 'parser.add_argument("--run-python", nargs=argparse.REMAINDER)' in entry
    assert 'return [sys.executable, "--run-python", str(script_path)]' in runner
    assert '"-c", full_code' not in runner


def test_backend_python_runner_supports_inline_code(monkeypatch, capsys):
    backend_entry = _load_backend_entry()

    monkeypatch.setattr(backend_entry.sys, "argv", ["aigator-backend"])
    backend_entry.run_python(["-c", "import sys; print(sys.argv[1])", "ready"])

    assert capsys.readouterr().out.strip() == "ready"


def test_backend_python_runner_supports_script_arguments(tmp_path, monkeypatch, capsys):
    backend_entry = _load_backend_entry()

    script = tmp_path / "script.py"
    script.write_text("import sys\nprint(sys.argv[1])\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    backend_entry.run_python(["script.py", "ready"])

    assert capsys.readouterr().out.strip() == "ready"
    assert Path.cwd() == tmp_path


def test_backend_python_runner_supports_stdin(monkeypatch, capsys):
    from io import StringIO

    backend_entry = _load_backend_entry()
    monkeypatch.setattr(backend_entry.sys, "stdin", StringIO("print('ready')\n"))
    backend_entry.run_python(["-"])

    assert capsys.readouterr().out.strip() == "ready"


def test_packaged_backend_bundles_beautiful_soup():
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    requirements = (ROOT / "web" / "requirements.txt").read_text(encoding="utf-8")
    spec = (ROOT / "packaging" / "aigator-backend.spec").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "release-desktop.yml").read_text(
        encoding="utf-8"
    )
    shell_skill = (ROOT / "web" / "skills" / "shell_runner" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert '"beautifulsoup4"' in project
    assert "beautifulsoup4" in requirements
    assert '"bs4"' in spec
    assert "from bs4 import BeautifulSoup" in workflow
    assert "use `run_python`" in shell_skill


def test_packaged_backend_bundles_pty_helpers():
    """pywinpty must be collected wholesale, not left to dependency analysis.

    PyInstaller walks imports and linked libraries, so it finds _winpty.pyd and
    the winpty.dll/conpty.dll it links against. But pywinpty also ships two
    helper EXECUTABLES -- winpty-agent.exe and OpenConsole.exe -- that the DLLs
    launch by name from their own directory at runtime. Those have no import and
    no link edge, so the graph walk drops them, the DLLs find no helper beside
    themselves, and PtyProcess.spawn() fails. Every terminal (OpenCode, Crush,
    Codex, bare shell) then opens blank and never paints.

    This shipped broken because the release smoke test exercised the backend's
    HTTP surface but never spawned a PTY -- hence the workflow assertion too.
    """
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    spec = (ROOT / "packaging" / "aigator-backend.spec").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "release-desktop.yml").read_text(
        encoding="utf-8"
    )

    assert '"pywinpty' in project
    # Import name is "winpty"; the distribution is "pywinpty".
    assert 'collect_all("winpty")' in spec
    # Windows-only: the module is absent on macOS/Linux, where _spawn_pty uses
    # the stdlib pty module, so an unguarded collect_all breaks those builds.
    assert 'sys.platform == "win32"' in spec
    # The release build must actually spawn a PTY, not just probe HTTP.
    assert "Smoke-test packaged PTY" in workflow


def test_github_pane_normalizes_urls_and_reports_load_failures():
    main = (ROOT / "shell" / "main.js").read_text(encoding="utf-8")

    assert "GITHUB_URL = normalizeWebUrl(data.github_base_url)" in main
    assert "[github] load failed" in main
    assert "GitHub could not load" in main
    assert "githubView.setVisible(false)" in main


def test_github_pane_refreshes_config_and_falls_back_when_unavailable():
    main = (ROOT / "shell" / "main.js").read_text(encoding="utf-8")
    pane = (ROOT / "web" / "static" / "third-pane.js").read_text(encoding="utf-8")

    preload = (ROOT / "shell" / "preload.js").read_text(encoding="utf-8")
    app = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")

    assert "await ensureGitHubView()" in main
    assert "if (!view) return false" in main
    assert "github-pane:refresh" in main
    assert "refreshGitHub" in preload
    assert "window.gatorShell.refreshGitHub(d.base_url)" in app
    assert "return true" in main
    assert ".showGitHub()" in pane
    assert ".then((shown) =>" in pane
    assert "_githubMode = 'classic'" in pane
    assert "_openThirdPaneImpl('github')" in pane


def test_github_navigation_allows_the_configured_enterprise_host():
    main = (ROOT / "shell" / "main.js").read_text(encoding="utf-8")

    assert "new URL(GITHUB_URL).hostname" in main
    assert "homeHosts: githubHomeHosts" in main


def test_reload_targets_focused_view_and_resets_gator_to_root():
    main = (ROOT / "shell" / "main.js").read_text(encoding="utf-8")
    menu = (ROOT / "shell" / "menu.js").read_text(encoding="utf-8")

    assert "reloadFocusedContents" in menu
    assert "reloadGator" in menu
    assert "contents.id !== gatorView.webContents.id" in main
    assert "gatorView.webContents.loadURL(GATOR_URL)" in main
