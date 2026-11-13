import json
import os
import shutil
import sys
from pathlib import Path

import pytest

import sandbox
from sandbox import SandboxRequest, build_env
from sandbox.forward import ForwardedProcess
from tests.code_sandbox.relay_support import free_port, http_get, write_server

pytestmark = [
    pytest.mark.real_sandbox,
    pytest.mark.skipif(sys.platform != "win32", reason="AppContainer is Windows only"),
]


def test_dev_server_in_the_sandbox_is_reachable_through_the_forwarder(windows_container, tmp_path):
    import psutil

    src = Path(sandbox.__file__).resolve().parent
    relay_dir = tmp_path / "relay"
    relay_dir.mkdir()
    for name in ("relay.py", "wire.py"):
        shutil.copy2(src / name, relay_dir / name)
    run = tmp_path / "run"
    run.mkdir()
    server = write_server(run)
    port = free_port()
    env = build_env(os.environ, run, None)
    env["AIGATOR_RELAY_COMMAND"] = json.dumps([sys.executable, "-u", str(server), "serve", str(port)])
    req = SandboxRequest(
        argv=[sys.executable, "-X", "utf8", str(relay_dir / "relay.py")],
        cwd=run,
        env=env,
        runtime_paths=sorted({Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve()}, key=str),
        read_paths=[relay_dir],
        write_paths=[],
        network=False,
        timeout=0,
    )
    sp = windows_container.start(req)
    fp = ForwardedProcess(sp, str(tmp_path / "log.txt")).start()
    children = []
    try:
        assert fp.wait_ready(30), (tmp_path / "log.txt").read_text(errors="replace")
        children = psutil.Process(sp.pid).children(recursive=True)
        assert children
        head, body = http_get(fp.listen_port)
        assert head.startswith(b"HTTP/1.0 200")
        assert body == b"hello from dev server"
    finally:
        fp.terminate()
    _gone, alive = psutil.wait_procs(children, timeout=10)
    assert alive == []
    assert isinstance(sp.wait(60), int)
    assert json.loads(windows_container.ledger_path().read_text())["per_run"] == []
