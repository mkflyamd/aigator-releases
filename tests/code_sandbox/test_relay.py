import struct
import sys

import pytest

from sandbox import wire
from tests.code_sandbox.relay_support import RelayClient, free_port, write_server


@pytest.fixture
def client():
    made = []

    def make(argv):
        c = RelayClient(argv)
        made.append(c)
        return c

    yield make
    for c in made:
        c.close()


def _log(frames):
    return b"".join(p for k, _c, p in frames if k == wire.LOG)


def test_log_and_exit(client):
    c = client([sys.executable, "-c", "print('hi'); import sys; sys.exit(4)"])
    frames = c.collect(lambda seen: any(k == wire.EXIT for k, _c, _p in seen))
    assert b"hi" in _log(frames)
    assert wire.parse_exit(frames[-1][2]) == 4


def test_open_data_close_round_trip(client, tmp_path):
    port = free_port()
    c = client([sys.executable, "-u", str(write_server(tmp_path)), "serve", str(port)])
    c.collect(lambda seen: b"Local:" in _log(seen))
    c.send(wire.OPEN, 1, wire.open_payload(port))
    c.send(wire.DATA, 1, b"GET / HTTP/1.0\r\nHost: localhost\r\n\r\n")
    frames = c.collect(lambda seen: any(k == wire.CLOSE and cid == 1 for k, cid, _p in seen))
    body = b"".join(p for k, cid, p in frames if k == wire.DATA and cid == 1)
    assert b"hello from dev server" in body


def test_stdin_eof_ends_relay(client):
    c = client([sys.executable, "-c", "import time; time.sleep(60)"])
    c.proc.stdin.close()
    assert c.proc.wait(10) == 0


def test_malformed_frame_ends_relay_with_2(client):
    c = client([sys.executable, "-c", "import time; time.sleep(60)"])
    c.proc.stdin.write(struct.pack("!BII", 99, 0, 0))
    c.proc.stdin.flush()
    assert c.proc.wait(10) == 2


def test_spawn_failure_reports_exit_127(client):
    c = client(["definitely-not-a-real-program-xyz"])
    frames = c.collect(lambda seen: any(k == wire.EXIT for k, _c, _p in seen))
    assert b"Could not start" in _log(frames)
    assert wire.parse_exit(frames[-1][2]) == 127


def test_open_to_closed_port_sends_close(client):
    c = client([sys.executable, "-c", "import time; time.sleep(60)"])
    c.send(wire.OPEN, 5, wire.open_payload(free_port()))
    frames = c.collect(lambda seen: any(k == wire.CLOSE and cid == 5 for k, cid, _p in seen))
    assert (wire.CLOSE, 5, b"") in frames
