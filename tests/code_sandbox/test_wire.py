import struct

import pytest

from sandbox import wire


def test_round_trip():
    data = wire.encode(wire.DATA, 7, b"hello") + wire.encode(wire.CLOSE, 7)
    frames = wire.Decoder().feed(data)
    assert frames == [(wire.DATA, 7, b"hello"), (wire.CLOSE, 7, b"")]


def test_frame_split_across_reads():
    data = wire.encode(wire.LOG, 0, b"abcdef")
    decoder = wire.Decoder()
    out = []
    for i in range(len(data)):
        out += decoder.feed(data[i:i + 1])
    assert out == [(wire.LOG, 0, b"abcdef")]


def test_oversized_payload_rejected_on_encode():
    with pytest.raises(wire.WireError):
        wire.encode(wire.DATA, 1, b"x" * (wire.MAX_PAYLOAD + 1))


def test_oversized_length_rejected_on_decode():
    bad = struct.pack("!BII", wire.DATA, 1, wire.MAX_PAYLOAD + 1)
    with pytest.raises(wire.WireError):
        wire.Decoder().feed(bad)


def test_unknown_kind_rejected():
    with pytest.raises(wire.WireError):
        wire.Decoder().feed(struct.pack("!BII", 99, 0, 0))
    with pytest.raises(wire.WireError):
        wire.encode(99, 0)


def test_open_and_exit_payloads():
    assert wire.parse_open(wire.open_payload(3030)) == 3030
    assert wire.parse_exit(wire.exit_payload(-9)) == -9
    assert wire.parse_exit(wire.exit_payload(3)) == 3
    with pytest.raises(wire.WireError):
        wire.parse_open(b"x")
    with pytest.raises(wire.WireError):
        wire.parse_exit(b"")
