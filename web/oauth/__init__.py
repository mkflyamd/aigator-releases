"""Generic OAuth 2.1 module — supports static client registration and Dynamic
Client Registration (RFC 7591). Used by MCP connections that require OAuth.

Public API:
    OAuthProvider              — provider config dataclass
    start_flow(provider)       — begin OAuth: returns {authorize_url, state, provider_id}
    get_access_token(prov_id)  — fetch a valid token (refresh if needed)
    discover_and_register(url) — DCR helper: returns OAuthProvider for an MCP URL
    is_authorized(prov_id)     — True if a valid (or refreshable) token exists
    forget(prov_id)            — wipe stored credentials and token
"""

from .provider import OAuthProvider
from .flow import start_flow, get_access_token, is_authorized, forget, poll, handle_callback, CALLBACK_URI
from .dcr import discover_and_register, register_byoc_provider

__all__ = [
    "OAuthProvider",
    "start_flow",
    "get_access_token",
    "is_authorized",
    "forget",
    "poll",
    "discover_and_register",
    "register_byoc_provider",
]
