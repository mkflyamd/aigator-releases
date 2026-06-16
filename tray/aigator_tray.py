"""AI Gator system tray launcher.

Run this instead of watchdog.py directly.
Starts the server hidden, shows a tray icon, opens the browser.

Usage:
  python tray/aigator_tray.py          (dev, shows console)
  pythonw tray/aigator_tray.py         (silent, no console)
  double-click AIGator.exe             (packaged installer)
"""
import json as _json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
import webbrowser
from pathlib import Path

def _is_compiled():
    """Detect if running as a compiled executable (PyInstaller or Nuitka)."""
    return getattr(sys, 'frozen', False) or "__compiled__" in globals()

if _is_compiled():
    # Running as compiled AIGator.exe — use embedded Python from install dir
    INSTALL_DIR = Path(sys.executable).parent
    PYTHON = INSTALL_DIR / "python" / "python.exe"
    ROOT = INSTALL_DIR / "app"
else:
    # Running as plain script in dev mode
    INSTALL_DIR = Path(__file__).parent.parent
    PYTHON = sys.executable
    ROOT = Path(__file__).parent.parent

WATCHDOG = ROOT / "web" / "watchdog.py"
LOG_DIR = Path.home() / "AppData" / "Local" / "AIGator" / "logs"
LOG_FILE = LOG_DIR / "aigator.log"
PID_FILE = Path.home() / "AppData" / "Local" / "AIGator" / "watchdog.pid"
TRAY_LOCK = Path.home() / "AppData" / "Local" / "AIGator" / "tray.lock"
DEV_CONSOLE = Path(__file__).parent / "aigator_dev_console.py"
UNINSTALL_SCRIPT = ROOT / "Uninstall-AIGator.ps1"

_watchdog_proc = None

_tray_state: dict = {"running_count": 0, "recent": []}
_summary_win = None


def _poll_task_summary():
    while True:
        try:
            with urllib.request.urlopen(
                "http://localhost:8000/api/tasks/summary", timeout=3
            ) as resp:
                _tray_state.update(_json.loads(resp.read()))
        except Exception:
            pass
        time.sleep(30)


def _log(msg):
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [tray] {msg}\n")
    except Exception:
        pass


# A process is "a gator" if its command line invokes one of our entry points.
# Matching by identity (not just port) evicts prior instances even when they
# grabbed a different port — the twin-tray case that port-only kill misses.
_GATOR_CMDLINE_RE = r"aigator_tray\.py|watchdog\.py|web\.app:app"


def _ancestor_pids():
    """PIDs of this process's ancestors (parent, grandparent, ...).

    The venv launcher (.venv\\Scripts\\pythonw.exe) does not run our code itself —
    it re-execs the base interpreter as a *child*. So the real tray's parent is a
    stub whose command line still contains "aigator_tray.py" and thus matches the
    identity sweep. Killing it with `taskkill /T` would take down this process
    too, so every ancestor must be excluded from the sweep.
    """
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | "
             "ForEach-Object { \"$($_.ProcessId)`t$($_.ParentProcessId)\" }"],
            capture_output=True, text=True,
        )
    except Exception:
        return set()
    parent = {}
    for line in r.stdout.splitlines():
        line = line.strip()
        if "\t" not in line:
            continue
        a, b = line.split("\t", 1)
        try:
            parent[int(a)] = int(b)
        except ValueError:
            continue
    chain, cur, seen = set(), os.getpid(), set()
    while cur in parent and cur not in seen:
        seen.add(cur)
        cur = parent[cur]
        if cur == 0:
            break
        chain.add(cur)
    return chain


