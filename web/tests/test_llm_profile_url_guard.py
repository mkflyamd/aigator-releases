"""Tests for the loopback-URL guard in create_or_update_llm_profile.

Verifies:
- Loopback URLs (localhost, 127.0.0.1, 0.0.0.0, ::1) are rejected for
  non-temporary production profiles.
- Private LAN ranges (10.x, 192.168.x, 172.16-31.x) are ALLOWED as persistent
  production profiles — a self-hosted model on a LAN host is legitimate.
- temporary=true bypasses the guard.
- The old substring-matching bug (e.g. "10." matching "api10.openai.com") is
  fixed — only true loopback hosts are blocked.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from fastapi import HTTPException

import routes.config_routes as cr


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_profile(base_url, **extra):
    p = {"base_url": base_url, "api_key": "sk-test", "name": "test"}
    p.update(extra)
    return p


def _stub_config(monkeypatch, cfg=None):
    """Stub config load/save so tests don't touch disk."""
    cfg = cfg or {"llm_profiles": []}
    monkeypatch.setattr(cr, "_load_config", lambda: cfg)
    monkeypatch.setattr(cr, "_save_config", lambda c: None)
    # Stub _fetch_profile_models so a passing guard is observable: if the guard
    # passed, this runs and returns a canned list; if the guard blocked, the
    # HTTPException is raised before we ever get here.
    monkeypatch.setattr(cr, "_fetch_profile_models", lambda p: ["test-model"])
    # Stub load_profile so we don't hit the registry
    monkeypatch.setattr("llm.registry.load_profile", lambda p: None)
    return cfg


# ── Loopback URLs: blocked for production profiles ────────────────────────────

@pytest.mark.parametrize("url", [
    "http://localhost:8000/v1",
    "http://127.0.0.1:8000/v1",
    "http://0.0.0.0:8000/v1",
    "http://[::1]:8000/v1",
])
async def test_loopback_blocked_for_production(url, monkeypatch):
    _stub_config(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await cr.create_or_update_llm_profile(_make_profile(url))
    assert exc.value.status_code == 400
    assert "Loopback URLs" in exc.value.detail


# ── Private LAN ranges: ALLOWED for production profiles ───────────────────────

@pytest.mark.parametrize("url", [
    "http://10.7.125.6:8000/v1",       # user's self-hosted model
    "http://10.0.0.1:8000/v1",
    "http://192.168.1.50:8000/v1",
    "http://172.16.0.1:8000/v1",
    "http://172.31.255.255:8000/v1",   # last /12 address
])
async def test_private_lan_allowed_for_production(url, monkeypatch):
    cfg = _stub_config(monkeypatch)
    result = await cr.create_or_update_llm_profile(_make_profile(url))
    # If _fetch_profile_models was called (mocked), models is populated → guard passed
    assert result.get("models") == ["test-model"]
    # Profile persisted to cfg
    assert any(p["base_url"] == url for p in cfg["llm_profiles"])


# ── Substring false-positive bug: regression test ─────────────────────────────

@pytest.mark.parametrize("url", [
    "https://api10.openai.com/v1",          # "10." substring, not private
    "https://something-192.168.example.com", # "192.168." substring in hostname
    "https://172.16.example.com/v1",         # "172.16." substring, public DNS
])
async def test_no_substring_false_positive(url, monkeypatch):
    """The old check matched substrings like '10.' anywhere in the URL,
    false-positive-matching public hostnames like api10.openai.com.
    The new check uses urlparse().hostname and only blocks true loopback,
    so these public URLs must pass the guard."""
    cfg = _stub_config(monkeypatch)
    result = await cr.create_or_update_llm_profile(_make_profile(url))
    assert result.get("models") == ["test-model"]


# ── temporary=true bypasses the guard ─────────────────────────────────────────

async def test_temporary_bypasses_loopback_guard(monkeypatch):
    cfg = _stub_config(monkeypatch)
    result = await cr.create_or_update_llm_profile(
        _make_profile("http://127.0.0.1:8000/v1", temporary=True)
    )
    assert result.get("models") == ["test-model"]
    assert result.get("temporary") is True


# ── Empty base_url: no crash (no guard, no fetch) ─────────────────────────────

async def test_empty_base_url_skips_guard(monkeypatch):
    _stub_config(monkeypatch)
    # Empty base_url should skip the guard; _fetch_profile_models is still
    # called but mocked, so we just verify no HTTPException from the guard.
    result = await cr.create_or_update_llm_profile(_make_profile(""))
    assert result.get("models") == ["test-model"]
