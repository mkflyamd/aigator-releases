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

# pywinpty (import name: "winpty") backs every PTY on Windows -- the terminal
# pane, and therefore OpenCode/Crush/Codex/bare-shell alike.
#
# It MUST be collected wholesale rather than left to dependency analysis.
# PyInstaller traces imports and linked libraries, so it finds _winpty.pyd and
# the winpty.dll/conpty.dll it links against -- but pywinpty also ships two
# helper EXECUTABLES, winpty-agent.exe and OpenConsole.exe, which the DLLs
# launch by name at runtime from their own directory. Those have no import and
# no link reference, so they are invisible to the graph walk and get dropped.
# The DLLs then find no helper next to themselves and PtyProcess.spawn() fails,
# which surfaces as a terminal that opens blank and never paints.
#
# Windows-only: the module does not exist on macOS/Linux, where _spawn_pty uses
# the stdlib pty module instead, so collect_all would raise during those builds.
if sys.platform == "win32":
    winpty_datas, winpty_binaries, winpty_hiddenimports = collect_all("winpty")
    datas += winpty_datas
    binaries += winpty_binaries
    hiddenimports += winpty_hiddenimports

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
