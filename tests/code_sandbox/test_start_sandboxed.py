from pathlib import Path

import pytest

import sandbox
from sandbox import SandboxRequest, SandboxUnavailable


def _req():
    return SandboxRequest(argv=["x"], cwd=Path("."), env={}, runtime_paths=[], read_paths=[],
                          write_paths=[], network=False, timeout=1)


def test_refused_when_not_enforced(monkeypatch):
    monkeypatch.setattr(sandbox, "sandbox_level", lambda: "off")
    monkeypatch.setattr(sandbox, "sandbox_unavailable_reason", lambda: "turned off")
    with pytest.raises(SandboxUnavailable, match="turned off"):
        sandbox.start_sandboxed(_req())


def test_platform_without_start_is_not_implemented(monkeypatch):
    monkeypatch.setattr(sandbox, "sandbox_level", lambda: "enforced")
    monkeypatch.setattr(sandbox, "_launcher", lambda: object())
    with pytest.raises(NotImplementedError):
        sandbox.start_sandboxed(_req())


def test_delegates_to_the_launcher(monkeypatch):
    seen = []

    class L:
        def start(self, req):
            seen.append(req)
            return "proc"

    monkeypatch.setattr(sandbox, "sandbox_level", lambda: "enforced")
    monkeypatch.setattr(sandbox, "_launcher", lambda: L())
    req = _req()
    assert sandbox.start_sandboxed(req) == "proc"
    assert seen == [req]


def test_container_readable_is_true_when_not_enforced(monkeypatch):
    monkeypatch.setattr(sandbox, "sandbox_level", lambda: "off")
    assert sandbox.container_readable(Path("C:/anything")) is True
