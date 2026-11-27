"""Who is using AI Gator: the Microsoft account email from the stored Graph token."""

import base64
import json

import secure_store


def _claims(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def email_from_token(token: str) -> str:
    claims = _claims(token or "")
    email = claims.get("upn") or claims.get("preferred_username") or claims.get("email") or ""
    return email.lower() if "@" in email else ""


def get_identity() -> dict | None:
    token = (secure_store.get_json("graph/token") or {}).get("access_token", "")
    email = email_from_token(token)
    if not email:
        return None
    claims = _claims(token)
    return {"id": email, "name": claims.get("name", "")}
