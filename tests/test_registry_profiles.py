import pytest

ANTHROPIC_PROFILE = {
    "id": "p-anth", "name": "Direct Anthropic", "type": "anthropic",
    "base_url": "https://api.anthropic.com", "api_key": "sk-ant-test",
    "api_key_header": "x-api-key", "user_id": "",
    "models": ["claude-opus-4-5", "claude-sonnet-4-5"], "active_model": "claude-sonnet-4-5",
}

GATEWAY_PROFILE = {
    "id": "p-gw", "name": "Work Gateway", "type": "gateway",
    "base_url": "https://llm-api.company.com/Unified", "api_key": "gwkey",
    "api_key_header": "Ocp-Apim-Subscription-Key", "user_id": "jsmith",
    "models": ["Claude-Sonnet-4.6", "GPT-4o"], "active_model": "Claude-Sonnet-4.6",
}


def test_load_profile_sets_active_model():
    import web.llm.registry as reg
    reg.load_profile(GATEWAY_PROFILE)
    assert reg.get_active_model() == "Claude-Sonnet-4.6"
    assert "GPT-4o" in reg.available_models()


def test_load_profile_anthropic_dispatches_anthropic_provider():
    import web.llm.registry as reg
    reg.load_profile(ANTHROPIC_PROFILE)
    from web.llm.anthropic_provider import AnthropicProvider
    provider = reg.get_provider()
    assert isinstance(provider, AnthropicProvider)


def test_load_profile_gateway_dispatches_openai_provider():
    import web.llm.registry as reg
    reg.load_profile(GATEWAY_PROFILE)
    from web.llm.openai_provider import OpenAIProvider
    provider = reg.get_provider()
    assert isinstance(provider, OpenAIProvider)


def test_get_active_profile_returns_loaded_profile():
    import web.llm.registry as reg
    reg.load_profile(GATEWAY_PROFILE)
    p = reg.get_active_profile()
    assert p["id"] == "p-gw"


def test_set_active_model_validates_against_profile_models():
    import web.llm.registry as reg
    reg.load_profile(GATEWAY_PROFILE)
    reg.set_active_model("GPT-4o")
    assert reg.get_active_model() == "GPT-4o"
    with pytest.raises(ValueError):
        reg.set_active_model("nonexistent-model")


def test_load_profile_evicts_provider_cache():
    import web.llm.registry as reg
    reg.load_profile(GATEWAY_PROFILE)
    p1 = reg.get_provider()
    # Loading a new profile must clear the cache — next get_provider returns a fresh instance
    reg.load_profile(ANTHROPIC_PROFILE)
    p2 = reg.get_provider()
    assert p1 is not p2
