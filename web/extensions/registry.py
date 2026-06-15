"""Maps extension_type -> adapter instance. Populated at import."""
from .base import ExtensionAdapter
from .mcp_adapter import MCPAdapter

_REGISTRY: dict[str, ExtensionAdapter] = {"mcp": MCPAdapter()}
KNOWN_TYPES = frozenset(_REGISTRY.keys())


def get_adapter(extension_type: str) -> ExtensionAdapter:
    if extension_type not in _REGISTRY:
        raise KeyError(f"Unknown extension type: {extension_type!r}")
    return _REGISTRY[extension_type]
