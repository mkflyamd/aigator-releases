"""MCP client over stdio — spawns a subprocess and speaks newline-delimited JSON-RPC.

Mirrors the public interface of GenericMCPClient (server_info, list_tools, call)
so mcp.manager can dispatch to either based on the connection's `transport` field.

Process lifecycle — pooled:
  acquire_pooled(cfg) returns a shared StdioMCPClient for the given command/args/env.
  One process is kept alive per unique stdio configuration; subsequent calls reuse it.
  This eliminates the 300–800 ms spawn+init overhead that npx/Node servers incur per
  call. The pool is keyed by (command, tuple(args), frozenset(env.items())).

  Callers that use acquire_pooled() MUST NOT call close() — the pool owns the process.
  Use release_from_pool(cfg) when a connection is deleted to terminate and evict it.

Direct (non-pooled) usage is still supported: instantiate StdioMCPClient directly
and call close() when done. Used for one-shot dry-run probes during connection setup.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import shutil
import subprocess
import threading
from typing import Any

from proc_utils import ensure_bundled_node_on_path, no_window_kwargs

_log = logging.getLogger(__name__)


class CommandNotFoundError(RuntimeError):
    """Raised when the configured command isn't on PATH."""


_INIT_PARAMS = {
    "protocolVersion": "2025-03-26",
    "capabilities": {},
    "clientInfo": {"name": "aigator", "version": "1.0"},
}

_EOF = object()  # sentinel pushed by reader thread when stdout closes

# Maximum messages buffered from a stdio server before back-pressure kicks in.
# Caps memory if a misbehaving server floods stdout.
_QUEUE_MAXSIZE = 256

# ── Process pool ──────────────────────────────────────────────────────────────
_pool: dict[tuple, "StdioMCPClient"] = {}
_pool_lock = threading.Lock()


def _pool_key(cfg: dict) -> tuple:
    return (
        cfg.get("command", ""),
        tuple(cfg.get("args", [])),
        frozenset((cfg.get("env") or {}).items()),
    )


def acquire_pooled(cfg: dict) -> "StdioMCPClient":
    """Return the shared StdioMCPClient for this config, spawning one if needed.

    The returned client is owned by the pool — do NOT call close() on it.
    """
    key = _pool_key(cfg)
    with _pool_lock:
        existing = _pool.get(key)
        if existing is not None:
            # Restart if the subprocess died unexpectedly.
            if existing._proc is not None and existing._proc.poll() is None:
                return existing
            _log.warning("[stdio-pool] process for %r exited; restarting", cfg.get("name") or cfg.get("command"))
            try:
                existing.close()
            except Exception:
                pass
        client = StdioMCPClient(cfg)
        _pool[key] = client
        _log.info("[stdio-pool] spawned %r (pool size %d)", cfg.get("name") or cfg.get("command"), len(_pool))
        return client


def release_from_pool(cfg: dict) -> None:
    """Terminate and evict the pooled process for this config (call on connection delete)."""
    key = _pool_key(cfg)
    with _pool_lock:
        client = _pool.pop(key, None)
    if client is not None:
        try:
            client.close()
        except Exception:
            pass
        _log.info("[stdio-pool] released %r", cfg.get("name") or cfg.get("command"))


