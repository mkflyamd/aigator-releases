"""MCP client over stdio — spawns a subprocess and speaks newline-delimited JSON-RPC.

Mirrors the public interface of GenericMCPClient (server_info, list_tools, call)
so mcp.manager can dispatch to either based on the connection's `transport` field.

Process lifecycle: the subprocess is long-lived for the life of the client. Each
tool handler in mcp.manager._register creates a fresh client per call (matching
the existing pattern); on stdio that means spawn → init → call → close per
user-facing tool invocation. This trades startup latency for stateless simplicity
and matches how the HTTP client already works.

Callers MUST invoke close() explicitly (typically via the manager). This class
does not implement __del__ because finalizer ordering at interpreter shutdown
is unreliable.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
from typing import Any


class CommandNotFoundError(RuntimeError):
    """Raised when the configured command isn't on PATH."""


_INIT_PARAMS = {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {"name": "aigator", "version": "1.0"},
}

_EOF = object()  # sentinel pushed by reader thread when stdout closes


class StdioMCPClient:
    def __init__(self, cfg: dict, timeout: float = 30.0) -> None:
        self._cfg = cfg
        self._name = cfg.get("name", cfg.get("command", "mcp"))
        self._timeout = timeout
        self._proc: subprocess.Popen | None = None
        self._next_id = 1
        self._queue: queue.Queue = queue.Queue()
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
        resolved = shutil.which(command)
        if not resolved:
            raise CommandNotFoundError(
                f"Command not found on PATH: {command}"
            )
        return resolved

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
        )

    def _reader_loop(self, stdout) -> None:
        try:
            for line in iter(stdout.readline, ""):
                self._queue.put(line)
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
        try:
            if self._proc.stdin and not self._proc.stdin.closed:
                self._proc.stdin.close()
        except Exception:
            pass
        try:
            if self._proc.stderr and not self._proc.stderr.closed:
                self._proc.stderr.close()
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
        self._proc = None
