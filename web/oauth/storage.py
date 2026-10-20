"""Per-provider OAuth storage — provider config + token cache, DPAPI-encrypted via
secure_store under the name ``oauth/<provider_id>``."""

from __future__ import annotations

import re
import threading

import secure_store

# Reentrant — update_token holds the lock while calling save() which re-enters.
_LOCK = threading.RLock()
_SAFE_ID = re.compile(r"^[a-zA-Z0-9_\-]+$")


def _name_for(provider_id: str) -> str:
    if not _SAFE_ID.match(provider_id):
        raise ValueError(f"invalid provider id: {provider_id!r}")
    return f"oauth/{provider_id}"


def load(provider_id: str) -> dict:
    return secure_store.get_json(_name_for(provider_id)) or {}


def save(provider_id: str, data: dict) -> None:
    name = _name_for(provider_id)
    with _LOCK:
        # Preserve an existing token unless the caller explicitly provided one.
        # Re-registering a provider (DCR / BYOC / start_flow) rewrites the record
        # with provider config but no token — without this, a valid token would
        # be silently wiped, forcing the user to re-authorize every time.
        if "token" not in data:
            existing = load(provider_id)
            if existing.get("token"):
                data = {**data, "token": existing["token"]}
        secure_store.set_json(name, data)


def delete(provider_id: str) -> None:
    secure_store.delete(_name_for(provider_id))


def update_token(provider_id: str, token: dict) -> None:
    """Merge a token block into the stored provider record under key 'token'."""
    with _LOCK:
        data = load(provider_id)
        data["token"] = token
        save(provider_id, data)