class StdioMCPClient:
    def __init__(self, cfg: dict, timeout: float = 30.0) -> None:
        self._cfg = cfg
        self._name = cfg.get("name", cfg.get("command", "mcp"))
        self._timeout = timeout
        self._proc: subprocess.Popen | None = None
        self._next_id = 1
        self._queue: queue.Queue = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        self._reader: threading.Thread | None = None
        self._stderr_lines: list[str] = []
        self._stderr_reader: threading.Thread | None = None
        try:
            self._connect()
        except Exception:
            self.close()
            raise

    def _resolve_command(self) -> str:
        command = self._cfg["command"]
        # Prefer AI Gator's bundled Node (if shipped) so npx/node servers resolve
        # to our copy regardless of the user's system Node / PATH.
        ensure_bundled_node_on_path()
        resolved = shutil.which(command)
        if not resolved:
            raise CommandNotFoundError(self._not_found_message(command))
        return resolved

    def _not_found_message(self, command: str) -> str:
        """Build a helpful error, naming the dependency the MCP server needs."""
        base = command.lower()
        node_tools = {"npx", "node", "npm"}
        py_tools = {"uvx", "uv"}
        if base in node_tools:
            hint = (
                f"This MCP server ('{self._name}') needs Node.js, which isn't installed. "
                "Install it from https://nodejs.org (or run the AI Gator setup again to "
                "install it for you), then restart AI Gator."
            )
        elif base in py_tools:
            hint = (
                f"This MCP server ('{self._name}') needs uv/uvx, which isn't installed. "
                "Install it from https://docs.astral.sh/uv/, then restart AI Gator."
            )
        else:
            hint = (
                f"The command '{command}' for MCP server '{self._name}' wasn't found on "
                "PATH. Install it and restart AI Gator."
            )
        return hint

    def _spawn(self) -> subprocess.Popen:
        resolved = self._resolve_command()
        env = {**os.environ, **self._cfg.get("env", {})}
        return subprocess.Popen(
            [resolved, *self._cfg.get("args", [])],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1,
            **no_window_kwargs(),
        )

    def _reader_loop(self, stdout) -> None:
        try:
            for line in iter(stdout.readline, ""):
                try:
                    self._queue.put(line, timeout=5)
                except queue.Full:
                    _log.warning("[stdio] %s: output queue full — dropping line", self._name)
        except Exception:
            pass
        finally:
            self._queue.put(_EOF)

    def _stderr_loop(self, stderr) -> None:
        try:
            for line in iter(stderr.readline, ""):
                self._stderr_lines.append(line.rstrip("\n"))
        except Exception:
            pass

    def _stderr_tail(self, max_lines: int = 10) -> str:
        return "\n".join(self._stderr_lines[-max_lines:]).strip()

    def _send(self, method: str, params: dict | None = None) -> dict:
        if self._proc is None or self._proc.poll() is not None:
            raise RuntimeError(f"{self._name}: subprocess is not running")
        req_id = self._next_id
        self._next_id += 1
        msg = {"jsonrpc": "2.0", "method": method, "id": req_id}
        if params is not None:
            msg["params"] = params
        try:
            self._proc.stdin.write(json.dumps(msg) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise RuntimeError(f"{self._name}: failed to write to subprocess: {e}") from e

        try:
            line = self._queue.get(timeout=self._timeout)
        except queue.Empty:
            self.close()
            stderr = self._stderr_tail()
            detail = f"\nServer stderr:\n{stderr}" if stderr else ""
            raise TimeoutError(
                f"MCP server did not respond within {self._timeout}s{detail}"
            )
        if line is _EOF:
            if self._stderr_reader:
                self._stderr_reader.join(timeout=1.0)
            stderr = self._stderr_tail()
            detail = f"\nServer stderr:\n{stderr}" if stderr else ""
            raise RuntimeError(f"{self._name}: subprocess closed stdout{detail}")
        try:
            return json.loads(line)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"{self._name}: invalid JSON from subprocess: {line[:200]}") from e

    def _send_notification(self, method: str, params: dict | None = None) -> None:
        if self._proc is None or self._proc.poll() is not None:
            return
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        try:
            self._proc.stdin.write(json.dumps(msg) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def _connect(self) -> None:
        self._proc = self._spawn()
        self._reader = threading.Thread(
            target=self._reader_loop, args=(self._proc.stdout,), daemon=True
        )
        self._reader.start()
        self._stderr_reader = threading.Thread(
            target=self._stderr_loop, args=(self._proc.stderr,), daemon=True
        )
        self._stderr_reader.start()
        resp = self._send("initialize", _INIT_PARAMS)
        if "error" in resp:
            raise RuntimeError(f"MCP init failed: {resp['error']}")
        self._server_info = resp.get("result", {}).get("serverInfo", {})
        self._send_notification("notifications/initialized")

    def server_info(self) -> dict:
        return self._server_info

    def list_tools(self) -> list[dict]:
        resp = self._send("tools/list", {})
        if "error" in resp:
            raise RuntimeError(f"tools/list failed: {resp['error']}")
        return resp.get("result", {}).get("tools", [])

    def call(self, tool: str, arguments: dict[str, Any] | None = None) -> str:
        resp = self._send("tools/call", {"name": tool, "arguments": arguments or {}})
        if "error" in resp:
            raise RuntimeError(f"{self._name}: {resp['error'].get('message', 'tool call failed')}")
        content = resp.get("result", {}).get("content", [])
        return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")

    def close(self) -> None:
        if self._proc is None:
            return
        # Terminate the subprocess FIRST so the OS closes its end of the pipes.
        # The reader threads (blocked in stdout/stderr.readline()) then see EOF
        # and exit on their own. Closing handles from the main thread while a
        # reader is blocked on them can deadlock Windows' subprocess lock —
        # subsequent Popen() calls then hang indefinitely.
        try:
            if self._proc.stdin and not self._proc.stdin.closed:
                self._proc.stdin.close()
        except Exception:
            pass
        try:
            self._proc.terminate()
            self._proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            try:
                self._proc.wait(timeout=2)
            except Exception:
                pass
        except Exception:
            pass
        # Give the reader threads a moment to drain EOF before we discard the
        # Popen object (which would otherwise close the underlying handles
        # under their feet).
        for t in (self._reader, self._stderr_reader):
            if t is not None and t.is_alive():
                try:
                    t.join(timeout=1.0)
                except Exception:
                    pass
        try:
            if self._proc.stderr and not self._proc.stderr.closed:
                self._proc.stderr.close()
        except Exception:
            pass
        self._proc = None
