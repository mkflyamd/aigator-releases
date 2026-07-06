"""OAuthProvider — config dataclass shared by static and DCR-based providers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class OAuthProvider:
    id: str                                # stable key, e.g. "mcp-atlassian" or "slack"
    mode: Literal["static", "dcr"]
    authorize_url: str                     # discovered for DCR
    token_url: str                         # discovered for DCR
    client_id: str                         # static config or DCR result
    client_secret: str = ""                # DCR may issue one
    scopes: list[str] = field(default_factory=list)
    redirect_uri: str = ""                 # filled at flow start once port is bound
    issuer: str = ""                       # informational
    registration_endpoint: str = ""        # DCR only
    extra_authorize_params: dict[str, str] = field(default_factory=dict)
    label: str = ""                        # human-readable display name
    resource: str = ""                     # RFC 8707 resource indicator (MCP server URL) — binds token audience

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "mode": self.mode,
            "authorize_url": self.authorize_url,
            "token_url": self.token_url,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scopes": list(self.scopes),
            "redirect_uri": self.redirect_uri,
            "issuer": self.issuer,
            "registration_endpoint": self.registration_endpoint,
            "extra_authorize_params": dict(self.extra_authorize_params),
            "label": self.label,
            "resource": self.resource,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OAuthProvider":
        return cls(
            id=d["id"],
            mode=d.get("mode", "static"),
            authorize_url=d.get("authorize_url", ""),
            token_url=d.get("token_url", ""),
            client_id=d.get("client_id", ""),
            client_secret=d.get("client_secret", ""),
            scopes=list(d.get("scopes", [])),
            redirect_uri=d.get("redirect_uri", ""),
            issuer=d.get("issuer", ""),
            registration_endpoint=d.get("registration_endpoint", ""),
            extra_authorize_params=dict(d.get("extra_authorize_params", {})),
            label=d.get("label", ""),
            resource=d.get("resource", ""),
        )
