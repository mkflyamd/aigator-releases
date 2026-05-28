import os
import importlib


def reload_gateway():
    import web.llm.gateway as gw
    importlib.reload(gw)
    return gw


def test_gateway_url_defaults_to_anthropic(monkeypatch):
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    gw = reload_gateway()
    assert gw.LLM_GATEWAY_URL == "https://api.anthropic.com"


def test_gateway_url_reads_from_env(monkeypatch):
    monkeypatch.setenv("LLM_GATEWAY_URL", "https://llm-api.corp.com/Anthropic")
    gw = reload_gateway()
    # LLM_GATEWAY_URL is static (import-time); use get_gateway_url() for dynamic access
    assert gw.get_gateway_url() == "https://llm-api.corp.com/Anthropic"


def test_get_gateway_url_dynamic(monkeypatch):
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    gw = reload_gateway()
    assert gw.get_gateway_url() == "https://api.anthropic.com"

    monkeypatch.setenv("LLM_GATEWAY_URL", "https://llm-api.corp.com/Anthropic")
    assert gw.get_gateway_url() == "https://llm-api.corp.com/Anthropic"

    monkeypatch.setenv("LLM_GATEWAY_URL", "https://other-gateway.example.com")
    assert gw.get_gateway_url() == "https://other-gateway.example.com"


def test_gateway_headers_empty_when_no_config(monkeypatch):
    monkeypatch.delenv("GATEWAY_KEY_HEADER", raising=False)
    monkeypatch.delenv("GATEWAY_USER_FIELD", raising=False)
    monkeypatch.delenv("GATEWAY_USER_ID", raising=False)
    gw = reload_gateway()
    assert gw.gateway_headers("any-key") == {}


def test_gateway_headers_with_key_header(monkeypatch):
    monkeypatch.setenv("GATEWAY_KEY_HEADER", "Ocp-Apim-Subscription-Key")
    monkeypatch.delenv("GATEWAY_USER_FIELD", raising=False)
    monkeypatch.delenv("GATEWAY_USER_ID", raising=False)
    gw = reload_gateway()
    headers = gw.gateway_headers("my-key")
    assert headers["Ocp-Apim-Subscription-Key"] == "my-key"
    assert "user" not in headers


def test_gateway_headers_with_user_field(monkeypatch):
    monkeypatch.setenv("GATEWAY_KEY_HEADER", "Ocp-Apim-Subscription-Key")
    monkeypatch.setenv("GATEWAY_USER_FIELD", "user")
    monkeypatch.setenv("GATEWAY_USER_ID", "jdoe")
    gw = reload_gateway()
    headers = gw.gateway_headers("my-key")
    assert headers["Ocp-Apim-Subscription-Key"] == "my-key"
    assert headers["user"] == "jdoe"


def test_is_gateway_url_matches_configured(monkeypatch):
    monkeypatch.setenv("LLM_GATEWAY_URL", "https://llm-api.corp.com/Anthropic")
    gw = reload_gateway()
    assert gw.is_gateway_url("https://llm-api.corp.com/Anthropic") is True
    assert gw.is_gateway_url("https://api.anthropic.com") is False


def test_is_gateway_url_false_for_direct_anthropic(monkeypatch):
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    gw = reload_gateway()
    assert gw.is_gateway_url("https://api.anthropic.com") is False
