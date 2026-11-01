"""Standalone PTY host: owns the coding-agent PTYs so they outlive the backend.

The backend (uvicorn) restarts on every code change; PTYs held in its memory die
with it. This process holds them instead. The backend connects over loopback,
authenticates with a token from a state file, and either creates a session or
attaches to an existing one and receives its buffered output plus live output.

Wire format: one JSON object per line. The first message on a connection must be
{"op": "hello", "token": ..., "proto": N}. Requests with a reply: create, status,
list, close, attach. After attach, the connection also carries output events
({"t": "out", "off": N, "data": ...}, {"t": "exit"}) and accepts write and resize
requests, which have no reply.

Run as a script: python pty_host.py --key <instance key>
"""

import argparse
import asyncio
import hmac
import json
import logging
import os
import re
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

from pty_session import PtySession
from pty_spawn import spawn_pty

logger = logging.getLogger("pty_host")

PROTOCOL_VERSION = 1
_OUT_PIECE_CHARS = 64 * 1024
_LINE_LIMIT = 8 * 1024 * 1024
_REAP_INTERVAL = 30.0


def _env_seconds(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


# With no backend connected this long, the host closes everything and exits, so
# quitting AI Gator does not leave coding agents running forever.
ORPHAN_TIMEOUT = _env_seconds("GATOR_PTY_HOST_ORPHAN_SECONDS", 600.0)
# A session whose process ended and that nobody is attached to is dropped after this.
DONE_TTL = _env_seconds("GATOR_PTY_HOST_DONE_SECONDS", 1800.0)


def state_dir() -> Path:
    return Path.home() / ".gator"


def safe_key(key: str) -> str:
    return re.sub(r"[^0-9A-Za-z_-]", "_", str(key)) or "default"


def host_file(key: str) -> Path:
    return state_dir() / f"pty-host-{safe_key(key)}.json"


def host_log_file(key: str) -> Path:
    return state_dir() / f"pty-host-{safe_key(key)}.log"


class PtyHost:
    def __init__(self, token: str, spawn=spawn_pty):
        self._token = token
        self._spawn = spawn
        self.sessions: dict[str, PtySession] = {}
        self._connections = 0
        self._attached: dict[str, int] = {}
        self._done_since: dict[str, float] = {}
        self._last_connection = time.time()

    def reap(self, now: float, orphan_timeout: float, done_ttl: float) -> bool:
        """Drop finished, unwatched sessions. Returns True when the host should exit
        because no backend has been connected for orphan_timeout."""
        for sid, session in list(self.sessions.items()):
            if not session.done or self._attached.get(sid):
                self._done_since.pop(sid, None)
                continue
            since = self._done_since.setdefault(sid, now)
            if now - since >= done_ttl:
                self.sessions.pop(sid, None)
                self._done_since.pop(sid, None)
                session.close()
        if self._connections:
            return False
        return now - self._last_connection >= orphan_timeout

    def close_all(self) -> None:
        for session in self.sessions.values():
            try:
                session.close()
            except Exception:
                logger.exception("closing a session failed")
        self.sessions.clear()

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._connections += 1
        attached_id: str | None = None
        pump: asyncio.Task | None = None
        try:
            hello = await self._read(reader)
            if (
                not hello
                or hello.get("op") != "hello"
                or not hmac.compare_digest(
                    str(hello.get("token", "")), self._token
                )
            ):
                await self._send(writer, {"ok": False, "error": "auth"})
                return
            if hello.get("proto") != PROTOCOL_VERSION:
                await self._send(
                    writer,
                    {"ok": False, "error": "proto", "proto": PROTOCOL_VERSION},
                )
                return
            await self._send(
                writer, {"ok": True, "proto": PROTOCOL_VERSION, "pid": os.getpid()}
            )

            attached: PtySession | None = None
            while True:
                msg = await self._read(reader)
                if msg is None:
                    break
                op = msg.get("op")
                if op == "write" and attached is not None:
                    try:
                        attached.write(str(msg.get("data", "")))
                    except Exception:
                        logger.exception("pty write failed")
                elif op == "resize" and attached is not None:
                    try:
                        attached.resize(int(msg["cols"]), int(msg["rows"]))
                    except Exception:
                        logger.exception("pty resize failed")
                elif op == "attach":
                    session = self.sessions.get(str(msg.get("id", "")))
                    if session is None:
                        await self._send(writer, {"ok": False, "error": "missing"})
                        continue
                    if pump is not None:
                        pump.cancel()
                    self._release(attached_id)
                    attached, attached_id = session, str(msg["id"])
                    self._attached[attached_id] = self._attached.get(attached_id, 0) + 1
                    pump = await self._attach(session, msg, writer)
                else:
                    reply = await self._request(op, msg, attached)
                    await self._send(writer, reply)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        except Exception:
            logger.exception("pty host connection failed")
        finally:
            if pump is not None:
                pump.cancel()
            self._release(attached_id)
            self._connections -= 1
            self._last_connection = time.time()
            writer.close()

    def _release(self, sid: str | None) -> None:
        if sid is None:
            return
        left = self._attached.get(sid, 0) - 1
        if left > 0:
            self._attached[sid] = left
        else:
            self._attached.pop(sid, None)

    async def _request(self, op, msg: dict, attached) -> dict:
        loop = asyncio.get_running_loop()
        sid = str(msg.get("id", ""))
        if op == "create":
            if sid in self.sessions:
                return {"ok": False, "error": "exists"}
            try:
                pty = await loop.run_in_executor(
                    None,
                    lambda: self._spawn(
                        cols=int(msg.get("cols", 220)),
                        rows=int(msg.get("rows", 24)),
                        command=msg.get("command"),
                        env=msg.get("env"),
                        cwd=msg.get("cwd"),
                    ),
                )
            except Exception as exc:
                logger.exception("spawn failed")
                return {"ok": False, "error": f"spawn failed: {exc}"}
            self.sessions[sid] = PtySession(pty)
            return {"ok": True}
        if op == "status":
            session = self.sessions.get(sid)
            return {
                "ok": True,
                "exists": session is not None,
                "alive": bool(session and not session.done and session.isalive()),
                "done": bool(session and session.done),
            }
        if op == "list":
            return {
                "ok": True,
                "sessions": [
                    {"id": k, "done": s.done} for k, s in self.sessions.items()
                ],
            }
        if op == "close":
            session = self.sessions.pop(sid, None)
            if session is not None:
                await loop.run_in_executor(None, session.close)
            return {"ok": True, "existed": session is not None}
        return {"ok": False, "error": f"unknown op {op!r}"}

    async def _attach(
        self, session: PtySession, msg: dict, writer: asyncio.StreamWriter
    ) -> asyncio.Task:
        loop = asyncio.get_running_loop()
        # Subscribe before the first read so output arriving in between is not lost.
        wake = session.subscribe(loop)
        data, end = session.read_from(int(msg.get("offset", 0) or 0))
        await self._send(writer, {"ok": True, "start": end - len(data)})
        return asyncio.create_task(self._pump(session, wake, data, end, writer))

    async def _pump(self, session, wake, data, end, writer) -> None:
        try:
            while True:
                await self._send_output(writer, end - len(data), data)
                wake.clear()
                finished = session.done
                data, new_end = session.read_from(end)
                end = new_end
                if not data:
                    if finished:
                        break
                    await wake.wait()
            await self._send(writer, {"t": "exit"})
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            session.unsubscribe(wake)

    async def _send_output(self, writer, offset: int, data: str) -> None:
        for i in range(0, len(data), _OUT_PIECE_CHARS):
            piece = data[i : i + _OUT_PIECE_CHARS]
            await self._send(
                writer, {"t": "out", "off": offset + i, "data": piece}
            )

    @staticmethod
    async def _read(reader: asyncio.StreamReader) -> dict | None:
        try:
            line = await reader.readline()
        except (ValueError, asyncio.LimitOverrunError):
            return None
        if not line:
            return None
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return {}
        return msg if isinstance(msg, dict) else {}

    @staticmethod
    async def _send(writer: asyncio.StreamWriter, obj: dict) -> None:
        writer.write((json.dumps(obj) + "\n").encode("utf-8"))
        await writer.drain()


def probe_state(key: str, timeout: float = 1.0) -> tuple[str, dict | None]:
    """("up", info) if a host for this key answers a hello, ("incompatible", info)
    if one answers but speaks another protocol version, else ("down", None)."""
    try:
        info = json.loads(host_file(key).read_text(encoding="utf-8"))
        with socket.create_connection(("127.0.0.1", int(info["port"])), timeout) as s:
            s.settimeout(timeout)
            s.sendall(
                (
                    json.dumps(
                        {"op": "hello", "token": info["token"], "proto": PROTOCOL_VERSION}
                    )
                    + "\n"
                ).encode()
            )
            reply = json.loads(s.makefile("rb").readline() or b"{}")
    except (OSError, ValueError, KeyError):
        return "down", None
    if reply.get("ok"):
        return "up", info
    if reply.get("error") == "proto":
        return "incompatible", info
    return "down", None


def probe(key: str, timeout: float = 1.0) -> dict | None:
    state, info = probe_state(key, timeout)
    return info if state == "up" else None


def host_command(key: str) -> list[str]:
    return [sys.executable, str(Path(__file__).resolve()), "--key", key]


def launch_detached(key: str, wait: float = 15.0) -> bool:
    """Start a host that is not a descendant of the caller, wait until it answers,
    then return. Meant to run in a short-lived launcher process (--detach): once
    the launcher exits, the host's recorded parent is gone, so a tree kill of the
    backend (taskkill /T, a dev script walking children) cannot reach it."""
    log_path = host_log_file(key)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict = dict(
        stdin=subprocess.DEVNULL,
        close_fds=True,
        cwd=str(Path(__file__).resolve().parent),
    )
    with open(log_path, "ab") as log:
        kwargs.update(stdout=log, stderr=log)
        if os.name == "nt":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            try:
                # Leave the caller's job object, if it allows it.
                proc = subprocess.Popen(
                    host_command(key), creationflags=flags | 0x01000000, **kwargs
                )
            except OSError:
                proc = subprocess.Popen(host_command(key), creationflags=flags, **kwargs)
        else:
            proc = subprocess.Popen(host_command(key), start_new_session=True, **kwargs)
    deadline = time.time() + wait
    while time.time() < deadline:
        if probe_state(key)[0] != "down":
            return True
        if proc.poll() is not None:
            return probe_state(key)[0] != "down"
        time.sleep(0.1)
    return False


def _write_host_file(key: str, info: dict) -> None:
    path = host_file(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(info), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


async def _reaper(host: PtyHost, stop: asyncio.Event) -> None:
    while not stop.is_set():
        await asyncio.sleep(_REAP_INTERVAL)
        try:
            if host.reap(time.time(), ORPHAN_TIMEOUT, DONE_TTL):
                logger.info("no backend connected for %ss; exiting", ORPHAN_TIMEOUT)
                stop.set()
        except Exception:
            logger.exception("reaper failed")


async def _amain(key: str) -> None:
    if probe_state(key)[0] != "down":
        logger.info("a host for %s is already running; exiting", key)
        return
    token = secrets.token_hex(32)
    host = PtyHost(token)
    server = await asyncio.start_server(
        host.handle, "127.0.0.1", 0, limit=_LINE_LIMIT
    )
    port = server.sockets[0].getsockname()[1]
    _write_host_file(
        key,
        {
            "pid": os.getpid(),
            "port": port,
            "token": token,
            "proto": PROTOCOL_VERSION,
            "started": time.time(),
        },
    )
    logger.info("pty host %s listening on 127.0.0.1:%s pid %s", key, port, os.getpid())
    stop = asyncio.Event()
    reaper = asyncio.create_task(_reaper(host, stop))
    try:
        async with server:
            await stop.wait()
    finally:
        reaper.cancel()
        host.close_all()
        try:
            info = json.loads(host_file(key).read_text(encoding="utf-8"))
            if info.get("pid") == os.getpid():
                host_file(key).unlink()
        except (OSError, ValueError):
            pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", required=True)
    parser.add_argument(
        "--detach",
        action="store_true",
        help="start a detached host, wait until it answers, and exit",
    )
    args = parser.parse_args(argv)
    if args.detach:
        sys.exit(0 if launch_detached(args.key) else 1)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(_amain(args.key))


if __name__ == "__main__":
    main()
