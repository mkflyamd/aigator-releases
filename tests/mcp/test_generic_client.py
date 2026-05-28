# tests/mcp/test_generic_client.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "web"))

import json
import pytest
from unittest.mock import patch, MagicMock
from mcp.generic_client import GenericMCPClient, _build_auth_headers


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


def test_unreachable_message_on_network_error():
    cfg = {"url": "http://host/mcp", "auth_type": "none", "auth_value": "", "name": "CRM"}
    client = GenericMCPClient.__new__(GenericMCPClient)
    client._cfg = cfg
    client._url = "http://host/mcp"
    client._headers = {}
    client._session_id = None
    with patch("mcp.generic_client._post", side_effect=RuntimeError("network")):
        with pytest.raises(RuntimeError, match="CRM is temporarily unreachable"):
            client.call("some_tool", {})