def _kill_gator_instances():
    """Identity sweep: kill every other gator process, on any port.

    Uses the command line (via CIM) rather than the listening port, so a stale
    tray/watchdog/uvicorn that bound a non-default port is still evicted. The
    current process and its ancestors (notably the venv launcher stub, whose
    command line also matches our entry points) are left alone.
    """
    protected = {os.getpid()} | _ancestor_pids()
    ps = (
        "Get-CimInstance Win32_Process | "
        f"Where-Object {{ $_.CommandLine -match '{_GATOR_CMDLINE_RE}' }} | "
        "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True,
        )
    except Exception as e:
        _log(f"identity sweep skipped (powershell unavailable): {e}")
        return
    killed = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        pid_str, cmdline = line.split("\t", 1)
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        if pid in protected:
            continue
        subprocess.run(f'taskkill /PID {pid} /F /T', shell=True, capture_output=True)
        killed.append((pid, cmdline.strip()))
    if killed:
        for pid, cmdline in killed:
            _log(f"identity sweep killed PID {pid}: {cmdline}")
        time.sleep(1)


def _kill_ports(*ports):
    """Port backstop: kill whatever still listens on the given ports.

    Catches a stale gator whose command line the identity sweep could not read
    (e.g. elevated / cross-context process). Logs what it kills so a rare
    foreign-app eviction leaves a breadcrumb.
    """
    r = subprocess.run('netstat -ano', capture_output=True, text=True, shell=True)
    pids = set()
    for line in r.stdout.splitlines():
        for port in ports:
            if f':{port}' in line and 'LISTEN' in line:
                pids.add(line.strip().split()[-1])
    for pid in pids:
        name = ""
        try:
            tr = subprocess.run(
                f'tasklist /FI "PID eq {pid}" /FO CSV /NH',
                shell=True, capture_output=True, text=True,
            )
            first = tr.stdout.strip().splitlines()[:1]
            if first:
                name = first[0].split(",")[0].strip('"')
        except Exception:
            pass
        subprocess.run(f'taskkill /PID {pid} /F', shell=True, capture_output=True)
        _log(f"port backstop killed PID {pid} ({name or 'unknown'}) on {ports}")
    if pids:
        time.sleep(1)


def _evict_old_watchdog():
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _kill_gator_instances()
    _kill_ports(8000, 8001)


def _start_watchdog():
    global _watchdog_proc
    _evict_old_watchdog()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    with open(LOG_FILE, "a") as log_f:
        _watchdog_proc = subprocess.Popen(
            [PYTHON, str(WATCHDOG)],
            cwd=str(ROOT),
            creationflags=flags,
            stdout=log_f,
            stderr=subprocess.STDOUT,
        )
    PID_FILE.write_text(str(_watchdog_proc.pid))


_LOADING_HTML = """\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>AI Gator \u2014 Starting...</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #0a0f1a; color: #e2e8f0;
      font-family: system-ui, -apple-system, sans-serif;
      display: flex; flex-direction: column;
      align-items: center; justify-content: center;
      height: 100vh; gap: 28px;
    }
    .logo { font-size: 96px; animation: chomp 0.8s ease-in-out infinite alternate; }
    @keyframes chomp {
      from { transform: scaleY(1) rotate(-5deg); }
      to   { transform: scaleY(0.8) rotate(5deg); }
    }
    .title { font-size: 28px; font-weight: 700; color: #4ade80; }
    .msg { font-size: 15px; color: #94a3b8; transition: opacity 0.4s; }
    .bar { width: 320px; height: 4px; background: #1e293b; border-radius: 2px; overflow: hidden; }
    .fill {
      height: 100%;
      background: linear-gradient(90deg, #4ade80, #22d3ee);
      border-radius: 2px;
      animation: pulse-bar 2s ease-in-out infinite;
    }
    @keyframes pulse-bar {
      0%   { width: 20%; margin-left: 0%; }
      50%  { width: 60%; margin-left: 20%; }
      100% { width: 20%; margin-left: 60%; }
    }
  </style>
</head>
<body>
  <div class="logo">\U0001f40a</div>
  <div class="title">AI Gator</div>
  <div class="msg" id="msg">Waking up the gator...</div>
  <div class="bar"><div class="fill"></div></div>
  <script>
    const msgs = [
      "Waking up the gator...",
      "Sharpening those teeth...",
      "Loading your workspace tools...",
      "Connecting to Microsoft 365...",
      "Almost ready to chomp..."
    ];
    let i = 0;
    const el = document.getElementById('msg');
    setInterval(() => {
      el.style.opacity = '0';
      setTimeout(() => { i = (i + 1) % msgs.length; el.textContent = msgs[i]; el.style.opacity = '1'; }, 400);
    }, 2200);
    function poll() {
      fetch('http://localhost:8001/ready')
        .then(r => r.json())
        .then(d => { if (d.ready) window.location.replace('http://localhost:8000'); })
        .catch(() => {});
    }
    setInterval(poll, 500);
  </script>
</body>
</html>"""

