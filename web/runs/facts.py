"""Facts observed about a run: URLs it printed, ports its process tree listened on, processes it left behind.

Nothing here decides whether a run "worked". These are observations the model and the user can read.
"""
from __future__ import annotations

import os
import re
import threading
import time

_URL = re.compile(r"https?://[^\s'\"<>)\]]+", re.IGNORECASE)
_MAX_URLS = 10
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")
_SAMPLE_SECONDS = 0.5
# A shell that starts a daemon and exits can be gone in well under a second, so the first seconds are sampled fast.
_EARLY_SAMPLE_SECONDS = 0.05
_EARLY_WINDOW_SECONDS = 2.0


def urls_in(text: str) -> list[str]:
    """Distinct http(s) URLs in the text, in order of first appearance, capped."""
    seen: list[str] = []
    for match in _URL.finditer(text or ""):
        url = match.group(0).rstrip(".,;:")
        if url not in seen:
            seen.append(url)
        if len(seen) >= _MAX_URLS:
            break
    return seen


def local_port_of(url: str) -> int | None:
    """The TCP port of a loopback URL, or None for any other host."""
    match = re.match(r"https?://(127\.0\.0\.1|localhost|\[::1\])(?::(\d+))?", url, re.IGNORECASE)
    if not match:
        return None
    if match.group(2):
        return int(match.group(2))
    return 443 if url.lower().startswith("https") else 80


def _connections(proc):
    getter = getattr(proc, "net_connections", None) or proc.connections
    return getter(kind="tcp")


def _listening_ports(proc) -> set[int]:
    import psutil

    try:
        return {c.laddr.port for c in _connections(proc) if c.status == psutil.CONN_LISTEN and c.laddr}
    except (psutil.Error, OSError):
        return set()


class TreeWatcher:
    """Samples a run's process tree while it runs: the TCP ports it listens on and the processes it starts.

    A shell that exits leaves its children running with no parent to walk from, so the pids seen
    along the way are what let the run report children left behind."""

    def __init__(self, pid: int, interval: float = _SAMPLE_SECONDS):
        self._pid = pid
        self._interval = interval
        self._ports: set[int] = set()
        self._seen: dict[int, tuple[float, str]] = {}
        self._root_created = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name=f"tree-watch-{pid}", daemon=True)

    def start(self) -> "TreeWatcher":
        self._sample()
        self._thread.start()
        return self

    def _loop(self) -> None:
        began = time.monotonic()
        while True:
            early = time.monotonic() - began < _EARLY_WINDOW_SECONDS
            if self._stop.wait(min(self._interval, _EARLY_SAMPLE_SECONDS) if early else self._interval):
                return
            self._sample()

    def _sample(self) -> None:
        import psutil

        try:
            root = psutil.Process(self._pid)
            self._root_created = self._root_created or root.create_time()
            members = [root, *root.children(recursive=True)]
        except psutil.Error:
            members = []
        known = {proc.pid for proc in members}
        members += [proc for proc in self._group_members() if proc.pid not in known]
        walked = set()
        for proc in members:
            try:
                self._seen[proc.pid] = (proc.create_time(), proc.name())
            except psutil.Error:
                continue
            walked.add(proc.pid)
            self._ports |= _listening_ports(proc)
        # Once the shell has exited its children can no longer be walked to, but they are still known by pid.
        for pid, (created, _) in list(self._seen.items()):
            if pid in walked:
                continue
            try:
                proc = psutil.Process(pid)
                if abs(proc.create_time() - created) < 1.0:
                    self._ports |= _listening_ports(proc)
            except psutil.Error:
                continue

    def _group_members(self) -> list:
        """POSIX: a child whose parent has exited is handed to init and can no longer be walked to, but it stays
        in the run's process group, which the run was started as the leader of."""
        if os.name == "nt":
            return []
        import psutil

        found = []
        for proc in psutil.process_iter():
            try:
                if os.getpgid(proc.pid) == self._pid:
                    found.append(proc)
            except (OSError, psutil.Error):
                continue
        return found

    @property
    def pids(self) -> set[int]:
        return set(self._seen)

    def finish(self) -> dict:
        """Stop sampling and report: ports the tree listened on, and processes still alive that it started."""
        import psutil

        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(2)
        self._sample()
        left = []
        for pid, (created, name) in self._seen.items():
            if pid == self._pid:
                continue
            try:
                proc = psutil.Process(pid)
                if abs(proc.create_time() - created) < 1.0 and proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                    left.append({"pid": pid, "name": name})
            except psutil.Error:
                continue
        return {"ports_opened": sorted(self._ports), "children_left": left}


def _listening_pid(port: int) -> int | None:
    import psutil

    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port == port and conn.pid:
                return conn.pid
        return None
    except psutil.AccessDenied:
        pass  # macOS lists every socket only to root; the processes this user owns can still be asked one by one
    except (psutil.Error, OSError):
        return None
    for proc in psutil.process_iter():
        if port in _listening_ports(proc):
            return proc.pid
    return None


def port_owner(port: int, tree_pids: set[int]) -> dict | None:
    """Which process listens on a loopback port, and whether it is in the run's own process tree."""
    pid = _listening_pid(port)
    if not pid:
        return None
    return {"owner_pid": pid, "owner_in_run_tree": pid in tree_pids}


def collect(text: str, watcher: "TreeWatcher | None") -> dict:
    """The facts for one finished run."""
    facts: dict = {"urls_seen": urls_in(text)}
    pids: set[int] = set()
    if watcher is not None:
        facts.update(watcher.finish())
        pids = watcher.pids
    for url in facts["urls_seen"]:
        port = local_port_of(url)
        owner = port_owner(port, pids) if port else None
        if owner:
            facts.update(owner)
            break
    return facts
