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
    global _gc_instance
    if _gc_instance is None:
        _gc_instance = GraphClient()
    return _gc_instance


def reset_graph_client() -> None:
    """Invalidate the cached singleton so the next get_graph_client() call
    constructs a fresh GraphClient that reads the newly written token.json.
    Call this after a successful complete_auth() to pick up the new token."""
    global _gc_instance
    _gc_instance = None


_skill_client_class_cache: dict = {}


def get_skill_client(skills_dir: Path):
    """Load a skill-specific GraphClient from its scripts directory (class cached per dir)."""
    key = str(skills_dir)
    if key not in _skill_client_class_cache:
        spec = importlib.util.spec_from_file_location(
            f"graph_client_{skills_dir.name}", str(skills_dir / "graph_client.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _skill_client_class_cache[key] = mod.GraphClient
    return _skill_client_class_cache[key]()


_teams_token_warned = False


def get_teams_token() -> str:
    """Return a Skype-compatible token for Teams/AMS CDN requests.

    Priority:
      1. Browser-extracted teams_token.json (highest fidelity, captures the
         exact token the Teams web app uses — best for image CDN access).
      2. FOCI-derived skype_token.json (written by read_chats.py's FOCI swap;
         valid Skype token, works for asm.skype.com image fetches).
      3. Graph OAuth Bearer token (fallback — works for Graph CDN endpoints
         but NOT for asm.skype.com, which requires a Skype token header).
    """
    global _teams_token_warned
    import time as _t

    _log = logging.getLogger("graph_client")
    cfg_dir = Path.home() / ".config" / "microsoft-graph"

    # 1. Browser-extracted token
    teams_file = cfg_dir / "teams_token.json"
    if teams_file.exists():
        try:
            d = json.loads(teams_file.read_text())
            token = d.get("access_token", "")
            expires_at = d.get("expires_at", 0)
            if token and _t.time() < expires_at:
                _teams_token_warned = False
                return token
            if token and not _teams_token_warned:
                _log.warning(
                    "Teams browser token expired (expires_at=%s, now=%s) "
                    "— checking FOCI skype_token next",
                    expires_at,
                    int(_t.time()),
                )
                _teams_token_warned = True
        except Exception as ex:
            _log.warning("Failed to read teams_token.json: %s", ex)

    # 2. FOCI-derived Skype token (written by read_chats.py after token swap).
    # This is a genuine Skype token — required for asm.skype.com image CDN
    # requests, where a Graph Bearer token returns 401. get_teams_token() was
    # previously unaware of this file, so image fetches always fell through to
    # the Graph token and 401'd on AMS-hosted Teams images.
    skype_file = cfg_dir / "skype_token.json"
    if skype_file.exists():
        try:
            d = json.loads(skype_file.read_text())
            token = d.get("skype_token", "")
            expires_at = d.get("expires_at", 0)
            if token and _t.time() < expires_at:
                return token
        except Exception as ex:
            _log.warning("Failed to read skype_token.json: %s", ex)

    # 3. Graph OAuth Bearer — works for graph.microsoft.com CDN but not AMS.
    return GraphClient().get_token()


def _get_graph_compatible_teams_token() -> str:
    """Return a Graph-audience token for building a Teams GraphClient.

    This is deliberately NOT get_teams_token(): that function's priority 2
    (skype_token.json, the FOCI-derived Skype token) has audience
    api.spaces.skype.com -- correct for asm.skype.com CDN requests, but
    Microsoft Graph (graph.microsoft.com) rejects it outright with
    401 "Issuer claim is malformed", since it isn't a Graph-scoped token at
    all. make_teams_gc() builds a GraphClient used for real Graph calls
    (/me, /users, /chats, ...), so it must never pick up that tier.

    Bug this fixes: get_teams_token() gained the skype_token.json tier to
    fix AMS image-CDN 401s (see get_teams_token's docstring), but
    make_teams_gc() reused that same function for its access token. When
    teams_token.json is absent/expired and skype_token.json is present and
    valid (a common combination -- skype_token.json is written on every
    Teams chat read via the FOCI swap, teams_token.json only when the
    browser extension captures one), every Graph call made through
    make_teams_gc() (e.g. tp_teams_new_chat's /me and /users lookups when
    starting a message to someone with no existing chat_id) started
    failing with that same "Issuer claim is malformed" 401 -- even though
    the recipient may be an existing, previously-messaged contact, because
    the failure is keyed on whether chat_id was already known at draft time,
    not on recipient history.

    Priority (mirrors get_teams_token()'s tiers 1 and 3, skipping tier 2):
      1. Browser-extracted teams_token.json, if not expired.
      2. Graph OAuth Bearer via GraphClient().get_token().
    """
    import time as _t

    _log = logging.getLogger("graph_client")
    cfg_dir = Path.home() / ".config" / "microsoft-graph"

    teams_file = cfg_dir / "teams_token.json"
    if teams_file.exists():
        try:
            d = json.loads(teams_file.read_text())
            token = d.get("access_token", "")
            expires_at = d.get("expires_at", 0)
            if token and _t.time() < expires_at:
                return token
        except Exception as ex:
            _log.warning("Failed to read teams_token.json: %s", ex)

    return GraphClient().get_token()


_teams_gc_instance: object | None = None
_teams_gc_token: str | None = None


def make_teams_gc():
    """GraphClient pre-loaded with a Graph-audience-safe Teams token (cached,
    refreshed on token change).

    Uses _get_graph_compatible_teams_token(), NOT get_teams_token() -- see
    that function's docstring for why: this GraphClient is used for real
    Microsoft Graph calls, which reject the Skype-audience token that
    get_teams_token() can return for AMS CDN image fetches.
    """
    global _teams_gc_instance, _teams_gc_token
    token = _get_graph_compatible_teams_token()
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
    if (
        _me_cache["data"]
        and _me_cache["token"] == token
        and now - _me_cache["ts"] < _ME_CACHE_TTL
    ):
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
    """Convert HTML to readable plain text, preserving links and paragraph breaks.

    Links become [text](url) so the LLM can see and use the actual URLs.
    Inline images (data: URIs and tracking pixels <=1px) are suppressed;
    meaningful images become [image: alt](src).
    """
    # Preserve links: <a href="url">text</a> -> [text](url)
    def _link(m):
        href = re.search(r'href=["\']([^"\']*)["\']', m.group(1), re.IGNORECASE)
        url = _html.unescape(href.group(1)) if href else ""
        inner = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if not url or url.startswith("mailto:") or not inner:
            return inner
        if inner == url:
            return url
        return f"[{inner}]({url})"

    text = re.sub(
        r"<a\b([^>]*)>(.*?)</a>",
        _link,
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Teams AMSImage: <img itemtype="http://schema.skype.com/AMSImage" src="" itemid="<id>">
    # src is always empty; the real URL must be constructed from itemid.
    # Use "[image: Teams attachment](url)" not "[image](url)" so the
    # fetch_image skill's ACTIVATES_ON pattern ('[image:') fires and the LLM
    # is given the fetch_image tool for the next turn instead of falling back
    # to run_python (which has no auth tokens for the AMS CDN).
    def _ams_img(m):
        attrs = m.group(1)
        iid_m = re.search(r'itemid=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        if not iid_m:
            return "[image: Teams attachment]"
        obj_id = iid_m.group(1)
        # imgpsh_fullsize_anim is the full-resolution PNG the Teams app loads.
        # imgo is a small JPEG thumbnail (~20 KB) — too low-res to read text.
        url = f"https://us-api.asm.skype.com/v1/objects/{obj_id}/views/imgpsh_fullsize_anim"
        return f"[image: Teams attachment]({url})"

    text = re.sub(
        r'<img\b([^>]*itemtype=["\']http://schema\.skype\.com/AMSImage["\'][^>]*)>',
        _ams_img,
        text,
        flags=re.IGNORECASE,
    )

    # Preserve meaningful images: skip data: URIs and tracking pixels
    def _img(m):
        attrs = m.group(1)
        src_m = re.search(r'src=["\']([^"\']*)["\']', attrs, re.IGNORECASE)
        # Fall back to data-teams-src when src is blanked by the Teams proxy rewrite
        dts_m = re.search(r'data-teams-src=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        alt_m = re.search(r'alt=["\']([^"\']*)["\']', attrs, re.IGNORECASE)
        w_m = re.search(r'width=["\']?(\d+)', attrs, re.IGNORECASE)
        h_m = re.search(r'height=["\']?(\d+)', attrs, re.IGNORECASE)
        src = (src_m.group(1) if src_m else "") or (dts_m.group(1) if dts_m else "")
        alt = alt_m.group(1).strip() if alt_m else ""
        w = int(w_m.group(1)) if w_m else None
        h = int(h_m.group(1)) if h_m else None
        # Suppress data: URIs and tracking pixels (any declared dimension <= 1)
        _is_tiny = (w is not None and w <= 1) or (h is not None and h <= 1)
        if src.startswith("data:") or _is_tiny:
            return ""
        # cid: is an email inline reference — not a fetchable URL; emit label only
        if src.startswith("cid:") or not src:
            return f"[image: {alt}]" if alt else ""
        # Always include ': ' after 'image' so the fetch_image skill's
        # ACTIVATES_ON pattern ('[image:') fires even when alt text is absent.
        label = f"image: {alt}" if alt else "image:"
        return f"[{label}]({src})"

    text = re.sub(r"<img\b([^>]*)>", _img, text, flags=re.IGNORECASE)

    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>|</div>|</tr>|</li>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\u00a0", " ")
    text = _html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    return text[:max_len] if max_len else text
