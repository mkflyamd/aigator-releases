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

for package in ("browser_use", "litellm", "playwright_stealth"):
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
hiddenimports += ["httpx_sse", "sse_starlette"]
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
    a.binaries,
    a.datas,
    [],
    name="aigator-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