_loading_tmp = None


def _open_loading():
    import tempfile
    global _loading_tmp
    # Write loading page to a temp file and open it immediately — no server needed
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False,
        encoding="utf-8", prefix="aigator_loading_"
    )
    tmp.write(_LOADING_HTML)
    tmp.close()
    _loading_tmp = tmp.name
    webbrowser.open("file:///" + tmp.name.replace("\\", "/"))


def _open_browser(icon=None, item=None):
    webbrowser.open("http://localhost:8000")


def _show_summary_panel(icon=None, item=None):
    global _summary_win
    import tkinter as tk

    if _summary_win is not None:
        try:
            _summary_win.lift()
            _summary_win.focus_force()
            return
        except tk.TclError:
            _summary_win = None  # destroyed already, fall through

    win = tk.Tk()
    _summary_win = win
    win.title("AI Gator")
    win.geometry("290x210")
    win.resizable(False, False)
    win.attributes("-topmost", True)

    def _on_close():
        global _summary_win
        _summary_win = None
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", _on_close)

    tk.Label(win, text="AI Gator", font=("Segoe UI", 13, "bold"), anchor="w").pack(fill="x", padx=12, pady=(10, 4))
    tk.Frame(win, height=1, bg="#334155").pack(fill="x", padx=12)

    count = _tray_state.get("running_count", 0)
    if count:
        tk.Label(win, text=f"\u26A1 {count} task(s) running",
                 font=("Segoe UI", 10), anchor="w", fg="#4ade80").pack(fill="x", padx=12, pady=4)

    for t in _tray_state.get("recent", [])[:4]:
        ch = "\u2705" if t.get("status") == "done" else "\u26A0\uFE0F"
        preview = (t.get("result_preview") or "")[:45]
        tk.Label(win, text=f"{ch} {preview}",
                 font=("Segoe UI", 9), anchor="w", fg="#94a3b8").pack(fill="x", padx=12, pady=1)

    tk.Frame(win, height=1, bg="#334155").pack(fill="x", padx=12, pady=4)
    tk.Button(win, text="Open AI Gator",
              command=lambda: (_open_browser(), _on_close()),
              font=("Segoe UI", 10), relief="flat", bg="#166534", fg="white",
              padx=8, pady=4).pack(fill="x", padx=12, pady=4)

    win.mainloop()
    _summary_win = None


def _restart_server(icon=None, item=None):
    try:
        urllib.request.urlopen("http://localhost:8001/restart", data=b"", timeout=3)
    except Exception:
        pass


def _open_dev_console(icon=None, item=None):
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    subprocess.Popen([PYTHON, str(DEV_CONSOLE)], creationflags=flags)


def _uninstall(icon=None, item=None):
    # Launch the detached uninstaller. It shows its own Yes/No confirm dialog, so
    # cancelling there leaves the running gator untouched. Only on confirm does it
    # stop gator (its identity sweep kills this tray) and delete the install dir.
    # We do NOT icon.stop() here — that would kill the gator even if the user cancels.
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-WindowStyle", "Hidden", "-File", str(UNINSTALL_SCRIPT)],
            creationflags=flags,
        )
    except Exception as e:
        _log(f"uninstall launch failed: {e}")


