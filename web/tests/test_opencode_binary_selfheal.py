"""Regression: the recurring "OpenCode won't start" outage was a missing
node_modules/opencode-ai/bin/opencode.exe (opencode's destructive-on-retry
postinstall + WakeGator re-triggering it left the shim's target deleted).
_ensure_opencode_binary re-materializes the CORRECT platform variant from the
surviving platform package. Critically, it must NEVER copy the AVX2 build onto a
non-AVX2 CPU (that crashes with an illegal instruction) — verified via the
variant-selection tests below.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from skills.opencode_agent import instance_manager as im


def _make_node_dir(tmp_path, installed_pkgs):
    """Build a fake node/ layout: node_modules/opencode-ai/node_modules/<pkg>/bin/opencode.exe
    for each pkg in installed_pkgs. Returns the node_dir Path."""
    node_dir = tmp_path / "node"
    oc_ai = node_dir / "node_modules" / "opencode-ai"
    for pkg in installed_pkgs:
        b = oc_ai / "node_modules" / pkg / "bin"
        b.mkdir(parents=True, exist_ok=True)
        (b / "opencode.exe").write_bytes(b"FAKE_BINARY_" + pkg.encode())
    (oc_ai / "bin").mkdir(parents=True, exist_ok=True)  # bin/ exists but empty
    return node_dir


def test_platform_packages_non_avx2_baseline_only(monkeypatch):
    monkeypatch.setattr(im.sys, "platform", "win32")
    monkeypatch.setattr(im, "_supports_avx2", lambda: False)
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    pkgs = im._opencode_platform_packages()
    # Never offer the AVX2 build on a non-AVX2 CPU (would SIGILL).
    assert pkgs == ["opencode-windows-x64-baseline"]


def test_platform_packages_avx2_prefers_full_then_baseline(monkeypatch):
    monkeypatch.setattr(im.sys, "platform", "win32")
    monkeypatch.setattr(im, "_supports_avx2", lambda: True)
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    pkgs = im._opencode_platform_packages()
    assert pkgs == ["opencode-windows-x64", "opencode-windows-x64-baseline"]


def test_selfheal_noop_when_target_present(tmp_path, monkeypatch):
    monkeypatch.setattr(im.sys, "platform", "win32")
    node_dir = _make_node_dir(tmp_path, ["opencode-windows-x64-baseline"])
    target = node_dir / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
    target.write_bytes(b"ALREADY_HERE")
    im._ensure_opencode_binary(node_dir)
    assert target.read_bytes() == b"ALREADY_HERE"  # untouched


def test_selfheal_materializes_baseline_on_non_avx2(tmp_path, monkeypatch):
    monkeypatch.setattr(im.sys, "platform", "win32")
    monkeypatch.setattr(im, "_supports_avx2", lambda: False)
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    # Both variants installed, but on non-AVX2 we must pick baseline.
    node_dir = _make_node_dir(tmp_path, ["opencode-windows-x64", "opencode-windows-x64-baseline"])
    target = node_dir / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
    assert not target.exists()
    im._ensure_opencode_binary(node_dir)
    assert target.exists()
    assert target.read_bytes() == b"FAKE_BINARY_opencode-windows-x64-baseline"


def test_selfheal_uses_avx2_build_when_supported(tmp_path, monkeypatch):
    monkeypatch.setattr(im.sys, "platform", "win32")
    monkeypatch.setattr(im, "_supports_avx2", lambda: True)
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    node_dir = _make_node_dir(tmp_path, ["opencode-windows-x64", "opencode-windows-x64-baseline"])
    target = node_dir / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
    im._ensure_opencode_binary(node_dir)
    assert target.read_bytes() == b"FAKE_BINARY_opencode-windows-x64"


def test_selfheal_avx2_falls_back_to_baseline_when_only_baseline_present(tmp_path, monkeypatch):
    monkeypatch.setattr(im.sys, "platform", "win32")
    monkeypatch.setattr(im, "_supports_avx2", lambda: True)
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    # AVX2 CPU but only baseline installed → safe fallback, no error.
    node_dir = _make_node_dir(tmp_path, ["opencode-windows-x64-baseline"])
    target = node_dir / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
    im._ensure_opencode_binary(node_dir)
    assert target.read_bytes() == b"FAKE_BINARY_opencode-windows-x64-baseline"


def test_selfheal_raises_clear_error_when_no_source(tmp_path, monkeypatch):
    monkeypatch.setattr(im.sys, "platform", "win32")
    monkeypatch.setattr(im, "_supports_avx2", lambda: False)
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    node_dir = _make_node_dir(tmp_path, [])  # no platform packages at all
    target = node_dir / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
    raised = None
    try:
        im._ensure_opencode_binary(node_dir)
    except RuntimeError as e:
        raised = e
    assert raised is not None
    assert "re-run WakeGator" in str(raised).lower() or "re-run wakegator" in str(raised).lower()
    assert not target.exists()  # never a partial/wrong binary


def test_selfheal_noop_off_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(im.sys, "platform", "linux")
    node_dir = _make_node_dir(tmp_path, [])
    im._ensure_opencode_binary(node_dir)  # must not raise on non-win32


def test_serve_log_path_namespaced_by_port():
    p1 = im._serve_log_path("AgenticPOC", 8100)
    p2 = im._serve_log_path("AgenticPOC", 8101)
    assert p1 != p2  # same project, different port → different log (no collision)
    assert p1.name == "AgenticPOC-8100.log"


def test_selfheal_tolerates_replace_permissionerror_when_target_present(tmp_path, monkeypatch):
    """Cross-instance safety: if os.replace fails because a peer instance is
    executing the target (Windows locks running exes) but the target now
    exists (the peer healed it), that must be treated as success, not an error."""
    monkeypatch.setattr(im.sys, "platform", "win32")
    monkeypatch.setattr(im, "_supports_avx2", lambda: False)
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    node_dir = _make_node_dir(tmp_path, ["opencode-windows-x64-baseline"])
    target = node_dir / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"

    real_replace = im.os.replace

    def fake_replace(src, dst):
        # Simulate a peer having healed the target, then our replace losing the
        # race with a lock error.
        pathlib.Path(dst).write_bytes(b"PEER_HEALED")
        raise PermissionError("target is being executed by a peer")

    monkeypatch.setattr(im.os, "replace", fake_replace)
    im._ensure_opencode_binary(node_dir)  # must NOT raise
    monkeypatch.setattr(im.os, "replace", real_replace)
    assert target.read_bytes() == b"PEER_HEALED"


def test_selfheal_clears_preflight_cache(tmp_path, monkeypatch):
    """A mid-session vanish+heal must force the --version preflight to re-run,
    so a stale 'verified' flag can't skip validating a freshly-materialized
    binary."""
    monkeypatch.setattr(im.sys, "platform", "win32")
    monkeypatch.setattr(im, "_supports_avx2", lambda: False)
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    node_dir = _make_node_dir(tmp_path, ["opencode-windows-x64-baseline"])
    monkeypatch.setattr(im, "_preflight_ok", True)  # pretend a prior verify passed
    im._ensure_opencode_binary(node_dir)  # heals → must reset the flag
    assert im._preflight_ok is False
