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
    assert workflow[True]["release"]["types"] == ["published"]
    assert "astral-sh/setup-uv@" in workflow_text
    assert "uv sync --locked" in workflow_text
    assert "uv run python packaging/sync_version.py" in workflow_text
    assert 'printf \'%s\\n\' "${GITHUB_REF_NAME#v}" > version.txt' in workflow_text
    assert "uv run pyinstaller" in workflow_text
    assert "npm ci --ignore-scripts" in workflow_text
    assert "Smoke-test packaged backend" in workflow_text
    assert "http://127.0.0.1:18765/health" in workflow_text
    assert 'health["version"] == sys.argv[2]' in workflow_text
    assert 'health["api_contract"] == "2026-08-17-pins-chat-v1"' in workflow_text
    assert "http://127.0.0.1:18765/api/context/pin" in workflow_text
    assert "http://127.0.0.1:18765/api/context/pins" in workflow_text
    assert "http://127.0.0.1:18765/api/chat" in workflow_text
    assert 'http://127.0.0.1:18765/api/chat/stream/$task_id' in workflow_text


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

    assert "webContents.getFocusedWebContents()" in menu
    assert "if (reloadGator(contents, hard)) return" in menu
    assert "contents.id !== gatorView.webContents.id" in main
    assert "gatorView.webContents.loadURL(GATOR_URL)" in main
