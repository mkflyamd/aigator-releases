"""Runs inside the sandbox. Starts the user's command and carries loopback
connections to it over stdin/stdout. Stdlib only.

AIGATOR_RELAY_COMMAND (JSON argv list) is the command. Frames: see wire.py.
"""
import json
import os
import queue
import socket
import subprocess
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wire  # noqa: E402

_out_lock = threading.Lock()
_conns = {}
_conns_lock = threading.Lock()


def send(kind, conn, payload=b""):
    try:
        data = wire.encode(kind, conn, payload)
        with _out_lock:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
    except (OSError, ValueError):
        os._exit(1)


class _Conn:
    def __init__(self, conn_id, port):
        self.id = conn_id
        self.port = port
        self.queue = queue.Queue()
        self.sock = None
        self.done = False
        self.lock = threading.Lock()

    def finish(self, notify):
        with self.lock:
            if self.done:
                return
            self.done = True
            sock = self.sock
        with _conns_lock:
            _conns.pop(self.id, None)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        self.queue.put(None)
        if notify:
            send(wire.CLOSE, self.id)

    def run(self):
        try:
            sock = socket.create_connection(("localhost", self.port), timeout=10)
        except OSError:
            self.finish(True)
            return
        sock.settimeout(None)
        with self.lock:
            if self.done:
                sock.close()
                return
            self.sock = sock
        threading.Thread(target=self._read, daemon=True).start()
        while True:
            item = self.queue.get()
            if item is None:
                self.finish(False)
                return
            try:
                sock.sendall(item)
            except OSError:
                self.finish(True)
                return

    def _read(self):
        sock = self.sock
        while True:
            try:
                data = sock.recv(wire.MAX_PAYLOAD)
            except OSError:
                break
            if not data:
                break
            send(wire.DATA, self.id, data)
        self.finish(True)


def _kill(child):
    try:
        child.kill()
    except OSError:
        pass


def _dispatch(kind, conn_id, payload):
    if kind == wire.OPEN:
        conn = _Conn(conn_id, wire.parse_open(payload))
        with _conns_lock:
            _conns[conn_id] = conn
        threading.Thread(target=conn.run, daemon=True).start()
        return
    with _conns_lock:
        conn = _conns.get(conn_id)
    if conn is None:
        return
    if kind == wire.DATA:
        conn.queue.put(payload)
    elif kind == wire.CLOSE:
        conn.queue.put(None)


def main():
    argv = json.loads(os.environ.pop("AIGATOR_RELAY_COMMAND"))
    try:
        child = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
    except OSError as exc:
        send(wire.LOG, 0, f"Could not start the command: {exc}\n".encode("utf-8", "replace"))
        send(wire.EXIT, 0, wire.exit_payload(127))
        return

    def pump():
        try:
            while True:
                data = child.stdout.read1(4096)
                if not data:
                    break
                send(wire.LOG, 0, data)
        except (OSError, ValueError):
            pass

    pump_thread = threading.Thread(target=pump, daemon=True)
    pump_thread.start()

    def wait():
        code = child.wait()
        pump_thread.join(2)
        send(wire.EXIT, 0, wire.exit_payload(code))
        os._exit(0)

    threading.Thread(target=wait, daemon=True).start()

    stdin = sys.stdin.buffer
    decoder = wire.Decoder()
    while True:
        try:
            data = wire.read_some(stdin, 65536)
        except (OSError, ValueError):
            data = b""
        if not data:
            _kill(child)
            os._exit(0)
        try:
            for kind, conn_id, payload in decoder.feed(data):
                _dispatch(kind, conn_id, payload)
        except wire.WireError:
            _kill(child)
            os._exit(2)


if __name__ == "__main__":
    main()
