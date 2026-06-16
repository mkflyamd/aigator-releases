"""PKCE helpers (RFC 7636) — verifier, S256 challenge, and state token."""
from __future__ import annotations

import base64
import hashlib
import secrets


def make_verifier() -> str:
    return secrets.token_urlsafe(64)


def make_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def make_state() -> str:
    return secrets.token_urlsafe(32)