def _quit(icon, item):
    # Tell watchdog to stop uvicorn and shut itself down before we exit
    try:
        urllib.request.urlopen("http://localhost:8001/quit", data=b"", timeout=3)
    except Exception:
        pass
    # Kill any lingering processes on both ports
    _kill_ports(8000, 8001)
    if _watchdog_proc:
        try:
            _watchdog_proc.terminate()
        except Exception:
            pass
    PID_FILE.unlink(missing_ok=True)
    TRAY_LOCK.unlink(missing_ok=True)
    if _loading_tmp:
        try:
            Path(_loading_tmp).unlink(missing_ok=True)
        except Exception:
            pass
    icon.stop()


def _make_icon_image():
    import io
    from PIL import Image

    # When compiled, __file__ may not reflect the install location — use INSTALL_DIR instead
    if _is_compiled():
        icon_path = INSTALL_DIR / "tray" / "aigator_icon.png"
    else:
        icon_path = Path(__file__).parent / "aigator_icon.png"
    if icon_path.exists():
        return Image.open(icon_path).resize((64, 64)).convert("RGBA")

    svg_path = ROOT / "web" / "static" / "favicon.svg"
    try:
        import cairosvg
        png_bytes = cairosvg.svg2png(url=str(svg_path), output_width=64, output_height=64)
        return Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    except Exception:
        pass

    # Fallback: simple drawn icon
    from PIL import ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, 63, 63], radius=12, fill="#0c1a0f")
    d.ellipse([4, 20, 60, 56], fill="#166534")
    d.ellipse([4, 22, 20, 38], fill="#eab308")
    d.ellipse([44, 22, 60, 38], fill="#eab308")
    return img


def _acquire_lock():
    TRAY_LOCK.parent.mkdir(parents=True, exist_ok=True)
    if TRAY_LOCK.exists():
        try:
            existing_pid = int(TRAY_LOCK.read_text().strip())
            import ctypes
            import ctypes.wintypes
            PROCESS_QUERY_LIMITED = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, existing_pid)
            if handle:
                # Verify the process is actually AIGator, not a recycled PID
                buf = ctypes.create_unicode_buffer(1024)
                size = ctypes.wintypes.DWORD(1024)
                ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
                ctypes.windll.kernel32.CloseHandle(handle)
                if ok and "AIGator" in buf.value:
                    return False  # a real AIGator instance is running
        except Exception:
            pass
    TRAY_LOCK.write_text(str(os.getpid()))
    return True


def main():
    try:
        import pystray
        from PIL import Image
    except ImportError:
        print("Missing deps. Run: pip install pystray Pillow")
        sys.exit(1)

    if not _acquire_lock():
        webbrowser.open("http://localhost:8000")
        sys.exit(0)

    # Start backend and open browser first — before any slow icon loading
    _start_watchdog()
    threading.Thread(target=_open_loading, daemon=True).start()

    img = _make_icon_image()

    items = [
        pystray.MenuItem("AI Gator", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "Task Summary",
            lambda icon, item: threading.Thread(target=_show_summary_panel, args=(icon, item), daemon=True).start(),
            default=True,
        ),
        pystray.MenuItem("Open AI Gator", _open_browser),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Restart Server", _restart_server),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Developer Console", _open_dev_console),
        pystray.Menu.SEPARATOR,
    ]
    # Only the source/pip track ships Uninstall-AIGator.ps1; the .exe track has its
    # own Add/Remove Programs entry, so hide this item when the script is absent.
    if UNINSTALL_SCRIPT.exists():
        items.append(pystray.MenuItem("Uninstall AI Gator…", _uninstall))
        items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem("Quit AI Gator", _quit))

    menu = pystray.Menu(*items)

    icon = pystray.Icon("AI Gator", img, "AI Gator", menu)
    threading.Thread(target=_poll_task_summary, daemon=True).start()
    icon.run()


if __name__ == "__main__":
    main()
