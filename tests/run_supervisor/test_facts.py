import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "web"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

import fakes
from runs import facts


def test_urls_are_found_once_in_order_and_trailing_punctuation_is_dropped():
    text = "Viewer at http://127.0.0.1:4173/p/demo/. Docs: https://example.com/a, again http://127.0.0.1:4173/p/demo/"
    assert facts.urls_in(text) == ["http://127.0.0.1:4173/p/demo/", "https://example.com/a"]


def test_the_url_list_is_capped():
    text = " ".join(f"http://127.0.0.1:{4000 + i}/" for i in range(40))
    assert len(facts.urls_in(text)) == 10


def test_only_loopback_urls_have_a_local_port():
    assert facts.local_port_of("http://127.0.0.1:4173/x") == 4173
    assert facts.local_port_of("http://localhost/") == 80
    assert facts.local_port_of("https://example.com:4173/") is None


def test_the_watcher_sees_the_port_a_process_listens_on(tmp_path):
    script = tmp_path / "listen.py"
    script.write_text(
        "import socket, time\n"
        "s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen()\n"
        "print(s.getsockname()[1], flush=True)\n"
        "time.sleep(30)\n"
    )
    proc = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True)
    try:
        port = int(proc.stdout.readline())
        watcher = facts.TreeWatcher(proc.pid, interval=0.05).start()
        assert fakes.wait_for(lambda: port in watcher._ports)
        assert port in watcher.finish()["ports_opened"]
    finally:
        proc.kill()
        proc.wait()


def test_a_child_that_outlives_its_parent_is_reported_as_left_behind(tmp_path):
    script = tmp_path / "parent.py"
    pid_file = tmp_path / "child.pid"
    script.write_text(
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\n"
        "time.sleep(30)\n"
    )
    proc = subprocess.Popen([sys.executable, str(script)])
    try:
        watcher = facts.TreeWatcher(proc.pid, interval=0.05).start()
        child = fakes.child_pid(tmp_path, "child")
        assert fakes.wait_for(lambda: child in watcher.pids)
        proc.kill()
        proc.wait()
        left = watcher.finish()["children_left"]
        assert [c["pid"] for c in left] == [child]
    finally:
        import psutil

        for p in psutil.Process().children(recursive=True):
            p.kill()


def test_a_port_held_by_a_process_outside_the_run_is_reported_as_outside_the_tree(tmp_path):
    script = tmp_path / "other.py"
    script.write_text(
        "import socket, time\n"
        "s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen()\n"
        "print(s.getsockname()[1], flush=True)\n"
        "time.sleep(30)\n"
    )
    proc = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True)
    try:
        port = int(proc.stdout.readline())
        found = facts.collect(f"Viewer at http://127.0.0.1:{port}/", None)
        assert found["urls_seen"] == [f"http://127.0.0.1:{port}/"]
        assert found["owner_pid"] == proc.pid
        assert found["owner_in_run_tree"] is False
    finally:
        proc.kill()
        proc.wait()
