import pytest
from extensions.registry import get_adapter, KNOWN_TYPES
from extensions.base import ExtensionAdapter


def test_get_adapter_returns_mcp_adapter():
    adapter = get_adapter("mcp")
    assert isinstance(adapter, ExtensionAdapter)
    assert adapter.extension_type == "mcp"
    # Adapter methods are now implemented (Task 2); verify they return correct types
    assert isinstance(adapter.normalize("https://example.com/mcp"), dict)
    assert isinstance(adapter.prefill_from_url("https://example.com/mcp"), dict)


def test_get_adapter_unknown_type_raises():
    with pytest.raises(KeyError):
        get_adapter("not-a-real-type")


def test_known_types_contains_mcp():
    assert "mcp" in KNOWN_TYPES
