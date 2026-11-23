"""Google Workspace account handling shared by config, MCP dispatch and chat."""
from __future__ import annotations

import json
import os
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_REDIRECT_URI = "http://localhost:8080/oauth2callback"


class GoogleAccountError(Exception):
    """No Google account can be chosen for a tool call."""


def normalize_accounts(raw) -> list[str]:
    out: list[str] = []
    for item in raw or []:
        email = str(item or "").strip().lower()
        if email and email not in out:
            out.append(email)
    return out


def is_valid_email(value: str) -> bool:
    return bool(_EMAIL_RE.match(value or ""))


def configured_accounts(cfg: dict) -> list[str]:
    if "google_accounts" in cfg:
        return normalize_accounts(cfg.get("google_accounts"))
    return normalize_accounts([cfg.get("google_user_email")])


def credentials_dir() -> pathlib.Path:
    override = os.environ.get("WORKSPACE_MCP_CREDENTIALS_DIR") or os.environ.get("GOOGLE_MCP_CREDENTIALS_DIR")
    if override:
        return pathlib.Path(override)
    return pathlib.Path.home() / ".google_workspace_mcp" / "credentials"


def signed_in_accounts() -> list[str]:
    directory = credentials_dir()
    if not directory.is_dir():
        return []
    return sorted(p.stem.lower() for p in directory.glob("*.json"))


def resolve_google_account(requested: str | None, accounts: list[str], signed_in: list[str]) -> str:
    if accounts:
        wanted = (requested or "").strip().lower()
        return wanted if wanted in accounts else accounts[0]
    if len(signed_in) == 1:
        return signed_in[0]
    raise GoogleAccountError(
        "No Google account is set. Add your Google email in Settings → Google Workspace."
    )


def resolve_google_account_for_call(requested: str | None) -> str:
    from config import load_config

    accounts = configured_accounts(load_config())
    return resolve_google_account(requested, accounts, [] if accounts else signed_in_accounts())


def _post_token(data: dict, timeout: float) -> tuple[int, dict]:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(_TOKEN_URL, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read() or b"{}")
        except ValueError:
            payload = {}
        return exc.code, payload


def probe_google_client(client_id: str, client_secret: str, timeout: float = 5.0) -> str:
    """Post a dummy code: invalid_client means a wrong id/secret, invalid_grant means they are valid."""
    try:
        _status, payload = _post_token(
            {
                "grant_type": "authorization_code",
                "code": "aigator-probe",
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": _REDIRECT_URI,
            },
            timeout,
        )
    except Exception:
        return "unknown"
    return "invalid_client" if payload.get("error") == "invalid_client" else "ok"
