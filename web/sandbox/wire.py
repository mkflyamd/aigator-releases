"""Frame format shared by the in-sandbox relay and the backend forwarder.

Stdlib only: relay.py imports this file from the sandbox, so it must not
depend on anything else in AI Gator.

Frame: !BII (kind, connection id, payload length) then the payload.
"""
from __future__ import annotations

import struct

OPEN, DATA, CLOSE, LOG, EXIT = 1, 2, 3, 4, 5
_KINDS = frozenset((OPEN, DATA, CLOSE, LOG, EXIT))
MAX_PAYLOAD = 64 * 1024
_HEADER = struct.Struct("!BII")
HEADER_SIZE = _HEADER.size


class WireError(ValueError):
    pass


def encode(kind: int, conn: int, payload: bytes = b"") -> bytes:
    if kind not in _KINDS:
        raise WireError(f"unknown frame kind {kind}")
    if len(payload) > MAX_PAYLOAD:
        raise WireError("payload too large")
    return _HEADER.pack(kind, conn, len(payload)) + bytes(payload)


class Decoder:
    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[tuple[int, int, bytes]]:
        buf = self._buf
        buf += data
        frames = []
        while len(buf) >= HEADER_SIZE:
            kind, conn, length = _HEADER.unpack_from(buf)
            if kind not in _KINDS:
                raise WireError(f"unknown frame kind {kind}")
            if length > MAX_PAYLOAD:
                raise WireError("payload too large")
            end = HEADER_SIZE + length
            if len(buf) < end:
                break
            frames.append((kind, conn, bytes(buf[HEADER_SIZE:end])))
            del buf[:end]
        return frames


def open_payload(port: int) -> bytes:
    return struct.pack("!H", port)


def parse_open(payload: bytes) -> int:
    if len(payload) != 2:
        raise WireError("bad OPEN payload")
    return struct.unpack("!H", payload)[0]


def exit_payload(code: int) -> bytes:
    return struct.pack("!q", code)


def parse_exit(payload: bytes) -> int:
    if len(payload) != 8:
        raise WireError("bad EXIT payload")
    return struct.unpack("!q", payload)[0]


def read_some(stream, n: int) -> bytes:
    """Whatever is available (at most n bytes) without waiting to fill n; b"" at EOF."""
    return (getattr(stream, "read1", None) or stream.read)(n)
