import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH).parent
web = root / "web"

datas = [
    (str(web / "static"), "static"),
    (str(web / "static"), "web/static"),
    (str(web / "skills"), "skills"),
    (str(web / "skills"), "web/skills"),
    (str(root / "tray" / "aigator_icon.png"), "tray"),
    (str(root / "version.txt"), "."),
]
hiddenimports = []
binaries = []

for package in ("browser_use", "litellm", "playwright_stealth", "bs4"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

mcp_datas, mcp_binaries, mcp_hiddenimports = collect_all(
    "mcp", filter_submodules=lambda name: not name.startswith("mcp.cli")
)
datas += mcp_datas
binaries += mcp_binaries
hiddenimports += mcp_hiddenimports
hiddenimports += ["httpx_sse", "sse_starlette", "secure_store"]
# web/sandbox is imported with bare names (web/ is on pathex); launchers are
# imported lazily per OS, so list them all explicitly.
hiddenimports += [
    "sandbox", "sandbox.policy", "sandbox.paths", "sandbox.approvals",
    "sandbox.launcher_windows", "sandbox.launcher_macos", "sandbox.launcher_linux",
]
if sys.platform != "win32":
    from PyInstaller.utils.hooks import copy_metadata

    datas += copy_metadata("keyring")
    hiddenimports += collect_submodules("keyring.backends")
    hiddenimports += ["cryptography.hazmat.primitives.ciphers.aead"]
    if sys.platform.startswith("linux"):
        hiddenimports += ["secretstorage"] + collect_submodules("jeepney")
hiddenimports += collect_submodules("web")
hiddenimports += collect_submodules("uvicorn")

a = Analysis(
    [str(root / "packaging" / "backend_entry.py")],
    pathex=[str(root), str(web)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="aigator-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
# Onedir, not onefile: a onefile sidecar re-extracts the whole bundle into
# %TEMP% on every `--run-python` child (~37 s before Python starts on
# Windows, 2026-10-05). Built with `--distpath dist`, COLLECT writes
# dist/backend/aigator-backend[.exe] plus dist/backend/_internal/, so the
# path used by shell/main.js and the release workflow does not change.
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="backend",
)
