"""Backend side of dev-server port forwarding.

ForwardedProcess wraps a started sandbox process that is running relay.py.
Pipe reads and writes run on threads; the browser-facing listener is an asyncio
server on its own loop thread, so the app's event loop is never involved.
"""
from __future__ import annotations

import asyncio
import codecs
import logging
import queue
import re
import threading
import time

from . import wire

_log = logging.getLogger("sandbox.forward")

MAX_CONNS = 64
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_URL = re.compile(r"https?://(?:localhost|127\.0\.0\.1|\[::1\]):(\d{1,5})(?!\w)")
_SCAN_TAIL = 8192


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def detect_port(text: str) -> int | None:
    for match in _URL.finditer(strip_ansi(text)):
        port = int(match.group(1))
        if 1 <= port <= 65535:
            return port
    return None


class ForwardedProcess:
    def __init__(self, proc, log_file: str, on_close=None):
        self._proc = proc
        self.pid = proc.pid
        self._log_path = log_file
        self._on_close = on_close
        self.url: str | None = None
        self.listen_port: int | None = None
        self.exit_code: int | None = None
        self.closed = threading.Event()
        self._ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = threading.Event()
        self._server = None
        self._conns: dict[int, asyncio.StreamWriter] = {}
        self._tasks: set = set()
        self._next_conn = 0
        self._writes: queue.Queue = queue.Queue()
        self._dev_port: int | None = None
        self._shut = False
        self._shut_lock = threading.Lock()
        self._log_handle = None
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._scan = ""

    def start(self) -> "ForwardedProcess":
        self._log_handle = open(self._log_path, "ab")
        threading.Thread(target=self._run_loop, daemon=True).start()
        if not self._loop_ready.wait(5):
            self._log_handle.close()
            raise OSError("The port forwarder did not start.")
        threading.Thread(target=self._read_pipe, daemon=True).start()
        threading.Thread(target=self._write_pipe, daemon=True).start()
        return self

    def poll(self) -> int | None:
        if self.exit_code is not None:
            return self.exit_code
        return self._proc.poll()

    def wait_ready(self, timeout: float) -> bool:
        self._ready.wait(timeout)
        return self.url is not None

    def terminate(self) -> None:
        self._writes.put(None)
        self._shutdown()
        self.closed.wait(5)

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        loop.call_soon(self._loop_ready.set)
        try:
            loop.run_forever()
        finally:
            loop.close()

    def _read_pipe(self) -> None:
        decoder = wire.Decoder()
        try:
            while True:
                data = wire.read_some(self._proc.stdout, 65536)
                if not data:
                    break
                for kind, conn, payload in decoder.feed(data):
                    if kind == wire.LOG:
                        self._on_log(payload)
                    elif kind == wire.DATA:
                        self._post(self._deliver, conn, payload)
                    elif kind == wire.CLOSE:
                        self._post(self._drop, conn)
                    elif kind == wire.EXIT:
                        self.exit_code = wire.parse_exit(payload)
                        self._shutdown()
                        return
        except (OSError, ValueError) as exc:
            _log.warning("forward: relay stream ended (%s)", type(exc).__name__)
        try:
            self._proc.terminate()
        except OSError:
            pass
        self._shutdown()

    def _write_pipe(self) -> None:
        stream = self._proc.stdin
        try:
            while True:
                frame = self._writes.get()
                if frame is None:
                    break
                stream.write(frame)
                stream.flush()
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except (OSError, ValueError):
                pass

    def _on_log(self, payload: bytes) -> None:
        try:
            self._log_handle.write(payload)
            self._log_handle.flush()
        except (OSError, ValueError) as exc:
            _log.warning("forward: log write failed (%s)", type(exc).__name__)
        if self._dev_port is not None:
            return
        self._scan += self._decoder.decode(payload)
        cut = self._scan.rfind("\n") + 1
        if not cut:
            self._scan = self._scan[-_SCAN_TAIL:]
            return
        port = detect_port(self._scan[:cut])
        self._scan = self._scan[cut:][-_SCAN_TAIL:]
        if port is None:
            return
        self._dev_port = port
        try:
            asyncio.run_coroutine_threadsafe(self._listen(port), self._loop)
        except RuntimeError:
            self._ready.set()

    def _post(self, fn, *args) -> None:
        try:
            self._loop.call_soon_threadsafe(fn, *args)
        except RuntimeError:
            pass

    async def _listen(self, port: int) -> None:
        try:
            for candidate in (port, 0):
                try:
                    server = await asyncio.start_server(self._accept, "127.0.0.1", candidate)
                except OSError:
                    continue
                if self._shut:
                    server.close()
                    break
                self._server = server
                self.listen_port = server.sockets[0].getsockname()[1]
                self.url = f"http://127.0.0.1:{self.listen_port}"
                break
        finally:
            self._ready.set()

    async def _accept(self, reader, writer) -> None:
        task = asyncio.current_task()
        self._tasks.add(task)
        conn = None
        try:
            if self._shut or len(self._conns) >= MAX_CONNS:
                return
            self._next_conn += 1
            conn = self._next_conn
            self._conns[conn] = writer
            self._send(wire.OPEN, conn, wire.open_payload(self._dev_port))
            while True:
                data = await reader.read(wire.MAX_PAYLOAD)
                if not data:
                    break
                self._send(wire.DATA, conn, data)
        except OSError:
            pass
        finally:
            if conn is not None and self._conns.pop(conn, None) is not None:
                self._send(wire.CLOSE, conn)
            writer.close()
            self._tasks.discard(task)

    def _deliver(self, conn: int, payload: bytes) -> None:
        writer = self._conns.get(conn)
        if writer is not None:
            writer.write(payload)

    def _drop(self, conn: int) -> None:
        writer = self._conns.pop(conn, None)
        if writer is not None:
            writer.close()

    def _send(self, kind: int, conn: int, payload: bytes = b"") -> None:
        self._writes.put(wire.encode(kind, conn, payload))

    async def _close_all(self) -> None:
        if self._server is not None:
            self._server.close()
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for writer in list(self._conns.values()):
            writer.close()
        self._conns.clear()

    def _shutdown(self) -> None:
        """Idempotent; never call from the loop thread."""
        with self._shut_lock:
            if self._shut:
                return
            self._shut = True
        self._ready.set()
        loop = self._loop
        try:
            asyncio.run_coroutine_threadsafe(self._close_all(), loop).result(3)
        except Exception as exc:
            _log.warning("forward: closing connections failed (%s)", type(exc).__name__)
        try:
            loop.call_soon_threadsafe(loop.stop)
        except RuntimeError:
            pass
        self._writes.put(None)
        deadline = time.monotonic() + 2
        while self._proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        try:
            self._proc.terminate()
        except OSError:
            pass
        try:
            self._log_handle.close()
        except (OSError, ValueError):
            pass
        if self._on_close is not None:
            try:
                self._on_close()
            except Exception as exc:
                _log.warning("forward: on_close failed (%s)", type(exc).__name__)
        self.closed.set()
