# tests/mcp/test_generic_client.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "web"))

import base64
import pytest
from unittest.mock import patch, MagicMock
import httpx
from mcp.generic_client import (
    GenericMCPClient,
    OAuthRequiredError,
    _build_auth_headers,
    _check_auth_http_error,
)


def test_build_auth_headers_none():
    assert _build_auth_headers("none", "") == {}


def test_build_auth_headers_bearer():
    h = _build_auth_headers("bearer", "tok123")
    assert h == {"Authorization": "Bearer tok123"}


def test_build_auth_headers_api_key():
    h = _build_auth_headers("api_key", "mykey")
    assert h == {"X-Api-Key": "mykey"}


def test_client_raises_when_unauthenticated_bearer():
    with pytest.raises(ValueError, match="auth_value"):
        GenericMCPClient({"url": "http://host/mcp", "auth_type": "bearer", "auth_value": ""})


# ── basic-fix: template normalization ─────────────────────────────────────────

def _build_client_skip_connect(cfg):
    """Construct GenericMCPClient but skip the live MCP handshake."""
    with patch.object(GenericMCPClient, "_connect", lambda self: None):
        return GenericMCPClient(cfg)


def _decode_basic(authz_header):
    assert authz_header.lower().startswith("basic ")
    return base64.b64decode(authz_header[6:]).decode("utf-8")


def test_basic_fix_normalizes_at_separator_template():
    # Atlassian docs commonly show `Basic email@api_token` (no colon).
    # After {placeholder} substitution the value reaches the client unencoded
    # with `@` as separator — we must encode email:token, not email:@token.
    cfg = {
        "url": "https://example.com/mcp",
        "auth_type": "none",
        "extra_headers": {"Authorization": "Basic alice@example.com@SECRET_TOKEN"},
    }
    client = _build_client_skip_connect(cfg)
    assert _decode_basic(client._headers["Authorization"]) == "alice@example.com:SECRET_TOKEN"


def test_basic_fix_normalizes_colon_with_stray_at():
    # Mixed: user pasted `{email}@{token}` AND a stray colon — still must
    # produce a single clean `email:token` payload.
    cfg = {
        "url": "https://example.com/mcp",
        "auth_type": "none",
        "extra_headers": {"Authorization": "Basic alice@example.com:@SECRET"},
    }
    client = _build_client_skip_connect(cfg)
    assert _decode_basic(client._headers["Authorization"]) == "alice@example.com:SECRET"


def test_basic_fix_leaves_valid_b64_alone():
    raw = base64.b64encode(b"alice@example.com:TOKEN").decode("ascii")
    cfg = {
        "url": "https://example.com/mcp",
        "auth_type": "none",
        "extra_headers": {"Authorization": f"Basic {raw}"},
    }
    client = _build_client_skip_connect(cfg)
    assert client._headers["Authorization"] == f"Basic {raw}"


def test_basic_fix_preserves_colons_inside_token():
    # Tokens with `:` are rare but legal — don't truncate them.
    cfg = {
        "url": "https://example.com/mcp",
        "auth_type": "none",
        "extra_headers": {"Authorization": "Basic alice@example.com:tok:with:colons"},
    }
    client = _build_client_skip_connect(cfg)
    assert _decode_basic(client._headers["Authorization"]) == "alice@example.com:tok:with:colons"


# ── _check_auth_http_error: OAuth escalation guard ───────────────────────────

def _fake_401(www_authenticate=None, body=b""):
    headers = {"WWW-Authenticate": www_authenticate} if www_authenticate else {}
    response = httpx.Response(401, headers=headers, content=body)
    return httpx.HTTPStatusError("401", request=httpx.Request("GET", "https://x/mcp"), response=response)


def test_oauth_escalation_when_no_user_creds():
    wa = 'Bearer resource_metadata="https://x/.well-known/oauth-protected-resource"'
    err = _fake_401(wa)
    with pytest.raises(OAuthRequiredError):
        _check_auth_http_error(err, "https://x/mcp", user_supplied_auth=False)


def test_oauth_escalation_suppressed_when_user_supplied_auth():
    # Server still advertises Bearer in WWW-Authenticate, but the user already
    # sent Basic creds. A 401 here means "rejected", not "switch to OAuth".
    wa = 'Bearer resource_metadata="https://x/.well-known/oauth-protected-resource"'
    err = _fake_401(wa)
    with pytest.raises(RuntimeError, match="Credentials were rejected"):
        _check_auth_http_error(err, "https://x/mcp", user_supplied_auth=True)


def test_cloudflare_1010_block_takes_priority():
    err = _fake_401(body=b'{"error_code":1010}')
    with pytest.raises(RuntimeError, match="Cloudflare"):
        _check_auth_http_error(err, "https://x/mcp", user_supplied_auth=True)


def test_user_supplied_auth_flag_set_for_basic_template():
    cfg = {
        "url": "https://example.com/mcp",
        "auth_type": "none",
        "extra_headers": {"Authorization": "Basic alice@example.com@SECRET"},
    }
    client = _build_client_skip_connect(cfg)
    assert client._user_supplied_auth is True


def test_user_supplied_auth_flag_false_when_no_creds():
    cfg = {"url": "https://example.com/mcp", "auth_type": "none"}
    client = _build_client_skip_connect(cfg)
    assert client._user_supplied_auth is False
