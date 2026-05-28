"""Shared Microsoft 365 helpers — GraphClient, token management, HTML conversion."""
import html as _html
import json
import logging
import os
import re
import sys
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SKILLS_DIR = Path(__file__).parent.parent  # web/skills/_m365 -> web/skills

# ── GraphClient import ──────────────────────────────────────────────
# The canonical GraphClient lives in web/skills/m365-email/graph_client.py
# We load it dynamically to avoid sys.path pollution.
def _load_graph_client_class():
    gc_path = _SKILLS_DIR / "m365-email" / "graph_client.py"
    spec = importlib.util.spec_from_file_location("graph_client", str(gc_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.GraphClient

GraphClient = _load_graph_client_class()


_gc_instance: object | None = None
_gc_token: str | None = None

def get_graph_client():
    """Return a cached GraphClient using the M365 OAuth token."""
    global _gc_instance, _gc_token
    if _gc_instance is not None:
        # Refresh token if needed (get_token handles expiry check)
        _gc_instance.get_token()
        return _gc_instance
    _gc_instance = GraphClient()
    return _gc_instance


def get_skill_client(skills_dir: Path):
    """Load a skill-specific GraphClient from its scripts directory."""
    spec = importlib.util.spec_from_file_location("graph_client_skill", str(skills_dir / "graph_client.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.GraphClient()


_teams_token_warned = False

def get_teams_token() -> str:
    """Return access token for Teams — browser token file takes priority over OAuth token."""
    global _teams_token_warned
    import time as _t
    _log = logging.getLogger("graph_client")
    teams_file = Path.home() / ".config" / "microsoft-graph" / "teams_token.json"
    if teams_file.exists():
        try:
            d = json.loads(teams_file.read_text())
            token = d.get("access_token", "")
            expires_at = d.get("expires_at", 0)
            if token and _t.time() < expires_at:
                _teams_token_warned = False
                return token
            if token and not _teams_token_warned:
                _log.warning("Teams browser token expired (expires_at=%s, now=%s) "
                             "— falling back to OAuth token", expires_at, int(_t.time()))
                _teams_token_warned = True
        except Exception as ex:
            _log.warning("Failed to read teams_token.json: %s", ex)
    return GraphClient().get_token()


_teams_gc_instance: object | None = None
_teams_gc_token: str | None = None

def make_teams_gc():
    """GraphClient pre-loaded with the Teams-specific token (cached, refreshed on token change)."""
    global _teams_gc_instance, _teams_gc_token
    token = get_teams_token()
    if _teams_gc_instance is not None and _teams_gc_token == token:
        return _teams_gc_instance
    gc = GraphClient()
    if token:
        gc._access_token = token
        gc._expires_at = float("inf")
    _teams_gc_instance = gc
    _teams_gc_token = token
    return gc


def get_cal_client():
    """Return a calendar-specific GraphClient."""
    cal_dir = _SKILLS_DIR / "m365-calendar" / "scripts"
    return get_skill_client(cal_dir)


import time as _time

_me_cache: dict = {"data": None, "token": None, "ts": 0}
_ME_CACHE_TTL = 300  # 5 minutes

def get_cached_me(gc) -> dict:
    """Return cached /me profile (id, displayName, mail), invalidating on token change or TTL expiry."""
    token = getattr(gc, "_access_token", None)
    now = _time.time()
    if (_me_cache["data"]
            and _me_cache["token"] == token
            and now - _me_cache["ts"] < _ME_CACHE_TTL):
        return _me_cache["data"]
    me = gc.get("/me", {"$select": "id,displayName,mail,userPrincipalName"})
    _me_cache["data"] = me
    _me_cache["token"] = token
    _me_cache["ts"] = now
    return me


def get_current_user_display_name(gc) -> str:
    """Return the signed-in user's display name (cached)."""
    return get_cached_me(gc).get("displayName", "")


def html_to_text(html: str, max_len: int = 0) -> str:
    """Convert HTML to readable plain text, preserving paragraph/line breaks."""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</p>|</div>|</tr>|</li>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\u00a0", " ")
    text = _html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    return text[:max_len] if max_len else text
