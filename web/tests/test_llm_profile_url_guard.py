"""Tests for the loopback-URL guard in create_or_update_llm_profile,
LM Studio /api/v0/models URL derivation, and context-window normalization.

Verifies:
- Loopback URLs (localhost, 127.0.0.1, 0.0.0.0, ::1) are rejected for
  non-temporary production profiles.
- Private LAN ranges (10.x, 192.168.x, 172.16-31.x) are ALLOWED as persistent
  production profiles — a self-hosted model on a LAN host is legitimate.
- temporary=true bypasses the guard.
- The old substring-matching bug (e.g. "10." matching "api10.openai.com") is
  fixed — only true loopback hosts are blocked.
- LM Studio metadata URL strips /v1 to produce the correct server origin
  (exercises the real _fetch_profile_models production code via mocked httpx).
- model_context_windows is normalized to positive integers regardless of
  input type (exercises the real load_profile production code).
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from fastapi import HTTPException

import routes.config_routes as cr
import llm.registry as registry


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


# ── LM Studio /api/v0/models URL derivation (real production code) ────────────

def _make_httpx_response(status_code: int, json_body: dict):
    """Build a minimal httpx.Response-alike accepted by _fetch_profile_models."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.is_success = (200 <= status_code < 300)
    resp.json.return_value = json_body
    return resp


@pytest.mark.parametrize("base_url,expected_lms_url", [
    ("http://localhost:1234/v1",  "http://localhost:1234/api/v0/models"),
    ("http://localhost:1234",     "http://localhost:1234/api/v0/models"),
    ("http://localhost:1234/v1/", "http://localhost:1234/api/v0/models"),
    ("http://10.7.47.65:8000/v1", "http://10.7.47.65:8000/api/v0/models"),
    ("http://10.7.47.65:8000",    "http://10.7.47.65:8000/api/v0/models"),
    ("http://localhost:1234/v2",  "http://localhost:1234/api/v0/models"),
])
def test_lmstudio_origin_strips_v1(base_url, expected_lms_url):
    """_fetch_profile_models (real code) must call httpx.get with the server
    origin (no /vN) when fetching LM Studio metadata — not /v1/api/v0/models."""
    profile = {
        "type": "local",
        "base_url": base_url,
        "api_key": "",
        "api_key_header": "",
        "user_id": "",
    }

    # Two GET calls: one for /v1/models, one for /api/v0/models
    v1_resp = _make_httpx_response(200, {"data": [{"id": "test-model"}]})
    lms_resp = _make_httpx_response(200, {"data": [
        {"id": "test-model", "loaded_context_length": 32768}
    ]})

    captured_urls = []

    def fake_get(url, **kwargs):
        captured_urls.append(url)
        if "api/v0" in url:
            return lms_resp
        return v1_resp

    with patch("httpx.get", side_effect=fake_get):
        cr._fetch_profile_models(profile)

    lms_calls = [u for u in captured_urls if "api/v0" in u]
    assert lms_calls, "Expected a call to /api/v0/models"
    assert lms_calls[0] == expected_lms_url, (
        f"Expected {expected_lms_url!r}, got {lms_calls[0]!r}"
    )
    # Also verify the loaded_context_length was captured
    assert profile.get("model_context_windows", {}).get("test-model") == 32768


# ── model_context_windows normalization via real load_profile ─────────────────

@pytest.mark.parametrize("ctx_windows,model_id,expected_ctx", [
    # Valid: integer kept as-is
    ({"m": 32768},   "m", 32768),
    # Valid: numeric string coerced to int
    ({"m": "32768"}, "m", 32768),
    # Valid: float truncated to int
    ({"m": 32768.9}, "m", 32768),
    # Invalid: zero -> fallback 200000
    ({"m": 0},       "m", 200000),
    # Invalid: negative -> fallback 200000
    ({"m": -1},      "m", 200000),
    # Invalid: non-numeric string -> fallback 200000
    ({"m": "bad"},   "m", 200000),
    # Invalid: None value -> fallback 200000
    ({"m": None},    "m", 200000),
    # Wrong container: None -> fallback 200000
    (None,           "m", 200000),
    # Wrong container: list -> fallback 200000
    ([1, 2, 3],      "m", 200000),
    # Wrong container: string -> fallback 200000
    ("32768",        "m", 200000),
])
def test_context_window_normalization_via_load_profile(ctx_windows, model_id, expected_ctx):
    """load_profile (real code) must normalize model_context_windows to positive
    ints and fall back to 200000 for zero, negative, invalid, and non-dict input."""
    profile = {
        "type": "openai",
        "models": [model_id],
        "active_model": model_id,
        "model_context_windows": ctx_windows,
    }
    registry.load_profile(profile)
    entry = registry.MODEL_REGISTRY.get(model_id)
    assert entry is not None, f"MODEL_REGISTRY missing {model_id!r}"
    assert entry.context_window == expected_ctx, (
        f"ctx_windows={ctx_windows!r}: expected {expected_ctx}, got {entry.context_window}"
    )


def test_context_window_mixed_valid_invalid_via_load_profile():
    """Mixed map: valid entries used, invalid dropped to 200000."""
    profile = {
        "type": "openai",
        "models": ["a", "b", "c", "d"],
        "active_model": "a",
        "model_context_windows": {"a": 8192, "b": 0, "c": "nope", "d": "4096"},
    }
    registry.load_profile(profile)
    assert registry.MODEL_REGISTRY["a"].context_window == 8192
    assert registry.MODEL_REGISTRY["b"].context_window == 200000
    assert registry.MODEL_REGISTRY["c"].context_window == 200000
    assert registry.MODEL_REGISTRY["d"].context_window == 4096
