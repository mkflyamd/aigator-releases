"""Teams route group — extracted from app.py."""
# reload-trigger
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict as _OD

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import shared

router = APIRouter()


def _is_skype_auth_error(exc: Exception) -> bool:
    """True when a Skype/chatsvc failure is an auth problem (expired/not-yet-minted
    Skype token) rather than a real server error. Skype returns HTTP 401 with a
    JSON body carrying errorCode 911 ("Authentication failed"). It reaches us as a
    urllib HTTPError or a wrapped message, so match on status code + the 911 marker."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code in (401, 403):
        return True
    msg = str(exc).lower()
    return ("911" in msg and "authentication failed" in msg) or "authentication failed" in msg


# ---------------------------------------------------------------------------
# FOCI/Skype module loader (cached after first load)
# ---------------------------------------------------------------------------

_skype_rc = None

def _get_skype_module():
    global _skype_rc
    if _skype_rc is not None:
        return _skype_rc
    import importlib.util
    from pathlib import Path as _Path
    _rc_path = _Path(__file__).parent.parent / "skills" / "m365-teams" / "scripts" / "read_chats.py"
    _spec = importlib.util.spec_from_file_location("_teams_read_chats", str(_rc_path))
    _rc = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_rc)
    _skype_rc = _rc
    return _rc


def _get_my_name() -> str:
    """Return the current user's display name, decoded from the Graph JWT 'name' claim.

    Used to fix quoted-reply previews: chatsvc embeds the literal placeholder
    "Display Name" inside <strong itemprop="mri"> for the current user and
    expects the client to resolve it. See issue #48.
    """
    from pathlib import Path as _Path
    token_file = _Path.home() / ".config" / "microsoft-graph" / "token.json"
    try:
        data = json.loads(token_file.read_text())
        access_token = data.get("access_token", "")
        if access_token:
            payload = access_token.split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            claims = json.loads(__import__("base64").b64decode(payload))
            return claims.get("name") or claims.get("preferred_username") or ""
    except Exception:
        pass
    return ""


_BARE_URL_RE = re.compile(r'(https?://[^\s<>"\')\]]+)')
_GUID_NAME_RE = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')

_PRESENCE_TOKEN_CACHE: dict = {}  # {token, expires_at}
_PRESENCE_AVAILABILITIES = {"Available", "Busy", "DoNotDisturb", "BeRightBack", "Away", "Offline"}
# activity must accompany availability — native Teams always sends both.
# Without the matching activity, UPS ignores the Offline value and reverts to Available.
_PRESENCE_ACTIVITY = {
    "Available": "Available", "Busy": "Busy", "DoNotDisturb": "DoNotDisturb",
    "BeRightBack": "BeRightBack", "Away": "Away", "Offline": "OffWork",
}


def _get_presence_token() -> str:
    """FOCI-swap the refresh token for a presence.teams.microsoft.com bearer token."""
    import time as _time
    cached = _PRESENCE_TOKEN_CACHE
    if cached.get("token") and _time.time() < cached.get("expires_at", 0) - 60:
        return cached["token"]
    _rc = _get_skype_module()
    tok = _rc._load_graph_tokens()
    refresh = tok.get("refresh_token", "")
    tid = tok.get("tenant_id", "organizations")
    CLIENT_ID = "1fec8e78-bce4-4aaf-ab1b-5451cc387264"
    data = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "scope": "https://presence.teams.microsoft.com/.default",
    }).encode()
    req = urllib.request.Request(
        f"https://login.microsoftonline.com/{tid}/oauth2/v2.0/token",
        data=data, method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        d = json.loads(resp.read())
    token = d["access_token"]
    cached["token"] = token
    cached["expires_at"] = _time.time() + d.get("expires_in", 3600)
    return token


def _fetch_presence(mris: list[str]) -> dict[str, dict]:
    """Batch-fetch Teams presence for a list of MRIs via the UPS getpresence endpoint.

    Returns {mri: {availability, activity, note}}. The UPS endpoint accepts an array
    of {mri, source} entries and returns one presence record per entry.
    """
    if not mris:
        return {}
    token = _get_presence_token()
    payload = [{"mri": m, "source": "ups"} for m in mris]
    req = urllib.request.Request(
        "https://teams.microsoft.com/ups/noam/v1/presence/getpresence/",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        d = json.loads(resp.read())
    out: dict[str, dict] = {}
    for entry in (d or []):
        mri = entry.get("mri", "")
        p = entry.get("presence", {}) or {}
        if mri:
            out[mri] = {
                "availability": p.get("availability", "Unknown"),
                "activity": p.get("activity", ""),
                "note": (p.get("note") or {}).get("message", ""),
            }
    return out


@router.get("/api/teams/presence")
async def tp_get_presence():
    """Get current user's Teams presence via UPS endpoint."""
    try:
        my_mri = _get_my_mri()
        result = _fetch_presence([my_mri])
        p = result.get(my_mri, {})
        return {
            "availability": p.get("availability", "Unknown"),
            "activity": p.get("activity", ""),
            "note": p.get("note", ""),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class PresenceBatchRequest(BaseModel):
    mris: list[str]


@router.post("/api/teams/presence/batch")
async def tp_get_presence_batch(req: PresenceBatchRequest):
    """Batch-fetch presence for other users' MRIs. Returns {mri: {availability,...}}."""
    try:
        # De-dup and cap to keep the UPS payload bounded
        unique = list(dict.fromkeys(m for m in req.mris if m))[:100]
        return {"presence": _fetch_presence(unique)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class PresenceSetRequest(BaseModel):
    availability: str


@router.post("/api/teams/presence")
async def tp_set_presence(req: PresenceSetRequest):
    """Set current user's Teams presence via UPS forceavailability endpoint."""
    if req.availability not in _PRESENCE_AVAILABILITIES:
        raise HTTPException(status_code=400, detail=f"Invalid availability: {req.availability}")
    try:
        token = _get_presence_token()
        body = {"availability": req.availability, "activity": _PRESENCE_ACTIVITY.get(req.availability, req.availability)}
        r = urllib.request.Request(
            "https://teams.microsoft.com/ups/noam/v1/me/forceavailability/",
            data=json.dumps(body).encode(),
            method="PUT",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(r, timeout=10) as resp:
            resp.read()
        return {"ok": True, "availability": req.availability}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _linkify_content(content: str) -> str:
    """Wrap bare URLs in <a href> so native Teams renders them as clickable links (#133).

    Splits on ALL HTML tags so URLs inside attribute values (e.g.
    itemtype="http://schema.skype.com/Forward") are never touched — only text
    nodes between tags are linkified.
    """
    if not content or "http" not in content:
        return content
    # Split into alternating [text, tag, text, tag, ...] segments.
    # Odd indices are HTML tags (including their attributes) — leave untouched.
    # Even indices are text nodes — linkify bare URLs in these only.
    parts = re.split(r'(<[^>]+>)', content)
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 1:  # HTML tag — never modify
            result.append(part)
        else:
            result.append(_BARE_URL_RE.sub(r'<a href="\1">\1</a>', part))
    return ''.join(result)


def _skype_send_body(content: str, messagetype: str, imdisplayname: str = "") -> dict:
    """Build a Skype chatsvc message body. Setting imdisplayname is what makes
    the recipient see our display name instead of our raw AAD object id (#56)."""
    body: dict = {"content": content, "messagetype": messagetype, "contenttype": "text"}
    if imdisplayname:
        body["imdisplayname"] = imdisplayname
    return body


def _get_my_mri() -> str:
    """Return the current user's Skype MRI (8:orgid:{aad-oid}).

    Tries Graph JWT first (fast, no network). Falls back to the Skype
    /users/ME/profile endpoint so reactions work even when the Graph
    token file is missing or expired.
    """
    from pathlib import Path as _Path
    # Fast path: decode OID from cached Graph JWT (no network needed)
    token_file = _Path.home() / ".config" / "microsoft-graph" / "token.json"
    try:
        data = json.loads(token_file.read_text())
        access_token = data.get("access_token", "")
        if access_token:
            payload = access_token.split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            claims = json.loads(__import__("base64").b64decode(payload))
            oid = claims.get("oid", "")
            if oid:
                return f"8:orgid:{oid}"
            email = claims.get("unique_name") or claims.get("upn") or claims.get("email") or ""
            if email:
                return f"8:{email}"
    except Exception:
        pass
    # Fallback: ask Skype API for our own profile — works with FOCI token alone
    try:
        _rc = _get_skype_module()
        skype_token, messaging_service = _rc.get_auth()
        import urllib.request as _ur
        req = _ur.Request(
            f"{messaging_service}/users/ME/profile",
            headers={"X-Skypetoken": skype_token, "Accept": "application/json"},
        )
        with _ur.urlopen(req, timeout=10) as resp:
            profile = json.loads(resp.read())
        mri = profile.get("selfMRI") or profile.get("id") or ""
        return mri
    except Exception:
        return ""


def _extract_forward_context(props: dict) -> dict:
    """Extract forward navigation info from Skype message raw_properties.

    Returns dict with:
      forward_deeplink  — Teams URL for native fallback
      original_thread_id — source conversation ID
      original_message_id — source message ID (str)
    All empty strings if not a forwarded message.
    """
    empty = {"forward_deeplink": "", "original_thread_id": "", "original_message_id": ""}
    try:
        ctx = props.get("originalMessageContext")
        if not ctx:
            return empty
        if isinstance(ctx, str):
            ctx = json.loads(ctx)
        thread_id = ctx.get("originalThreadId", "")
        msg_id = str(ctx.get("messageId", ""))
        if not thread_id or not msg_id:
            return empty
        context = json.dumps({"contextType": ctx.get("threadType", "chat")})
        deeplink = (
            f"https://teams.microsoft.com/l/message/"
            f"{urllib.parse.quote(thread_id, safe='')}/"
            f"{msg_id}"
            f"?context={urllib.parse.quote(context)}"
            f"&isForwardDeeplink=true"
        )
        return {"forward_deeplink": deeplink, "original_thread_id": thread_id, "original_message_id": msg_id}
    except Exception:
        return empty


def _normalize_skype_messages(raw_msgs: list[dict], my_mri: str, my_name: str = "") -> list[dict]:
    """Convert Skype API messages to the frontend thread format."""
    # Build MRI→name lookup from senders in this thread (no extra API calls)
    mri_to_name: dict[str, str] = {}
    for m in raw_msgs:
        mri = m.get("from_mri", "")
        name = m.get("sender_name", "")
        if mri and name:
            mri_to_name[mri.lower()] = name
    # Seed the current user so quoted-reply previews of my own messages
    # resolve correctly (chatsvc leaves the literal "Display Name" placeholder
    # for the current user's MRI — see issue #48).
    if my_mri and my_name:
        mri_to_name[my_mri.lower()] = my_name

    def _resolve_mri(mri: str) -> str:
        name = mri_to_name.get(mri.lower(), "")
        if name:
            return name
        # Fallback: strip 8:orgid: prefix, return readable part
        parts = mri.split(":", 2)
        return parts[-1] if len(parts) > 1 else mri

    def _name_for_mri(mri: str) -> str:
        """Resolve an MRI to a display name using the thread map, with GUID fallback."""
        if not mri:
            return "Someone"
        n = mri_to_name.get(mri.lower(), "")
        if n:
            return n
        guid = mri.split(":")[-1]
        return _name_cache.get(guid, "") or "Someone"

    messages = []
    for m in raw_msgs:
        # System events (member add/remove, topic change) come pre-parsed from read_chats.
        # Carry the raw MRIs through — _resolve_system_event_names (post-pass with Graph
        # access) resolves them and builds system_text, since added members never sent a
        # message in this thread and so aren't in the sender-built name map.
        if m.get("message_type") == "systemEvent":
            # deleteMember (removed/left) intentionally not surfaced — can be sensitive
            if m.get("event") not in ("addMember", "topicUpdate"):
                continue
            messages.append({
                "id": m.get("id", ""),
                "message_type": "systemEvent",
                "event": m.get("event", ""),
                "initiator_mri": m.get("initiator_mri", ""),
                "target_mris": m.get("target_mris") or [],
                "value": m.get("value", ""),
                "system_text": "",  # filled by _resolve_system_event_names
                "created_at": m.get("time", ""),
                "is_mine": False,
                "sender_name": "",
                "body": "", "body_html": "", "reactions": [], "attachments": [],
            })
            continue
        # Skip Skype system event types that produce raw GUID/metadata blobs in the UI:
        # - ThreadActivity/* roster events, call control signals, etc.
        # - callStarted / callEnded are handled separately by URIObject detection below
        skype_msgtype = m.get("messagetype", "")
        if skype_msgtype.startswith("ThreadActivity/") or skype_msgtype in (
            "Event/Call", "Event/CallEnded", "Event/CallStarted",
        ):
            continue
        from_mri = m.get("from_mri", "")
        sender_name = m.get("sender_name", "") or from_mri.split(":")[-1]
        is_mine = bool(my_mri and from_mri and from_mri.lower() == my_mri.lower())
        content_html = m.get("content_html", "")
        mention_map: dict[str, str] = m.get("mention_map", {})
        # Skip messages whose content is raw call metadata JSON or SystemEvent XML
        # (callStarted/callEnded/roster blobs that render as GUID noise in the UI).
        # Check both content_html and raw content field.
        _raw_content = m.get("content", "") or ""
        _check_src = content_html or _raw_content
        # Skip raw call metadata JSON blobs — but NOT URIObject recording messages
        # (those have scopeId AND a <URIObject> or <a href>Play tag).
        _is_recording_blob = "URIObject" in _check_src or "<a " in _check_src or "Play" in _check_src
        if _check_src and not _is_recording_blob and (
            '"callId"' in _check_src or      # JSON metadata (quoted)
            "\\\"callId\\\"" in _check_src or  # JSON metadata (escaped)
            '"scopeId"' in _check_src or
            "\\\"scopeId\\\"" in _check_src or
            "callStarted" in _check_src or
            "callEnded" in _check_src or
            ("8:orgid:" in _check_src and "20448:orgid:" in _check_src)  # roster blob
        ) and "tp-recording-card" not in _check_src:
            continue
        if content_html and "<img" in content_html:
            import logging as _log
            _log.getLogger("teams.img").debug("RAW img HTML: %s", content_html[:2000])
        if content_html:
            # Repair forward/reply blockquotes whose itemtype was corrupted by a prior
            # _linkify_content bug. The corruption pattern in raw Skype storage is:
            #   <blockquote itemtype="&lt;a href=">http://schema.skype.com/Forward">&gt;
            # where the tag was split: itemtype closed early at the &lt; and the URL
            # leaked as visible text. Restore to:
            #   <blockquote itemtype="http://schema.skype.com/Forward">
            content_html = re.sub(
                r'(<blockquote\b[^>]*?)itemtype="&lt;a href=">'
                r'\s*(https?://schema\.skype\.com/[^"]+)"&gt;',
                r'\1itemtype="\2">',
                content_html,
            )
            # Normalize Skype mention spans → <at data-aad="..."> tags
            # Preserves AAD GUID so frontend can show person card on click
            def _mention_sub(match: re.Match) -> str:
                attrs, text = match.group(1), match.group(2)
                iid_m = re.search(r'itemid="(\d+)"', attrs)
                iid = iid_m.group(1) if iid_m else ""
                guid = mention_map.get(iid, "")
                data = f' data-aad="{guid}"' if guid else ""
                return f"<at{data}>{text}</at>"

            content_html = re.sub(
                r'<span([^>]*itemtype="http://schema\.skype\.com/Mention"[^>]*)>(.*?)</span>',
                _mention_sub,
                content_html,
            )
            # Also normalize raw <at id="8:orgid:{guid}"> tags (from our own sent messages)
            def _raw_at_sub(match: re.Match) -> str:
                guid = match.group(1)
                text = match.group(2)
                return f'<at data-aad="{guid}">{text}</at>'
            content_html = re.sub(
                r'<at\s+id="8:orgid:([0-9a-fA-F-]+)">(.*?)</at>',
                _raw_at_sub,
                content_html,
            )
            # Native Teams sends inline emojis as
            #   <img itemtype="http://schema.skype.com/Emoji" itemid="rofl"
            #        src="https://statics.teams.cdn.office.net/.../emoticons/.../20_f.png"
            #        alt="🤣" ...>
            # The CDN host isn't in our image-proxy allowlist, so the <img> would break
            # and the message renders as empty/plain text. Since the alt attribute already
            # holds the real Unicode char (which the browser renders natively, like the
            # rest of our emoji handling), just replace the whole tag with its alt char.
            def _emoji_img_sub(match: re.Match) -> str:
                tag = match.group(0)
                alt_m = re.search(r'\balt="([^"]*)"', tag)
                return alt_m.group(1) if alt_m and alt_m.group(1) else ""
            content_html = re.sub(
                r'<img\b[^>]*itemtype="http://schema\.skype\.com/Emoji"[^>]*/?>',
                _emoji_img_sub,
                content_html,
            )
            # Quoted-reply author resolution: <strong itemprop="mri" itemid="{MRI}">Display Name</strong>
            # chatsvc returns the literal placeholder "Display Name" for the current user's
            # MRI inside reply previews. Substitute with the resolved name when known.
            def _quote_author_sub(match: re.Match) -> str:
                full_attrs, text = match.group(1), match.group(2)
                mri_m = re.search(r'itemid="([^"]+)"', full_attrs)
                if not mri_m:
                    return match.group(0)
                resolved = mri_to_name.get(mri_m.group(1).lower(), "")
                return f"<strong{full_attrs}>{resolved or text}</strong>"
            content_html = re.sub(
                r'<strong((?=[^>]*itemprop="mri")[^>]*)>([^<]*)</strong>',
                _quote_author_sub,
                content_html,
            )
            content_html = re.sub(
                r'src="(https://(?:[^"]*\.teams\.microsoft\.com|[^"]*\.sfbassets\.com|[^"]*\.asm\.skype\.com|graph\.microsoft\.com)[^"]+)"',
                r'src="" data-teams-src="\1"',
                content_html,
            )
            # AMSImage inside forward blockquotes: src="" with itemid="<object-id>".
            # The URL was never in the src attribute — synthesize a proxy URL from itemid.
            def _ams_img_sub(match: re.Match) -> str:
                full = match.group(0)
                if 'data-teams-src=' in full or 'src="http' in full:
                    return full  # already handled
                iid_m = re.search(r'itemid="([^"]+)"', full)
                if not iid_m:
                    return full
                obj_id = iid_m.group(1)
                asm_url = f"https://us-api.asm.skype.com/v1/objects/{obj_id}/views/imgo"
                return full.replace('src=""', f'src="" data-teams-src="{asm_url}"', 1)
            content_html = re.sub(
                r'<img\b[^>]*itemtype="http://schema\.skype\.com/AMSImage"[^>]*/?>',
                _ams_img_sub,
                content_html,
            )
        # Rewrite CallRecording URIObject messages to a Play card with valid href (#105)
        if content_html and "URIObject" in content_html and "CallRecording" in content_html:
            import html as _html_skype
            rec_url_s, rec_title_s = _parse_recording_uri_object(content_html)
            if rec_url_s:
                content_html = (
                    f'<div class="tp-recording-card">'
                    f'&#128249; {_html_skype.escape(rec_title_s)}: '
                    f'<a href="{_html_skype.escape(rec_url_s)}" target="_blank" rel="noopener">Play recording</a>'
                    f'</div>'
                )
            else:
                # URIObject with no extractable URL (ChunkFinished/in-progress) — skip
                continue
        # Parse reactions: [{key, users:[{mri}]}] → [{type, user}]
        # Tag current user's reactions as "You" so the frontend can detect toggles.
        reactions = []
        for emotion in m.get("emotions_raw", []):
            rtype = emotion.get("key", "")
            for u in emotion.get("users", []):
                umri = u.get("mri", "")
                is_my_reaction = bool(my_mri and umri and umri.lower() == my_mri.lower())
                # Carry the raw MRI so _resolve_reaction_names can Graph-resolve reactors
                # who never sent a message in this window (absent from mri_to_name).
                reactions.append({
                    "type": rtype,
                    "user": "You" if is_my_reaction else _resolve_mri(umri),
                    "_mri": "" if is_my_reaction else umri,
                })

        created_at = m.get("time", "")
        last_modified = m.get("edit_time", "") or created_at
        messages.append({
            "id": m.get("id", ""),
            "sender_name": sender_name,
            "sender_id": from_mri,
            "is_mine": is_mine,
            "body": m.get("content", ""),
            "body_html": content_html,
            **_extract_forward_context(m.get("raw_properties", {})),
            "created_at": created_at,
            "last_modified_at": last_modified,
            "message_type": "message",
            "reactions": reactions,
            "attachments": [],
        })
    return messages


def _resolve_sender_guids(messages: list[dict]) -> None:
    """Resolve message sender_name when it is a raw GUID (Skype sometimes returns the
    AAD object ID as the imdisplayname for external/guest senders). Extracts the GUID
    from sender_id (MRI format '8:orgid:{guid}' or plain GUID), checks _name_cache,
    then falls back to Graph /users/{guid}."""
    unknown: dict[str, list[dict]] = {}  # guid → list of messages with that sender
    for msg in messages:
        name = msg.get("sender_name", "")
        if not name or not _GUID_NAME_RE.match(name.strip()):
            continue
        # Extract GUID from sender_id MRI or use sender_name directly as the GUID
        sid = msg.get("sender_id", "")
        guid = sid.split(":")[-1].lower() if sid else name.lower()
        if not guid:
            continue
        cached = _name_cache.get(guid)
        if cached and not _GUID_NAME_RE.match(cached):
            msg["sender_name"] = cached
        else:
            unknown.setdefault(guid, []).append(msg)
    if not unknown:
        return
    try:
        from skills._m365.helpers import make_teams_gc
        gc = make_teams_gc()
        for guid, msgs_with_guid in unknown.items():
            try:
                u = gc.get(f"/users/{guid}", {"$select": "displayName"})
                name = u.get("displayName", "")
                if name and not _GUID_NAME_RE.match(name):
                    _name_cache[guid] = name
                    for m in msgs_with_guid:
                        m["sender_name"] = name
            except Exception:
                pass
    except Exception:
        pass


def _resolve_quoted_guids(messages: list[dict]) -> None:
    """Backfill sender names in quoted-reply blockquotes where the MRI resolved to a GUID.

    Skype's <strong itemprop="mri" itemid="8:orgid:{guid}"> attribution uses the sender's
    MRI. _normalize_skype_messages only knows names of senders in the current fetch window.
    If the quoted author wasn't in that window, their name falls through to the raw GUID text.

    This helper:
    1. Scans body_html for any remaining GUID-shaped text inside itemprop="mri" strong tags.
    2. Tries _name_cache first (populated by prior lookups in this session).
    3. Falls back to Graph /users/{guid} for unknowns — at most one request per unique GUID.
    4. Rewrites body_html in-place and seeds _name_cache for future calls.
    """
    _GUID_RE = re.compile(
        r'<strong([^>]*itemprop="mri"[^>]*)>'
        r'([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})'
        r'</strong>',
    )
    # Collect unique GUIDs that appear as text inside itemprop="mri" strong tags
    unknown: set[str] = set()
    for msg in messages:
        html = msg.get("body_html", "")
        if html:
            for m in _GUID_RE.finditer(html):
                unknown.add(m.group(2).lower())
    if not unknown:
        return
    # Resolve via cache first, then Graph for the remainder
    resolved: dict[str, str] = {}
    still_unknown = set()
    for guid in unknown:
        name = _name_cache.get(guid) or _name_cache.get(f"8:orgid:{guid}")
        if name and not _GUID_NAME_RE.match(name):
            resolved[guid] = name
        else:
            still_unknown.add(guid)
    if still_unknown:
        try:
            from skills._m365.helpers import make_teams_gc
            gc = make_teams_gc()
            for guid in still_unknown:
                try:
                    u = gc.get(f"/users/{guid}", {"$select": "displayName"})
                    name = u.get("displayName", "")
                    if name and not _GUID_NAME_RE.match(name):
                        _name_cache[guid] = name
                        resolved[guid] = name
                except Exception:
                    pass
        except Exception:
            pass
    if not resolved:
        return
    # Rewrite body_html for all messages
    def _sub(m: re.Match) -> str:
        attrs, guid = m.group(1), m.group(2).lower()
        name = resolved.get(guid)
        return f"<strong{attrs}>{name}</strong>" if name else m.group(0)
    for msg in messages:
        if msg.get("body_html"):
            msg["body_html"] = _GUID_RE.sub(_sub, msg["body_html"])


def _resolve_system_event_names(messages: list[dict]) -> None:
    """Build system_text for systemEvent messages, resolving MRIs to display names.

    Added members never sent a message in this thread, so their MRI is absent from the
    sender-built name map. We resolve every event MRI here via _name_cache, then Graph
    /users/{guid} for the remainder — one request per unique unknown GUID.
    """
    sys_msgs = [m for m in messages if m.get("message_type") == "systemEvent"]
    if not sys_msgs:
        return

    def _guid(mri: str) -> str:
        return (mri or "").split(":")[-1].lower()

    # Collect unique GUIDs across all events
    guids: set[str] = set()
    for m in sys_msgs:
        for mri in [m.get("initiator_mri", "")] + (m.get("target_mris") or []):
            g = _guid(mri)
            if g:
                guids.add(g)

    resolved: dict[str, str] = {}
    still_unknown = set()
    for g in guids:
        name = _name_cache.get(g) or _name_cache.get(f"8:orgid:{g}")
        if name and not _GUID_NAME_RE.match(name):
            resolved[g] = name
        else:
            still_unknown.add(g)
    if still_unknown:
        try:
            from skills._m365.helpers import make_teams_gc
            gc = make_teams_gc()
            for g in still_unknown:
                try:
                    u = gc.get(f"/users/{g}", {"$select": "displayName"})
                    name = u.get("displayName", "")
                    if name and not _GUID_NAME_RE.match(name):
                        _name_cache[g] = name
                        resolved[g] = name
                except Exception:
                    pass
        except Exception:
            pass

    def _name(mri: str) -> str:
        return resolved.get(_guid(mri), "") or "Someone"

    for m in sys_msgs:
        ev = m.get("event", "")
        initiator = _name(m.get("initiator_mri", ""))
        targets = [_name(t) for t in (m.get("target_mris") or [])]
        targets_str = ", ".join(targets)
        if ev == "addMember":
            m["system_text"] = f"{initiator} added {targets_str} to the chat"
        elif ev == "topicUpdate":
            m["system_text"] = f"{initiator} changed the group name to \"{m.get('value','')}\""
        else:
            m["system_text"] = ""  # deleteMember intentionally not surfaced (sensitive)


def _resolve_reaction_names(messages: list[dict]) -> None:
    """Backfill reactor display names that fell back to a raw GUID.

    Reaction tooltips show who reacted, but a reactor who never SENT a message in the
    loaded window is absent from the sender-built name map, so their name renders as the
    raw AAD GUID. Collect those GUIDs, resolve via _name_cache then Graph /users/{guid}
    (one request per unique unknown), and rewrite the reaction 'user' field in place.
    """
    def _guid(mri: str) -> str:
        return (mri or "").split(":")[-1].lower()

    # Collect GUIDs from reactions whose displayed 'user' is still GUID-shaped
    unknown: set[str] = set()
    for msg in messages:
        for r in (msg.get("reactions") or []):
            if r.get("user") and _GUID_NAME_RE.match(r["user"]):
                g = _guid(r.get("_mri", ""))
                if g:
                    unknown.add(g)
    if not unknown:
        # still strip the internal _mri field before returning
        for msg in messages:
            for r in (msg.get("reactions") or []):
                r.pop("_mri", None)
        return

    resolved: dict[str, str] = {}
    still_unknown = set()
    for g in unknown:
        name = _name_cache.get(g) or _name_cache.get(f"8:orgid:{g}")
        if name and not _GUID_NAME_RE.match(name):
            resolved[g] = name
        else:
            still_unknown.add(g)
    if still_unknown:
        try:
            from skills._m365.helpers import make_teams_gc
            gc = make_teams_gc()
            for g in still_unknown:
                try:
                    u = gc.get(f"/users/{g}", {"$select": "displayName"})
                    name = u.get("displayName", "")
                    if name and not _GUID_NAME_RE.match(name):
                        _name_cache[g] = name
                        resolved[g] = name
                except Exception:
                    pass
        except Exception:
            pass

    for msg in messages:
        for r in (msg.get("reactions") or []):
            g = _guid(r.get("_mri", ""))
            if g and g in resolved:
                r["user"] = resolved[g]
            r.pop("_mri", None)  # never leak the internal field to the client


_graph_id_cache: dict[str, str] = {}  # skype_id → graph_id

def _resolve_to_graph_chat_id(skype_id: str, gc) -> str:
    """Resolve a Skype-format chat ID to a Graph chat ID.

    Skype API returns IDs like '19:xxx_yyy@unq.gbl.spaces' or '19:xxx@thread.skype'.
    Graph API rejects these — it needs IDs like '19:xxx@thread.v2'.
    Tries GET /chats/{id} directly (Graph accepts some Skype formats as path params).
    Returns the resolved Graph ID, or the original if resolution fails.
    """
    if "@unq.gbl.spaces" not in skype_id and "@thread.skype" not in skype_id:
        return skype_id  # already Graph-format
    if skype_id in _graph_id_cache:
        return _graph_id_cache[skype_id]
    try:
        # Graph can resolve Skype IDs via direct GET — no filter needed
        result = gc.get(f"/chats/{urllib.parse.quote(skype_id, safe='@:._-')}", params={"$select": "id"})
        graph_id = result.get("id", "")
        if graph_id:
            _graph_id_cache[skype_id] = graph_id
            return graph_id
    except Exception as e:
        print(f"[graph-id] resolve failed for {skype_id}: {e}", flush=True)
    return skype_id  # fallback — let Graph return its own error


def _normalize_skype_chats(convs: list[dict]) -> list[dict]:
    """Convert Skype API conversation objects to the third-pane response format."""
    from datetime import datetime, timezone

    # Build GUID → display name map from all senders and thread members.
    # This lets us resolve DM partner names without extra API calls.
    # Key: lowercase AAD GUID; value: display name
    _guid_to_name: dict[str, str] = {}
    for _c in convs:
        # From last_sender
        _sender_mri = _c.get("last_sender_mri", "")
        _sender_name = _c.get("last_sender", "")
        if _sender_name and _sender_mri:
            _guid = _sender_mri.split(":")[-1].lower()
            if _guid and "-" in _guid:
                _guid_to_name[_guid] = _sender_name
        # From thread_members (friendlyName field in threadProperties.members)
        for _m in (_c.get("thread_members") or []):
            _mri = _m.get("id", "") or _m.get("mri", "")
            _fname = _m.get("friendlyName", "") or _m.get("displayName", "")
            if _fname and _mri:
                _mguid = _mri.split(":")[-1].lower()
                if _mguid and "-" in _mguid:
                    _guid_to_name[_mguid] = _fname

    # Compute my AAD GUID once for DM resolution
    _my_guid = ""
    try:
        import base64 as _b64, json as _j
        from pathlib import Path as _P
        _tok = _j.loads((_P.home() / ".config" / "microsoft-graph" / "token.json").read_text())
        _payload = _tok.get("access_token", "").split(".")[1]
        _payload += "=" * (4 - len(_payload) % 4)
        _my_guid = _j.loads(_b64.b64decode(_payload)).get("oid", "").lower()
    except Exception:
        pass

    def _resolve_other_dm_name(conv: dict) -> str:
        """For a DM, return the OTHER person's display name (not the current user)."""
        # DM ID: 19:{guid_A}_{guid_B}@...  — one is mine, the other is the partner
        cid = conv.get("id", "")
        raw = cid.replace("19:", "").split("@")[0]
        parts = raw.split("_")
        if len(parts) != 2:
            return ""
        g0, g1 = parts[0].lower(), parts[1].lower()
        other_guid = g1 if g0 == _my_guid else g0
        # Look up from GUID→name map built from all conversation senders
        name = _guid_to_name.get(other_guid, "")
        if name:
            return name
        # Fallback: check addedBy — it's the other person if they initiated the chat
        added_mri = conv.get("added_by_mri", "")
        if added_mri:
            added_guid = added_mri.split(":")[-1].lower()
            if added_guid != _my_guid:
                name = _guid_to_name.get(added_guid, "")
                if name:
                    return name
        return ""

    def _parse_horizon_iso(horizon: str) -> str:
        """Convert consumptionhorizon first field (ms epoch) to ISO string."""
        if not horizon:
            return ""
        try:
            ms = int(horizon.split(";")[0])
            return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
        except Exception:
            return ""

    def _parse_iso(ts: str) -> datetime | None:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None

    _DM_ID_RE = re.compile(
        r"^19:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_"
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        re.IGNORECASE,
    )

    def _chat_type(conv: dict) -> str:
        tt = (conv.get("thread_type") or conv.get("type") or "").lower()
        cid = conv.get("id", "")
        if tt == "meeting" or "19:meeting_" in cid:
            return "meeting"
        # 1:1 DMs have IDs like 19:{guid}_{guid}@unq.gbl.spaces
        if _DM_ID_RE.match(cid):
            return "oneOnOne"
        # Two-person @thread.v2 chats (created via our chatsvc POST /threads fallback
        # when Chat.Create scope is unavailable) should surface as DMs, not groups.
        # A real group needs ≥3 members; member_count=2 with no explicit topic = DM.
        member_count = int(conv.get("member_count") or 0)
        topic = (conv.get("topic") or "").strip()
        if member_count == 2 and not topic:
            return "oneOnOne"
        # Named group chats (threadType=topic) and multi-person chats (threadType=chat, @thread.v2)
        if tt in ("chat", "topic", ""):
            return "group"
        return tt

    chats = []
    for conv in convs:
        cid = conv.get("id", "")
        tt = (conv.get("thread_type") or conv.get("type") or "").lower()

        # Skip system feeds and Teams Spaces (not chats), but keep 48:notes (self-chat)
        if tt == "space":
            continue
        if cid.startswith("48:") and cid != "48:notes":
            continue

        chat_type = "oneOnOne" if cid == "48:notes" else _chat_type(conv)

        last_time = conv.get("last_time", "")
        last_read_time = _parse_horizon_iso(conv.get("consumption_horizon", ""))

        last_dt = _parse_iso(last_time)
        read_dt = _parse_iso(last_read_time)

        # Normal unread: new message arrived after the last read horizon.
        unread_normal = bool(last_dt and read_dt and last_dt > read_dt)

        # Explicit mark-unread via consumptionHorizonBookmark.
        # Native Teams web (verified from live chatsvc captures) uses the bookmark's
        # FIRST field (readUntil ms) as the explicit-unread signal:
        #   mark-UNREAD -> bookmark "{msgTs};{now};{msgId}"  (readUntil > 0  = pinned unread)
        #   mark-READ   -> bookmark "0;{now};0"              (readUntil == 0 = cleared)
        # So a bookmark is an active unread pin iff its readUntil field is > 0.
        # This is exact — no time-gap heuristics.
        bookmark_read_until = 0
        try:
            _bm = conv.get("consumption_horizon_bookmark", "")
            if _bm:
                bookmark_read_until = int(_bm.split(";")[0])
        except Exception:
            bookmark_read_until = 0
        unread_bookmark = bookmark_read_until > 0

        unread = 1 if (unread_normal or unread_bookmark) else 0

        # Clean up topics that are roster dumps (raw MRI strings)
        raw_topic = conv.get("topic", "")
        if any(p in raw_topic for p in ("8:orgid:", "8:teamsvisitor:", "8:live:")):
            raw_topic = ""

        if cid == "48:notes":
            topic = "Notes to Self"
        elif chat_type == "oneOnOne":
            # For DMs, resolve the OTHER person's name.
            # Strategy: try _resolve_other_dm_name (uses last_sender GUID→name map),
            # then scan thread_members for the partner's friendlyName,
            # then fall back to raw_topic only if it differs from last_sender
            # (to avoid showing the current user's own name as the DM partner).
            resolved = _resolve_other_dm_name(conv)
            if not resolved:
                # Try thread_members — Skype may include partner's friendlyName here
                for _tm in (conv.get("thread_members") or []):
                    _tmri = _tm.get("id", "") or _tm.get("mri", "")
                    _tguid = _tmri.split(":")[-1].lower()
                    _tfname = _tm.get("friendlyName", "") or _tm.get("displayName", "")
                    if _tguid and _tguid != _my_guid and _tfname:
                        resolved = _tfname
                        _guid_to_name[_tguid] = _tfname  # seed for future lookups
                        break
            _last_sender_name = conv.get("last_sender", "")
            # Suppress raw_topic when it equals last_sender (= current user sent last message)
            _safe_topic = raw_topic if (raw_topic and raw_topic != _last_sender_name) else ""
            topic = resolved or _safe_topic or "Chat"
        elif raw_topic:
            topic = raw_topic
        elif chat_type == "meeting":
            topic = "Meeting"
        elif chat_type == "group":
            topic = "Group Chat"
        else:
            topic = conv.get("last_sender") or "Chat"

        # Strip GUID prefix from last_message (Skype API returns "guid: message text")
        _last_msg = conv.get("last_message", "")
        _last_sender = conv.get("last_sender", "")
        if _last_sender and re.match(r'^[0-9a-fA-F]{8}-', _last_sender):
            _last_sender = ""  # suppress GUID sender — frontend will show preview without prefix
        _guid_pfx = re.match(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}:\s*', _last_msg)
        if _guid_pfx:
            _last_msg = _last_msg[_guid_pfx.end():]

        # Collect member display names from thread_members for search matching.
        # In practice the Skype conversations list rarely includes friendlyName
        # for group members — it's mainly present for DMs. The full roster requires
        # a per-chat API call (_normalize_skype_chats_members) which is too slow for
        # search. This is a best-effort pass; last_sender is the more reliable signal.
        _member_names = []
        for _tm in (conv.get("thread_members") or []):
            _tmri = _tm.get("id", "") or _tm.get("mri", "")
            _tguid = _tmri.split(":")[-1].lower()
            _tfname = _tm.get("friendlyName", "") or _tm.get("displayName", "")
            if not _tfname and _tguid and "-" in _tguid:
                _tfname = _guid_to_name.get(_tguid, "")
            if _tfname:
                _member_names.append(_tfname)

        # For DMs, derive the peer's MRI from the chat id (19:{guidA}_{guidB}@...)
        # so the frontend can request presence for the other person.
        peer_mri = ""
        if chat_type == "oneOnOne" and cid != "48:notes":
            _raw = cid.replace("19:", "").split("@")[0]
            _parts = _raw.split("_")
            if len(_parts) == 2:
                _og = _parts[1].lower() if _parts[0].lower() == _my_guid else _parts[0].lower()
                if _og and _og != _my_guid:
                    peer_mri = f"8:orgid:{_og}"

        chats.append({
            "id": cid,
            "topic": topic,
            "last_message": _last_msg,
            "last_message_time": last_time,
            "last_sender": _last_sender,
            "last_read_time": last_read_time,
            "unread_count": unread,
            "chat_type": chat_type,
            "peer_mri": peer_mri,
            "member_emails": [],
            "members": [],
            "_member_names": _member_names,
        })

    chats.sort(key=lambda c: c.get("last_message_time") or "", reverse=True)
    return chats


# ---------------------------------------------------------------------------
# Helper: normalize Graph chat objects (kept for reference)
# ---------------------------------------------------------------------------

def _normalize_teams_chats(chats_raw: list[dict], me: dict, gc) -> tuple[list[dict], bool]:
    """Normalize raw Graph chat objects into the API response format.
    Returns (chats, has_viewpoint)."""
    from skills._m365.helpers import html_to_text
    me_id = me.get("id", "")
    me_display = me.get("displayName", "")
    me_parts = set(w.lower() for w in re.split(r'[,\s]+', me_display) if w)

    def _is_me(member):
        uid = member.get("userId", "")
        if uid and me_id and uid == me_id:
            return True
        name = member.get("displayName", "")
        if name and me_parts:
            parts = set(w.lower() for w in re.split(r'[,\s]+', name) if w)
            if parts == me_parts:
                return True
        return False

    _has_viewpoint = bool(chats_raw and "viewpoint" in chats_raw[0])
    chats = []
    for chat in chats_raw:
        cid = chat.get("id", "")
        members = chat.get("members", [])
        other_names = []
        for m in members:
            dn = m.get("displayName", "")
            if not dn or _is_me(m):
                continue
            if ", " in dn:
                parts = dn.split(", ", 1)
                dn = f"{parts[1]} {parts[0]}"
            other_names.append(dn)
        chat_type_raw = chat.get("chatType", "")
        _is_one_on_one = chat_type_raw == "oneOnOne"
        # For 1:1 DMs, prefer member names over raw topic — topic is often set to the
        # current user's own display name after they send a message.
        if other_names and _is_one_on_one:
            topic = other_names[0]
        elif chat.get("topic"):
            topic = chat["topic"]
        elif len(other_names) <= 2:
            topic = " · ".join(other_names) or "Chat"
        else:
            topic = f"{other_names[0]} · {other_names[1]} +{len(other_names) - 2}"

        preview = chat.get("lastMessagePreview") or {}
        last_body = html_to_text((preview.get("body") or {}).get("content", ""), max_len=80)
        last_sender = ((preview.get("from") or {}).get("user") or {}).get("displayName", "")
        last_time = preview.get("createdDateTime") or chat.get("lastUpdatedDateTime") or ""
        if last_time and not last_time.endswith("Z") and "+" not in last_time:
            last_time += "Z"

        viewpoint = chat.get("viewpoint") or {}
        last_read_time = viewpoint.get("lastMessageReadDateTime") or ""
        if last_time and last_read_time:
            unread = 1 if last_time > last_read_time else 0
        else:
            unread = 0

        member_emails = [
            m.get("email", "").lower() for m in members
            if m.get("email") and not _is_me(m)
        ]
        member_details = [
            {
                "name": m.get("displayName", ""),
                "email": (m.get("email") or "").lower(),
                "membership_id": m.get("id", ""),
                # MRI for Skype API remove: 8:orgid:{aad_object_id}
                "mri": f"8:orgid:{m['userId']}" if m.get("userId") else "",
            }
            for m in members
            if m.get("email") and not _is_me(m)
        ]
        chats.append({
            "id": cid,
            "topic": topic,
            "last_message": last_body,
            "last_message_time": last_time,
            "last_sender": last_sender,
            "last_read_time": last_read_time,
            "unread_count": unread,
            "chat_type": chat.get("chatType", ""),
            "member_emails": member_emails,
            "members": member_details,
        })
    chats.sort(key=lambda c: c.get("last_message_time") or "", reverse=True)
    return chats, _has_viewpoint


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

_name_cache: dict[str, str] = {}  # aad guid → display name, persists across requests


def _resolve_chat_names(chats: list[dict]) -> None:
    """Resolve display names for:
    - DMs: other person's name via Graph batch
    - Unnamed groups: member names via /v1/threads + Graph $filter
    """
    import base64 as _b64, json as _j
    from pathlib import Path as _P

    my_guid = ""
    try:
        tok = _j.loads((_P.home() / ".config" / "microsoft-graph" / "token.json").read_text())
        payload = tok.get("access_token", "").split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        my_guid = _j.loads(_b64.b64decode(payload)).get("oid", "").lower()
    except Exception:
        return

    try:
        from skills._m365.helpers import GraphClient
        gc = GraphClient()
        if not gc.get_token():
            return
    except Exception:
        return

    # ── 1. DMs: extract other person's GUID ──────────────────────────────────
    dm_unresolved: dict[str, list[int]] = {}  # guid → chat indices
    for i, chat in enumerate(chats):
        if chat.get("chat_type") != "oneOnOne":
            continue
        cid = chat.get("id", "")
        raw = cid.replace("19:", "").split("@")[0]
        parts = raw.split("_")
        if len(parts) != 2:
            continue
        g0, g1 = parts[0].lower(), parts[1].lower()
        other_guid = g1 if g0 == my_guid else g0
        if other_guid in _name_cache:
            chat["topic"] = _name_cache[other_guid]
            cached_email = _name_cache.get(f"email:{other_guid}", "")
            if cached_email:
                chat["other_email"] = cached_email
        else:
            dm_unresolved.setdefault(other_guid, []).append(i)

    # ── 2. Unnamed groups: fetch thread roster via Skype ─────────────────────
    group_guid_to_indices: dict[str, list[int]] = {}  # guid → chat indices (for name → topic)
    group_chat_guids: dict[int, list[str]] = {}       # chat index → list of other-member guids
    try:
        _rc = _get_skype_module()
        skype_token, messaging_service = _rc.get_auth()
    except Exception:
        skype_token = messaging_service = ""

    if skype_token:
        for i, chat in enumerate(chats):
            if chat.get("chat_type") != "group" or chat.get("topic") != "Group Chat":
                continue
            cid = chat.get("id", "")
            try:
                thread_url = f"{messaging_service.replace('/v1', '')}/v1/threads/{urllib.parse.quote(cid, safe='')}"
                req = urllib.request.Request(
                    thread_url,
                    headers={"X-Skypetoken": skype_token, "Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=5) as r:
                    members = json.loads(r.read()).get("members", [])
                guids = []
                for m in members:
                    mri = m.get("id", "")
                    guid = mri.split(":")[-1].lower()
                    if guid and "-" in guid and guid != my_guid:
                        guids.append(guid)
                        if guid not in _name_cache:
                            group_guid_to_indices.setdefault(guid, []).append(i)
                group_chat_guids[i] = guids
                # Reclassify 2-person @thread.v2 chats as DMs — covers the case where our
                # POST /threads fallback created a group thread for what is really a 1:1.
                # Only when no user-set topic exists ("Group Chat" is the default placeholder).
                if len(members) == 2:
                    topic_norm = (chat.get("topic") or "").strip().lower()
                    if topic_norm in ("", "group chat"):
                        chat["chat_type"] = "oneOnOne"
            except Exception:
                pass

    # ── 3. Batch-resolve all unknown GUIDs via Graph ──────────────────────────
    all_unresolved = list({**{g: [] for g in dm_unresolved}, **{g: [] for g in group_guid_to_indices}}.keys())
    for chunk_start in range(0, len(all_unresolved), 20):
        chunk = all_unresolved[chunk_start:chunk_start + 20]
        try:
            batch_requests = [
                {"id": g, "method": "GET", "url": f"/users/{g}?$select=displayName,mail,userPrincipalName"}
                for g in chunk
            ]
            for resp in gc.batch(batch_requests):
                guid = resp.get("id", "")
                body = resp.get("body", {})
                if not isinstance(body, dict):
                    continue
                name = body.get("displayName", "")
                email = (body.get("mail") or body.get("userPrincipalName") or "").lower()
                if email and guid:
                    _name_cache[f"email:{guid}"] = email
                if name and guid:
                    _name_cache[guid] = name
        except Exception:
            pass

    # Apply DM names, emails and members list
    for guid, indices in dm_unresolved.items():
        name = _name_cache.get(guid, "")
        email = _name_cache.get(f"email:{guid}", "")
        for idx in indices:
            if name:
                chats[idx]["topic"] = name
            if email:
                chats[idx]["other_email"] = email
            if name or email:
                chats[idx]["members"] = [{"name": name or email, "email": email, "membership_id": ""}]

    # ── 4. Skype roster fallback for DMs still unresolved after Graph batch ────
    # When Graph /users/{guid} returns no result, use the Skype thread members endpoint.
    if skype_token and messaging_service:
        for guid, indices in dm_unresolved.items():
            if _name_cache.get(guid):
                continue  # already resolved by Graph batch
            if not indices:
                continue
            cid = chats[indices[0]].get("id", "")
            if not cid:
                continue
            try:
                base = messaging_service.rstrip("/")
                if base.endswith("/v1"):
                    base = base[:-3]
                thread_url = f"{base}/v1/threads/{urllib.parse.quote(cid, safe='')}"
                req = urllib.request.Request(
                    thread_url,
                    headers={"X-Skypetoken": skype_token, "Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=8) as r:
                    thread_data = json.loads(r.read())
                members = thread_data.get("members", [])
                for m in members:
                    mri = m.get("id", "") or m.get("mri", "")
                    mguid = mri.split(":")[-1].lower()
                    # Try both friendlyName and displayName
                    fname = m.get("friendlyName", "") or m.get("displayName", "") or m.get("name", "")
                    if mguid and mguid == guid and fname:
                        _name_cache[guid] = fname
                        for idx in indices:
                            chats[idx]["topic"] = fname
                        break
            except Exception:
                pass

    # Populate members for DMs that were resolved from cache (skipped dm_unresolved path)
    for i, chat in enumerate(chats):
        if chat.get("chat_type") == "oneOnOne" and not chat.get("members"):
            # Came from cache path — build members from what we have
            email = chat.get("other_email", "")
            name = chat.get("topic", "")
            if name or email:
                chat["members"] = [{"name": name or email, "email": email, "membership_id": ""}]

    # Apply group names and members list
    for chat_idx, guids in group_chat_guids.items():
        resolved = [
            {"name": _name_cache.get(g, ""), "email": _name_cache.get(f"email:{g}", ""), "membership_id": ""}
            for g in guids if _name_cache.get(g) or _name_cache.get(f"email:{g}")
        ]
        names = [m["name"] for m in resolved if m["name"]]
        if names:
            chats[chat_idx]["topic"] = ", ".join(names[:3])
        if resolved:
            chats[chat_idx]["members"] = resolved


def _resolve_dm_names_via_history(chats: list[dict], skype_token: str,
                                  messaging_service: str, rc) -> None:
    """Last-resort DM partner-name resolution from message history.

    When a 1:1 DM has an empty member roster AND the current user sent the last
    message, neither the GUID→name map (from last_sender) nor the Skype thread
    roster yields the partner's name, so the topic falls back to "Chat". The
    partner's name is always present in the thread's own message history, however
    (every message carries the sender's imdisplayname). For each unresolved DM,
    fetch one page of messages and use the first sender whose AAD GUID is NOT the
    current user's.

    Modifies chats in place. Best-effort: any failure leaves the topic as-is.
    """
    # Current user's AAD GUID — to skip our own messages.
    my_guid = ""
    try:
        import base64 as _b64
        from pathlib import Path as _P
        _tok = json.loads((_P.home() / ".config" / "microsoft-graph" / "token.json").read_text())
        _payload = _tok.get("access_token", "").split(".")[1]
        _payload += "=" * (4 - len(_payload) % 4)
        my_guid = json.loads(_b64.b64decode(_payload)).get("oid", "").lower()
    except Exception:
        pass

    for chat in chats:
        if chat.get("chat_type") != "oneOnOne":
            continue
        # Only act on DMs we couldn't resolve any other way.
        if chat.get("topic") != "Chat":
            continue
        cid = chat.get("id", "")
        if not cid:
            continue
        try:
            messages, _ = rc.read_messages(cid, skype_token, messaging_service, limit=20)
        except Exception:
            continue
        for m in messages:
            from_mri = m.get("from_mri", "") or m.get("from", "")
            sender_guid = from_mri.split(":")[-1].lower()
            sender_name = m.get("sender_name", "")
            # Skip our own messages and any non-name sender (bare GUID / MRI).
            if not sender_name or sender_name == from_mri:
                continue
            if my_guid and sender_guid == my_guid:
                continue
            if re.match(r'^[0-9a-fA-F]{8}-', sender_name):
                continue
            chat["topic"] = sender_name
            if not chat.get("members"):
                chat["members"] = [{"name": sender_name, "email": "", "membership_id": ""}]
            break


@router.get("/api/teams/chats")
def tp_teams_chats(skip: int = 0, top: int = 50, delta: bool = False, skype_cursor: str = ""):
    """Chat list via FOCI/Skype token. Pass skype_cursor from a previous response to page back."""
    try:
        import perf
        _rc = _get_skype_module()
        with perf.span("teams.get_auth"):
            skype_token, messaging_service = _rc.get_auth()
        with perf.span("teams.list_chats", top=top):
            convs, backward_link = _rc.list_chats(skype_token, messaging_service, limit=top, backward_link=skype_cursor)
        chats = _normalize_skype_chats(convs)
        with perf.span("teams.resolve_chat_names", chats=len(chats)):
            _resolve_chat_names(chats)
        # Last-resort DM name resolution: for any 1:1 still showing "Chat" (empty
        # roster + we sent the last message), pull the partner's name from the
        # thread's own message history via the Skype token.
        with perf.span("teams.resolve_dm_names", chats=len(chats)):
            _resolve_dm_names_via_history(chats, skype_token, messaging_service, _rc)
        has_more = bool(backward_link)
        return {"chats": chats, "has_viewpoint": True, "has_more": has_more, "skype_cursor": backward_link}
    except RuntimeError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        # The Skype chatsvc token is minted on a separate path from the Graph
        # token, so right after sign-in Teams can still 401 with errorCode 911
        # ("Authentication failed") for a few seconds until that token catches
        # up. That arrives here as a urllib HTTPError and used to surface as a
        # raw 500 ("Teams is broken"). Detect it and return a clear, retryable
        # 503 so the UI can say "still connecting" instead. (token-lag UX)
        if _is_skype_auth_error(e):
            raise HTTPException(status_code=503, detail="Teams session is still connecting — retry in a moment.")
        raise HTTPException(status_code=500, detail=str(e))


# Short-lived cache of the normalized search window so repeat searches in a session
# are instant. The window (which chats exist) changes slowly; 60s TTL is plenty and
# the chat-list poller keeps the live list fresh independently. (#118)
_search_window_cache: dict = {"chats": None, "ts": 0.0}
_SEARCH_WINDOW_TTL = 60.0

# ── Member long-title cache (disk-backed) ─────────────────────────────────────
# Mirrors what native Teams stores in IndexedDB as chatTitle.longTitle:
# a comma-separated string of all member display names per chat, used to
# match by member name at search time without per-chat API calls.
#
# Layout: { chat_id → "Name1, Name2, Name3, ..." }
# Persisted to disk so it survives server restarts and grows incrementally.
from pathlib import Path as _Path
_MEMBER_CACHE_PATH = _Path.home() / ".config" / "microsoft-graph" / "teams_member_cache.json"
_member_long_titles: dict[str, str] = {}  # in-memory copy, loaded at startup
_prefetch_running = False  # guard — only one prefetch at a time


def _load_member_cache() -> None:
    """Load the on-disk member cache into memory at startup."""
    global _member_long_titles
    try:
        if _MEMBER_CACHE_PATH.exists():
            _member_long_titles = json.loads(_MEMBER_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        _member_long_titles = {}


def _save_member_cache() -> None:
    try:
        _MEMBER_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _MEMBER_CACHE_PATH.write_text(
            json.dumps(_member_long_titles, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


_load_member_cache()


def _prefetch_member_names(chats: list[dict]) -> None:
    """Background thread: resolve full member rosters for all group/meeting chats
    and persist them to disk so search can match by member name.

    Works exactly like Teams' chatTitle.longTitle build:
      1. Fetch Skype /v1/threads/{id} roster (member MRIs) for unknown group chats
      2. Batch-resolve new GUIDs → displayName via Graph /users/$batch
      3. Build long_title = "Name1, Name2, ..." sorted alphabetically (excl. self)
      4. Write updated cache to disk

    Skips chats already in _member_long_titles (incremental, not full rebuild).
    """
    global _prefetch_running, _member_long_titles
    if _prefetch_running:
        return
    _prefetch_running = True
    try:
        import base64 as _b64
        from skills._m365.helpers import GraphClient

        # Resolve my own GUID so we can exclude self from long_title
        my_guid = ""
        try:
            tok = json.loads((_Path.home() / ".config" / "microsoft-graph" / "token.json").read_text())
            payload = tok.get("access_token", "").split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            my_guid = json.loads(_b64.b64decode(payload)).get("oid", "").lower()
        except Exception:
            pass

        try:
            gc = GraphClient()
            if not gc.get_token():
                return
            _rc = _get_skype_module()
            skype_token, messaging_service = _rc.get_auth()
        except Exception:
            return

        base_url = messaging_service.rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]

        dirty = False
        new_guids: set[str] = set()  # GUIDs needing Graph resolution this run

        for chat in chats:
            chat_id = chat.get("id", "")
            chat_type = chat.get("chat_type", "")
            if not chat_id or chat_type == "oneOnOne":
                continue  # DMs handled by existing resolver; skip
            if chat_id in _member_long_titles:
                continue  # already cached

            # Fetch Skype thread roster
            try:
                thread_url = f"{base_url}/v1/threads/{urllib.parse.quote(chat_id, safe='')}"
                req = urllib.request.Request(
                    thread_url,
                    headers={"X-Skypetoken": skype_token, "Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=8) as r:
                    members_raw = json.loads(r.read()).get("members", [])
            except Exception:
                continue

            guids = []
            for m in members_raw:
                mri = m.get("id", "") or m.get("mri", "")
                guid = mri.split(":")[-1].lower()
                if guid and "-" in guid and guid != my_guid:
                    guids.append(guid)
                    if guid not in _name_cache:
                        new_guids.add(guid)

            # Store guids on chat temporarily so we can build long_title after batch
            chat["_prefetch_guids"] = guids

        # Batch-resolve all new GUIDs in chunks of 20
        new_guids = list(new_guids)
        for chunk_start in range(0, len(new_guids), 20):
            chunk = new_guids[chunk_start:chunk_start + 20]
            try:
                batch_requests = [
                    {"id": g, "method": "GET", "url": f"/users/{g}?$select=displayName,mail,userPrincipalName"}
                    for g in chunk
                ]
                for resp in gc.batch(batch_requests):
                    guid = resp.get("id", "")
                    body = resp.get("body", {})
                    if not isinstance(body, dict):
                        continue
                    name = body.get("displayName", "")
                    email = (body.get("mail") or body.get("userPrincipalName") or "").lower()
                    if name and guid:
                        _name_cache[guid] = name
                    if email and guid:
                        _name_cache[f"email:{guid}"] = email
            except Exception:
                pass

        # Build and store long_title for each chat
        for chat in chats:
            guids = chat.pop("_prefetch_guids", None)
            if guids is None:
                continue
            chat_id = chat.get("id", "")
            names = sorted(
                n for g in guids
                if (n := _name_cache.get(g, ""))
            )
            if names:
                _member_long_titles[chat_id] = ", ".join(names)
                dirty = True

        if dirty:
            _save_member_cache()

    except Exception:
        pass
    finally:
        _prefetch_running = False


@router.get("/api/teams/search")
def tp_teams_search(q: str = "", top: int = 500):
    """Search Teams chats/channels by name, topic, or last message text.

    top defaults to the scan cap (500) so ALL name/group/last-message matches in the
    scanned window are returned — a small cap (was 50) truncated hundreds of real
    matches and made DMs/groups appear "missing" vs native Teams (#118).
    """
    if not q.strip():
        return {"chats": []}
    try:
        import time as _time
        # Serve the scanned window from cache when warm — avoids re-paginating ~10
        # Skype pages (the 2-7s cost) on every keystroke. TTL-bounded so it stays fresh.
        cached = _search_window_cache["chats"]
        if cached is not None and (_time.time() - _search_window_cache["ts"]) < _SEARCH_WINDOW_TTL:
            chats = cached
        else:
            _rc = _get_skype_module()
            skype_token, messaging_service = _rc.get_auth()
            # Fetch a wide window then filter — Teams has no server-side chat search.
            # Skype rejects an oversized pageSize (a 1k single page → HTTP 400), so
            # accumulate by following the backward_link cursor in a BOUNDED loop: safe
            # page size, max page count and max total, so search reaches conversations
            # older than the list horizon (#66) without an oversized request (#118).
            _SEARCH_PAGE = 50
            _SEARCH_MAX_PAGES = 10
            _SEARCH_MAX_CHATS = 500
            convs: list = []
            backward_link = ""
            for _page in range(_SEARCH_MAX_PAGES):
                page_convs, backward_link = _rc.list_chats(
                    skype_token, messaging_service, limit=_SEARCH_PAGE, backward_link=backward_link
                )
                convs.extend(page_convs)
                if not backward_link or len(convs) >= _SEARCH_MAX_CHATS:
                    break
            # NOTE: intentionally SKIP the per-chat name resolver here — it is
            # too slow for interactive search. Member names are resolved in the
            # background by _prefetch_member_names and persisted to disk so
            # subsequent searches can match by member name without any API calls.
            chats = _normalize_skype_chats(convs)
            _search_window_cache["chats"] = chats
            _search_window_cache["ts"] = _time.time()
            # Kick off background member-name prefetch (non-blocking)
            import threading as _threading
            _threading.Thread(
                target=_prefetch_member_names, args=(list(chats),), daemon=True
            ).start()
        ql = q.lower()
        matched = [
            c for c in chats
            if ql in (c.get("topic") or "").lower()
            or ql in (c.get("last_message") or "").lower()
            or ql in (c.get("last_sender") or "").lower()
            or any(ql in (m.get("name") or "").lower() for m in (c.get("members") or []))
            or any(ql in n.lower() for n in (c.get("_member_names") or []))
            or ql in _member_long_titles.get(c.get("id", ""), "").lower()
        ]
        print(f"[teams-search] q={q!r} scanned={len(chats)} matched={len(matched)} cache={len(_member_long_titles)}", flush=True)
        return {"chats": matched[:top], "has_viewpoint": True, "has_more": False}
    except RuntimeError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/teams/chats_GRAPH_DISABLED")
def tp_teams_chats_graph_disabled(skip: int = 0, top: int = 50, delta: bool = False):
    """Original Graph API path — kept for reference, not routed."""
    try:
        from skills._m365.helpers import make_teams_gc, get_cached_me
        gc = make_teams_gc()
        me = get_cached_me(gc)

        _PARAMS_VARIANTS = [
            {"$expand": "lastMessagePreview,members", "$select": "id,topic,chatType,lastUpdatedDateTime,viewpoint", "$top": str(top)},
            {"$expand": "lastMessagePreview,members", "$select": "id,topic,chatType,lastUpdatedDateTime", "$top": str(top)},
            {"$expand": "members", "$select": "id,topic,chatType,lastUpdatedDateTime", "$top": str(top)},
        ]

        if not delta:
            # ── Legacy full-fetch path with cursor pagination ──
            chats_raw = []
            _last_err = None
            for params in _PARAMS_VARIANTS:
                try:
                    result = gc.get("/me/chats", params)
                    chats_raw = result.get("value", [])
                    # Follow @odata.nextLink pages to get older chats
                    # Collect enough pages to satisfy skip + top
                    target = skip + top
                    while len(chats_raw) < target and "@odata.nextLink" in result:
                        result = gc.get_absolute(result["@odata.nextLink"])
                        chats_raw.extend(result.get("value", []))
                    _last_err = None
                    break
                except BaseException as e:
                    _last_err = e
                    continue
            if _last_err and ("401" in str(_last_err) or "403" in str(_last_err)):
                raise _last_err
            has_more = "@odata.nextLink" in result
            chats, _has_viewpoint = _normalize_teams_chats(chats_raw, me, gc)
            _resolve_chat_names(chats)
            sample = [(c["topic"][:20] if c.get("topic") else c["id"][:12], c["unread_count"]) for c in chats[:5]]
            print(f"[chats] has_viewpoint={_has_viewpoint} | unread={sum(c['unread_count'] for c in chats)} | total={len(chats)} | has_more={has_more}", flush=True)
            return {"chats": chats, "has_viewpoint": _has_viewpoint, "has_more": has_more}

        # ── Delta sync path ──
        # Skip delta entirely if it previously failed for this endpoint
        if "teams_chats" in shared._delta_unsupported:
            return tp_teams_chats(skip, top, delta=False)

        state = shared._delta_state.get("teams_chats")

        # Cold start: no delta state yet — use fast non-delta path first
        if not state or not state.get("delta_link"):
            return tp_teams_chats(skip, top, delta=False)

        if state and state.get("delta_link"):
            # Incremental sync
            try:
                result = gc.get_absolute(state["delta_link"])
            except Exception as e:
                if "410" in str(e):
                    shared._delta_state.pop("teams_chats", None)
                    return tp_teams_chats(skip, top, delta=True)
                raise
            from app import _apply_delta_changes
            _apply_delta_changes(state, result)
            while "@odata.nextLink" in result:
                result = gc.get_absolute(result["@odata.nextLink"])
                _apply_delta_changes(state, result)
            if "@odata.deltaLink" in result:
                state["delta_link"] = result["@odata.deltaLink"]
        else:
            # Initial delta sync with fallback params
            # Delta endpoint doesn't support $top — strip it from params
            # Cap pages to avoid chasing hundreds of @odata.nextLink on cold start
            _MAX_DELTA_PAGES = 5
            _delta_variants = [{k: v for k, v in p.items() if k != "$top"} for p in _PARAMS_VARIANTS]
            _last_err = None
            for params in _delta_variants:
                try:
                    result = gc.get("/me/chats/delta", params)
                    all_items = list(result.get("value", []))
                    _pages = 1
                    while "@odata.nextLink" in result and _pages < _MAX_DELTA_PAGES:
                        result = gc.get_absolute(result["@odata.nextLink"])
                        all_items.extend(result.get("value", []))
                        _pages += 1
                    if _pages >= _MAX_DELTA_PAGES and "@odata.nextLink" in result:
                        # Page cap hit and no deltaLink yet. Clear state so the next poll
                        # retries a full delta init rather than getting stuck on "" forever.
                        print(f"[chats] Delta init capped at {_pages} pages ({len(all_items)} items) — retrying delta next poll", flush=True)
                        shared._delta_state.pop("teams_chats", None)
                        return tp_teams_chats(skip, top, delta=False)
                    state = {
                        "delta_link": result.get("@odata.deltaLink", ""),
                        "items": all_items,
                    }
                    shared._delta_state["teams_chats"] = state
                    _last_err = None
                    break
                except BaseException as e:
                    _last_err = e
                    continue
            # If all variants failed with auth error, surface it instead of silently returning empty
            if _last_err and ("401" in str(_last_err) or "403" in str(_last_err)):
                raise _last_err
            if not shared._delta_state.get("teams_chats"):
                # All delta variants failed — remember this and skip delta on future calls
                shared._delta_unsupported.add("teams_chats")
                shared._save_delta_unsupported()
                print("[chats] Delta not supported for this token — disabling delta for teams_chats", flush=True)
                return tp_teams_chats(skip, top, delta=False)

        # Cap stored items
        if len(state["items"]) > shared._DELTA_MAX_ITEMS:
            state["items"] = state["items"][:shared._DELTA_MAX_ITEMS]

        chats, _has_viewpoint = _normalize_teams_chats(state["items"], me, gc)
        # Resolve DM partner names via Skype roster for chats where Graph members
        # expansion returned empty (Graph path doesn't always include member details).
        _resolve_chat_names(chats)
        sample = [(c["topic"][:20] if c.get("topic") else c["id"][:12], c["unread_count"]) for c in chats[:5]]
        print(f"[chats] has_viewpoint={_has_viewpoint} | unread={sum(c['unread_count'] for c in chats)} | sample: {sample}", flush=True)
        return {"chats": chats, "has_viewpoint": _has_viewpoint}
    except Exception as e:
        s = str(e)
        if "Graph API 401" in s: raise HTTPException(status_code=401, detail=s)
        if "Graph API 403" in s: raise HTTPException(status_code=403, detail=s)
        raise HTTPException(status_code=500, detail=s)


@router.get("/api/teams/chats/{chat_id}/messages")
def tp_teams_messages(chat_id: str, top: int = 50, next_link: str = "", skype_cursor: str = ""):
    """Full message thread. Tries Skype API (FOCI) first, falls back to Graph.

    Pagination:
    - Graph path: pass next_link from a previous response to fetch the next (older) page.
    - Skype path: pass skype_cursor (backwardLink URL from previous response) to page back.
    Response includes next_link/skype_cursor when more pages exist and has_more flag.
    """
    # ── Skype API path (permanent) ──────────────────────────────────────────
    try:
        import perf
        _rc = _get_skype_module()
        with perf.span("teams.get_auth"):
            skype_token, messaging_service = _rc.get_auth()
        my_mri = _get_my_mri()
        my_name = _get_my_name()
        with perf.span("teams.read_messages", top=top):
            raw_msgs, backward_link = _rc.read_messages(
                chat_id, skype_token, messaging_service, limit=top,
                backward_link=skype_cursor,
            )
        messages = _normalize_skype_messages(raw_msgs, my_mri, my_name)
        with perf.span("teams.resolve_sender_guids", msgs=len(messages)):
            _resolve_sender_guids(messages)
        with perf.span("teams.resolve_quoted_guids", msgs=len(messages)):
            _resolve_quoted_guids(messages)
        _resolve_system_event_names(messages)
        _resolve_reaction_names(messages)
        has_more = bool(backward_link)
        return {"messages": messages, "my_id": my_mri, "my_name": my_name,
                "peer_last_read": "", "next_link": "", "skype_cursor": backward_link,
                "has_more": has_more}
    except Exception as _skype_err:
        print(f"[teams] Skype API failed for messages, falling back to Graph: {_skype_err}", flush=True)

    # ── Graph API fallback (while captured token is still valid) ────────────
    EMOJI_TO_NAME = {"\U0001f44d": "like", "\u2764\ufe0f": "heart", "\U0001f602": "laugh", "\U0001f62e": "surprised", "\U0001f622": "sad", "\U0001f621": "angry"}
    try:
        from skills._m365.helpers import make_teams_gc, html_to_text, get_cached_me
        gc = make_teams_gc()
        me = get_cached_me(gc)
        my_id = me.get("id", "")
        my_name = me.get("displayName", "")
        # $orderby is not supported on all chat message endpoints with browser tokens — omit it
        # Use beta endpoint: v1.0 does not include reactions in chat message responses
        if next_link:
            result = gc.get_absolute(next_link)
        else:
            result = gc.get(f"/me/chats/{chat_id}/messages", {"$top": str(top)}, base_url="https://graph.microsoft.com/beta")
        raw = result.get("value", [])
        messages = []
        for m in raw:
            msg_type = m.get("messageType", "message")
            if msg_type == "systemEventMessage":
                import html as _html
                event = m.get("eventDetail") or {}
                rec_status = event.get("callRecordingStatus", "")
                rec_url = (event.get("callRecordingUrl") or event.get("recordingUrl") or "").strip()
                rec_title = (event.get("callTitle") or event.get("meetingSubject") or "Meeting recording").strip()
                if rec_status and rec_url:
                    rec_html = (
                        f'<div class="tp-recording-card">'
                        f'&#128249; {_html.escape(rec_title)}: '
                        f'<a href="{_html.escape(rec_url)}" target="_blank">Play recording</a>'
                        f'</div>'
                    )
                    messages.append({
                        "id": m.get("id", ""),
                        "sender_name": "Teams",
                        "sender_id": "",
                        "is_mine": False,
                        "body": f"Recording: {rec_title}",
                        "body_html": rec_html,
                        "created_at": m.get("createdDateTime", ""),
                        "last_modified_at": "",
                        "message_type": "systemEventMessage",
                        "reactions": [],
                        "attachments": [],
                    })
                continue
            if msg_type != "message":
                continue
            sender = ((m.get("from") or {}).get("user") or {})
            sender_id = sender.get("id", "")
            sender_name = sender.get("displayName", "")
            # is_mine: match by ID first, fall back to display name
            is_mine = bool(
                (my_id and sender_id and sender_id == my_id) or
                (my_name and sender_name and sender_name == my_name)
            )
            body_content = (m.get("body") or {}).get("content", "")
            content_type = (m.get("body") or {}).get("contentType", "text")
            # Skip raw call metadata JSON blobs (callId/scopeId JSON, roster blobs)
            # that render as GUID noise in the UI. Guard against filtering URIObject
            # recording messages which go through _parse_recording_uri_object first.
            _gc_is_recording = "URIObject" in body_content or "<a " in body_content
            if body_content and not _gc_is_recording and (
                '"callId"' in body_content or
                '"scopeId"' in body_content or
                "callStarted" in body_content or
                "callEnded" in body_content or
                ("8:orgid:" in body_content and "20448:orgid:" in body_content)
            ) and "tp-recording-card" not in body_content:
                continue
            body_html = ""
            if content_type == "html" and body_content:
                # Detect CallRecording URIObject messages and rewrite to a Play card (#105).
                # Raw URIObject XML has a nested <a href>Play</a> but the browser parser
                # strips attributes from unknown XML elements → href="" → window.open never fires.
                import html as _html_mod
                rec_url, rec_title = _parse_recording_uri_object(body_content)
                if rec_url:
                    body_html = (
                        f'<div class="tp-recording-card">'
                        f'&#128249; {_html_mod.escape(rec_title)}: '
                        f'<a href="{_html_mod.escape(rec_url)}" target="_blank" rel="noopener">Play recording</a>'
                        f'</div>'
                    )
                elif "URIObject" in body_content and "CallRecording" in body_content:
                    # URIObject with no extractable URL (in-progress/ChunkFinished recording)
                    # — skip rather than rendering raw XML as GUID noise.
                    continue
                else:
                    # Replace Teams image URLs with data-src so the browser can lazy-load
                    # them via /api/teams/proxy-image — avoids blocking the thread per image.
                    body_html = re.sub(
                        r'src="(https://(?:graph\.microsoft\.com|[^"]*\.teams\.microsoft\.com|[^"]*\.sfbassets\.com)[^"]+)"',
                        r'src="" data-teams-src="\1"',
                        body_content
                    )
            body_text = html_to_text(body_content, max_len=2000) if content_type == "html" else body_content
            # Reactions: list of {reactionType, user.displayName}
            reactions_raw = m.get("reactions") or []
            reactions = []
            for r in reactions_raw:
                rtype = EMOJI_TO_NAME.get(r.get("reactionType", ""), r.get("reactionType", ""))
                # Graph API nests user identity in various ways depending on version
                user_obj = r.get("user") or {}
                ruser = (
                    (user_obj.get("user") or {}).get("displayName")  # beta: user.user.displayName
                    or user_obj.get("displayName")                    # v1: user.displayName
                    or (user_obj.get("application") or {}).get("displayName")  # bot reactions
                    or ""
                )
                # If no name found, try to resolve from sender cache or use ID
                if not ruser:
                    uid = (user_obj.get("user") or {}).get("id") or user_obj.get("id") or ""
                    if uid:
                        # Check if this user is a sender in the current message list
                        for prev in raw:
                            pfrom = (prev.get("from") or {}).get("user") or {}
                            if pfrom.get("id") == uid and pfrom.get("displayName"):
                                ruser = pfrom["displayName"]
                                break
                    if not ruser:
                        ruser = uid[:8] if uid else "Someone"
                # Tag current user's reaction as "You" so frontend can detect remove toggle.
                if my_name and ruser and ruser == my_name:
                    ruser = "You"
                reactions.append({"type": rtype, "user": ruser})
            # Attachments: files shared in the chat (contentUrl = clickable link)
            attachments_raw = m.get("attachments") or []
            attachments = [{
                "id": a.get("id", ""),
                "name": a.get("name", ""),
                "content_type": a.get("contentType", ""),
                "content_url": a.get("contentUrl", ""),
                "thumbnail_url": a.get("thumbnailUrl", ""),
            } for a in attachments_raw if a.get("name")]
            messages.append({
                "id": m.get("id", ""),
                "sender_name": sender_name,
                "sender_id": sender_id,
                "is_mine": is_mine,
                "body": body_text,
                "body_html": body_html,
                "created_at": m.get("createdDateTime", ""),
                "last_modified_at": m.get("lastModifiedDateTime", ""),
                "message_type": m.get("messageType", "message"),
                "reactions": reactions,
                "attachments": attachments,
            })
        # Graph returns newest-first without $orderby — reverse to get chronological
        messages.reverse()
        # next_link points to the NEXT (older) page; after reversing it covers older messages
        response_next_link = result.get("@odata.nextLink", "")

        # Fetch chat-level read time for seen indicator (other party's last read)
        peer_last_read = ""
        try:
            chat_info = gc.get(f"/me/chats/{chat_id}", {"$select": "id,chatType,viewpoint"})
            peer_last_read = (chat_info.get("viewpoint") or {}).get("lastMessageReadDateTime", "")
        except Exception:
            pass

        return {"messages": messages, "my_id": my_id, "my_name": my_name,
                "peer_last_read": peer_last_read, "next_link": response_next_link,
                "has_more": bool(response_next_link), "fetch_top": top}
    except Exception as e:
        s = str(e)
        if "Graph API 401" in s:
            raise HTTPException(status_code=401, detail=s)
        if "Graph API 403" in s:
            raise HTTPException(status_code=403, detail=s)
        raise HTTPException(status_code=500, detail=s)


# Allowed hostnames for Teams image proxy — SSRF allowlist
_TEAMS_IMG_ALLOWED = {
    "graph.microsoft.com",
    "teams.microsoft.com",
    "statics.teams.cdn.office.net",
    "au.statics.teams.cdn.office.net",
    "eu.statics.teams.cdn.office.net",
    "asm.skype.com",
    "sfbassets.com",
}
# In-process LRU image cache: url → (content_type, bytes)  max 200 entries ~50MB
_img_cache: "_OD[str, tuple[str,bytes]]" = _OD()
_IMG_CACHE_MAX = 200

@router.get("/api/teams/proxy-image")
async def tp_teams_proxy_image(url: str):
    """Proxy a Teams-hosted image. SSRF-safe, async, cached."""
    from urllib.parse import urlparse
    from fastapi.responses import Response as _Resp
    parsed = urlparse(url)
    host = parsed.netloc.lower().split(":")[0]
    if not any(host == h or host.endswith("." + h) for h in _TEAMS_IMG_ALLOWED):
        raise HTTPException(status_code=400, detail="URL not from an allowed Teams domain")
    # Serve from cache if available
    if url in _img_cache:
        _img_cache.move_to_end(url)
        ct, data = _img_cache[url]
        return _Resp(content=data, media_type=ct, headers={"Cache-Control": "private, max-age=3600"})
    try:
        # Build auth headers: prefer Skype token for Teams/ASM images,
        # fall back to Bearer token for legacy Graph-hosted images
        auth_headers: dict[str, str] = {}
        skype_token_val: str = ""
        try:
            _rc = _get_skype_module()
            skype_token_val, _ = _rc.get_auth()
        except Exception:
            pass
        if skype_token_val:
            # asm.skype.com and the asyncgw media gateway both require
            # "Authorization: skype_token <token>" — X-Skypetoken 401s on those hosts.
            # Other Teams hosts accept X-Skypetoken.
            if "asm.skype.com" in url or "asyncgw" in host:
                auth_headers["Authorization"] = f"skype_token {skype_token_val}"
            else:
                auth_headers["X-Skypetoken"] = skype_token_val
        if not auth_headers:
            from skills._m365.helpers import make_teams_gc
            gc = make_teams_gc()
            bearer = gc.get_token()
            if bearer:
                auth_headers["Authorization"] = f"Bearer {bearer}"
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=auth_headers)
            if r.status_code == 429:
                raise HTTPException(status_code=429, detail="Graph rate limited — retry later")
            r.raise_for_status()
        ct = r.headers.get("content-type", "image/png")
        data = r.content
        # Store in cache, evict oldest if full
        _img_cache[url] = (ct, data)
        if len(_img_cache) > _IMG_CACHE_MAX:
            _img_cache.popitem(last=False)
        return _Resp(content=data, media_type=ct, headers={"Cache-Control": "private, max-age=3600"})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


def _parse_recording_uri_object(body_content: str) -> tuple[str | None, str]:
    """Extract (play_url, title) from a Teams CallRecording URIObject message body.

    Returns (None, '') if the content is not a recording or has no valid URL.
    Priority: <a href> Play link → onedriveForBusinessVideo item uri.
    """
    if "URIObject" not in body_content or "CallRecording" not in body_content:
        return None, ""
    # Extract title
    title_m = re.search(r"<Title>([^<]*)</Title>", body_content)
    title = title_m.group(1).strip() if title_m else "Meeting recording"
    # A single recording posts MANY chunk messages. Only the final "Success" chunk
    # carries a real SharePoint/OneDrive Play URL; intermediate chunks have an empty
    # <a href=""> and only an amsVideo (asyncgw) item. asyncgw/amsVideo URLs ALWAYS
    # return 401 when opened in a browser (they need an X-Skypetoken header), so we
    # must NEVER surface them — only a SharePoint/OneDrive URL yields a usable card.
    # Returning None for asyncgw-only chunks also collapses the duplicate cards.

    # Priority 1: onedriveForBusinessVideo item — SharePoint URL, browser-accessible.
    odv_m = re.search(r'type="onedriveForBusinessVideo"[^>]*\buri="(https://[^"]+)"', body_content)
    if odv_m and "asyncgw" not in odv_m.group(1):
        return odv_m.group(1), title
    # Priority 2: <a href="...">Play</a> — only a real SharePoint/OneDrive link.
    href_m = re.search(r'<a\s+href="(https://[^"]+)"[^>]*>\s*Play\s*</a>', body_content)
    if href_m and "asyncgw" not in href_m.group(1):
        return href_m.group(1), title
    # No browser-usable URL (asyncgw-only chunk, or empty href) — render no card.
    return None, ""


def _build_skype_mentions(mentions: list[dict]) -> list[dict]:
    """Serialize Graph mention objects into the Skype chatsvc properties format.

    Skype expects: [{itemid: int, mri: "8:orgid:<aad_id>", displayName: str}]
    Entries missing an AAD id are silently skipped.
    Used by both send and edit endpoints so serialization stays in sync.
    """
    result = []
    for m in mentions:
        aad_id = ((m.get("mentioned") or {}).get("user") or {}).get("id", "")
        if not aad_id:
            continue
        result.append({
            "itemid": m.get("id", 0),
            "mri": f"8:orgid:{aad_id}",
            "displayName": m.get("mentionText", ""),
        })
    return result


class TeamsHostedImage(BaseModel):
    contentType: str
    contentBytes: str  # base64


class TeamsEditRequest(BaseModel):
    body: str  # new HTML or plain text content
    is_html: bool = False  # client-computed; avoids server re-deriving from body prefix
    mentions: list[dict] = []  # Graph mention objects — same shape as TeamsSendRequest
    hosted_images: list[TeamsHostedImage] = []  # newly-pasted images to upload on edit (#112)


@router.patch("/api/teams/chats/{chat_id}/messages/{message_id}")
async def tp_teams_edit_message(chat_id: str, message_id: str, req: TeamsEditRequest):
    """Edit a sent Teams message via Skype chatsvc API (no Chat.ReadWrite scope needed)."""
    try:
        _rc = _get_skype_module()
        skype_token, messaging_service = _rc.get_auth()
        if not skype_token:
            raise HTTPException(status_code=503, detail="Skype token unavailable — restart AI Gator to refresh")
        msg_type = "RichText/Html" if req.is_html else "Text"
        # Upload any newly-pasted images to ASM and swap ../hostedContents/{n}/$value
        # placeholders for real asm.skype.com URLs — same as the send path. Without
        # this an image added during an edit would PATCH a raw data: URI which native
        # Teams can't store as a hosted image (#112).
        edit_content = _upload_images_to_asm(req.body, req.hosted_images, chat_id, skype_token)
        # Encode chat_id the same way read_messages does — Skype API requires it
        # messaging_service already ends with /v1 — do NOT add /v1/ again
        encoded_chat = urllib.parse.quote(chat_id, safe="")
        _edit_headers = {"X-Skypetoken": skype_token, "Content-Type": "application/json"}
        _edit_body = {"content": edit_content, "messagetype": msg_type}
        has_mentions = 'itemtype="http://schema.skype.com/Mention"' in req.body
        if has_mentions and req.mentions:
            skype_mentions = _build_skype_mentions(req.mentions)
            if skype_mentions:
                _edit_body["properties"] = {"mentions": json.dumps(skype_mentions)}
        _body_size = len(req.body.encode("utf-8"))
        print(f"[teams-edit] msg={message_id} size={_body_size} preview={req.body[:150]!r}", flush=True)
        url = f"{messaging_service}/users/ME/conversations/{encoded_chat}/messages/{message_id}"
        resp = httpx.put(url, headers=_edit_headers, json=_edit_body, timeout=15)
        if resp.status_code == 404 and "LocationLookupFailed" in resp.text:
            global_svc = _rc.get_global_service()
            if global_svc:
                resp = httpx.put(f"{global_svc}/users/ME/conversations/{encoded_chat}/messages/{message_id}", headers=_edit_headers, json=_edit_body, timeout=15)
        if resp.status_code not in (200, 201, 204):
            raise HTTPException(status_code=resp.status_code, detail=f"Skype API: {resp.text[:200]}")
        # Return the final content (real ASM URLs, placeholders resolved) so the bubble
        # stores it for the next edit instead of a stale ../hostedContents placeholder.
        return {"ok": True, "body_html": edit_content}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/teams/chats/{chat_id}/messages/{message_id}")
async def tp_teams_delete_message(chat_id: str, message_id: str):
    """Delete a sent Teams message via Skype chatsvc API — no Graph scope needed."""
    try:
        import httpx as _httpx
        _rc = _get_skype_module()
        skype_token, messaging_service = _rc.get_auth()
        encoded_chat = urllib.parse.quote(chat_id, safe="")
        _del_headers = {"X-Skypetoken": skype_token}
        url = f"{messaging_service}/users/ME/conversations/{encoded_chat}/messages/{message_id}"
        resp = _httpx.delete(url, headers=_del_headers, timeout=15)
        if resp.status_code == 404 and "LocationLookupFailed" in resp.text:
            global_svc = _rc.get_global_service()
            if global_svc:
                resp = _httpx.delete(f"{global_svc}/users/ME/conversations/{encoded_chat}/messages/{message_id}", headers=_del_headers, timeout=15)
        if resp.status_code in (200, 204):
            return {"ok": True}
        raise HTTPException(status_code=resp.status_code, detail=f"Skype API: {resp.text[:200]}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class TeamsReactionRequest(BaseModel):
    reaction: str   # Teams reaction key ("2795_heavyplussign") or emoji char ("➕")
    action: str = "add"   # "add" or "remove"


# Normalise legacy Skype key names → emoji chars (Graph rejects the word form)
_REACTION_KEY_TO_EMOJI = {"like": "👍", "heart": "❤️", "laugh": "😆", "surprised": "😮", "sad": "😢", "angry": "😡"}


# ── Teams emoji catalog (harvested from the Teams web picker) ────────────────
# Maps emoji char ↔ Teams reaction key. The chatsvc emotions API requires the KEY
# ("2795_heavyplussign"), not the raw glyph — Graph's setReaction rejected extended
# emojis, which is why reactions like ➕ silently failed. Loaded once, cached.
_teams_emoji_catalog: list | None = None
_emoji_char_to_key: dict[str, str] = {}
_emoji_key_to_char: dict[str, str] = {}

def _load_teams_emoji_catalog() -> None:
    global _teams_emoji_catalog
    if _teams_emoji_catalog is not None:
        return
    from pathlib import Path as _P
    _teams_emoji_catalog = []
    try:
        path = _P(__file__).resolve().parent.parent / "static" / "teams_emoji.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        _teams_emoji_catalog = data
        for e in data:
            key = e.get("key", "")
            char = e.get("char", "")
            if key and char:
                _emoji_key_to_char[key] = char
                # First key wins for a given char (base entry precedes tone variants)
                if char not in _emoji_char_to_key:
                    _emoji_char_to_key[char] = key
    except Exception as ex:
        print(f"[reactions] failed to load teams_emoji.json: {ex}", flush=True)


def _reaction_to_teams_key(reaction: str) -> str:
    """Resolve whatever the frontend sent (Teams key OR emoji char) to a Teams key."""
    _load_teams_emoji_catalog()
    if reaction in _emoji_key_to_char:
        return reaction                       # already a valid key
    if reaction in _emoji_char_to_key:
        return _emoji_char_to_key[reaction]   # emoji char → key
    # Legacy short-name ("like") → char → key
    legacy_char = _REACTION_KEY_TO_EMOJI.get(reaction)
    if legacy_char and legacy_char in _emoji_char_to_key:
        return _emoji_char_to_key[legacy_char]
    # Try stripping a trailing variation selector on the char
    bare = reaction.replace(chr(0xFE0F), "")
    if bare in _emoji_char_to_key:
        return _emoji_char_to_key[bare]
    return ""  # unknown — caller handles


@router.post("/api/teams/chats/{chat_id}/messages/{message_id}/react")
async def tp_teams_react(chat_id: str, message_id: str, req: TeamsReactionRequest):
    """Add or remove a reaction via the Skype/chatsvc emotions API — the same call
    native Teams makes. Graph's setReaction only accepts the classic reaction set and
    rejects extended emojis (➕, 🙊, etc.); chatsvc accepts the full catalog.

    Captured from the Teams web client:
      add:    PUT    {svc}/users/ME/conversations/{chat}/messages/{msg}/properties?name=emotions
              body:  {"emotions": {"key": "<key>", "value": <ms-epoch>}}
      remove: DELETE {svc}/users/ME/conversations/{chat}/messages/{msg}/properties?name=emotions
              body:  {"emotions": {"key": "<key>"}}
    The identifier is the Teams reaction KEY ("2795_heavyplussign"), not the glyph.
    """
    if not req.reaction:
        raise HTTPException(status_code=400, detail="reaction must be non-empty")
    if req.action not in ("add", "remove"):
        raise HTTPException(status_code=400, detail="action must be 'add' or 'remove'")

    key = _reaction_to_teams_key(req.reaction)
    if not key:
        raise HTTPException(status_code=400, detail=f"Unknown reaction: {req.reaction!r}")

    try:
        import httpx as _httpx
        _rc = _get_skype_module()
        skype_token, messaging_service = _rc.get_auth()
        if not skype_token:
            raise HTTPException(status_code=401, detail="No Teams (Skype) token available. Re-authenticate via Settings.")

        base = messaging_service.rstrip("/")
        encoded_chat = urllib.parse.quote(chat_id, safe="")
        url = (f"{base}/users/ME/conversations/{encoded_chat}"
               f"/messages/{message_id}/properties?name=emotions")
        headers = {
            "Authorization": f"Bearer {skype_token}",
            "X-Skypetoken": skype_token,
            "Content-Type": "application/json",
        }
        if req.action == "add":
            import time as _t
            body = {"emotions": {"key": key, "value": int(_t.time() * 1000)}}
            resp = _httpx.put(url, headers=headers, json=body, timeout=15)
        else:
            body = {"emotions": {"key": key}}
            resp = _httpx.request("DELETE", url, headers=headers, json=body, timeout=15)

        print(f"[reactions] {req.action} key={key!r} -> HTTP {resp.status_code}", flush=True)
        if resp.status_code in (200, 201, 204):
            return {"ok": True}
        raise HTTPException(status_code=resp.status_code, detail=f"chatsvc: {resp.text[:300]}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _skype_set_consumption_horizon(chat_id: str, horizon: str) -> bool:
    """Update the consumption horizon for a chat via the Skype internal API.

    horizon format: "{read_ms};{read_ms};{last_msg_id}"
    Setting this to "now" marks the chat as read; setting to "0;0;0" marks unread.
    Returns True on success.
    """
    import json as _json
    _rc = _get_skype_module()
    skype_token, messaging_service = _rc.get_auth()
    encoded_id = urllib.parse.quote(chat_id, safe="")
    url = f"{messaging_service}/users/ME/conversations/{encoded_id}/properties"
    payload = _json.dumps({"consumptionhorizon": horizon}).encode()
    req = urllib.request.Request(
        url, data=payload, method="PUT",
        headers={"X-Skypetoken": skype_token, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()
    return True


def _skype_set_consumption_horizon_bookmark(chat_id: str, bookmark: str) -> bool:
    """Mark a chat as unread using the consumptionHorizonBookmark endpoint.

    Native Teams uses PUT .../properties?name=consumptionHorizonBookmark with
    body {"consumptionHorizonBookmark": "{ts1};{ts2};{msgId}"} — not the plain
    consumptionhorizon field. This endpoint actually works for marking unread.
    """
    import json as _json
    _rc = _get_skype_module()
    skype_token, messaging_service = _rc.get_auth()
    encoded_id = urllib.parse.quote(chat_id, safe="")
    url = f"{messaging_service}/users/ME/conversations/{encoded_id}/properties?name=consumptionHorizonBookmark"
    payload = _json.dumps({"consumptionHorizonBookmark": bookmark}).encode()
    req = urllib.request.Request(
        url, data=payload, method="PUT",
        headers={"X-Skypetoken": skype_token, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()
    return True


def _chat_readwrite_token() -> str:
    """Return a Graph token with Chat.ReadWrite scope.

    Chat.ReadWrite is not in the FOCI pre-consented scopes for the Teams Desktop
    client ID (1fec8e78), so it can only come from the browser-captured Teams token
    (teams_token.json) which Microsoft's own Teams client obtained with full consent.
    Raises RuntimeError if the token is unavailable or expired.
    """
    import json as _j, time as _t
    from pathlib import Path as _P
    f = _P.home() / ".config" / "microsoft-graph" / "teams_token.json"
    if not f.exists():
        raise RuntimeError("teams_token.json not found — capture Teams token first")
    d = _j.loads(f.read_text())
    tok = d.get("access_token", "")
    exp = d.get("expires_at", 0)
    if not tok or _t.time() >= exp:
        raise RuntimeError("Teams browser token expired — recapture via Settings")
    return tok


def _graph_user_body(gc) -> dict:
    """Build the {user: {id, tenantId}} body required by markChatReadForUser /
    markChatUnreadForUser (Graph v1.0). Reads OID + tenantId from the token."""
    try:
        import base64 as _b64, json as _j
        tok = gc.get_token()
        payload = tok.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        claims = _j.loads(_b64.b64decode(payload))
        return {"user": {"id": claims.get("oid", ""), "tenantId": claims.get("tid", "")}}
    except Exception:
        return {}


@router.post("/api/teams/chats/{chat_id}/mark-read")
async def tp_teams_mark_read(chat_id: str):
    """Mark a chat as read — Skype horizon + Graph viewpoint so both paths stay in sync (#123)."""
    import time as _time
    skype_ok = False
    graph_ok = False
    try:
        now_ms = int(_time.time() * 1000)
        horizon = f"{now_ms};{now_ms};0"
        _skype_set_consumption_horizon(chat_id, horizon)
        # Clear any explicit mark-unread pin. Native Teams web clears the bookmark
        # with readUntil=0 ("0;{now};0") — a non-zero first field is an ACTIVE unread
        # pin, so writing "{now};{now};0" here would leave the chat unread in native
        # Teams (the Gator->native read-propagation bug). readUntil MUST be 0.
        try:
            _skype_set_consumption_horizon_bookmark(chat_id, f"0;{now_ms};0")
        except Exception:
            pass  # non-fatal — horizon is the primary read signal
        skype_ok = True
    except Exception as e:
        print(f"[mark-read] Skype horizon FAILED: {e}", flush=True)
    try:
        from skills._m365.helpers import GraphClient
        gc = GraphClient()
        try:
            gc._access_token = _chat_readwrite_token()
            gc._expires_at = float("inf")
        except Exception:
            pass  # fall back to whatever token GraphClient loaded
        gc.post(f"/me/chats/{chat_id}/markChatReadForUser", _graph_user_body(gc))
        graph_ok = True
    except Exception as e:
        print(f"[mark-read] Graph viewpoint FAILED: {e}", flush=True)
    return {"ok": skype_ok or graph_ok}


class TeamsMarkUnreadRequest(BaseModel):
    last_message_time: str = ""  # ISO timestamp of the last message, used to set a valid Skype horizon


@router.post("/api/teams/chats/{chat_id}/mark-unread")
async def tp_teams_mark_unread(chat_id: str, req: TeamsMarkUnreadRequest = TeamsMarkUnreadRequest()):
    """Mark a chat as unread — Skype horizon + Graph viewpoint so both paths stay in sync (#123).

    Uses last_message_time to set the consumption horizon to just before the last message
    so native Teams shows the chat as unread. '0;0;0' was ignored by native Teams.
    """
    skype_ok = False
    graph_ok = False
    try:
        # Use the consumptionHorizonBookmark endpoint — same as native Teams web uses.
        # Format: "{ts_before_last};{ts_of_last};{last_msg_id}"
        # Fetch the most recent message to get its ID and timestamp.
        _rc2 = _get_skype_module()
        skype_token2, messaging_service2 = _rc2.get_auth()
        msgs, _ = _rc2.read_messages(chat_id, skype_token2, messaging_service2, limit=5)
        # msgs are newest-first from read_messages
        last_msg = msgs[0] if msgs else None
        import time as _time2
        now_ms2 = int(_time2.time() * 1000)
        if last_msg:
            import datetime as _dt2
            msg_time_str = last_msg.get("time", "")
            msg_id = last_msg.get("id", "")
            ts2 = 0
            try:
                ts2 = int(_dt2.datetime.fromisoformat(msg_time_str.replace("Z", "+00:00")).timestamp() * 1000)
            except Exception:
                pass
            # Native Teams web bookmark format (verified from captures):
            #   "{readUntil};{modified};{msgId}" where readUntil = the target message's
            #   timestamp (so that message becomes the first unread) and modified = now.
            #   readUntil > 0 is the explicit-unread signal _normalize_skype_chats reads.
            read_until = ts2 if ts2 > 0 else now_ms2
            bookmark = f"{read_until};{now_ms2};{msg_id}"
        else:
            # No messages — pin with a non-zero readUntil so it still reads as unread.
            ts2 = now_ms2
            bookmark = f"{now_ms2};{now_ms2};0"
        _skype_set_consumption_horizon_bookmark(chat_id, bookmark)
        skype_ok = True
    except Exception as e:
        print(f"[mark-unread] Skype bookmark FAILED: {e}", flush=True)
    graph_detail = ""
    try:
        from skills._m365.helpers import GraphClient
        gc = GraphClient()
        try:
            gc._access_token = _chat_readwrite_token()
            gc._expires_at = float("inf")
        except Exception:
            pass  # fall back to whatever token GraphClient loaded
        body = _graph_user_body(gc)
        result = gc.post(f"/me/chats/{chat_id}/markChatUnreadForUser", body)
        graph_ok = True
        graph_detail = str(result)
    except Exception as e:
        graph_detail = str(e)
        print(f"[mark-unread] Graph FAILED: {e}", flush=True)
    return {"ok": skype_ok or graph_ok, "graph_ok": graph_ok, "graph_detail": graph_detail[:200]}


@router.get("/api/people/card/{aad_id}")
async def get_person_card(aad_id: str):
    """Return profile + manager info for a person by AAD GUID. Used for @mention click cards."""
    try:
        from skills._m365.helpers import GraphClient
        gc = GraphClient()
        select = "id,displayName,jobTitle,department,mail,userPrincipalName,officeLocation,businessPhones,mobilePhone"
        person = gc.get(f"/users/{aad_id}", {"$select": select})
        # Fetch manager (best-effort)
        manager: dict = {}
        try:
            mgr = gc.get(f"/users/{aad_id}/manager", {"$select": "displayName,jobTitle,mail,id"})
            manager = {"name": mgr.get("displayName", ""), "title": mgr.get("jobTitle", ""),
                       "email": mgr.get("mail", ""), "id": mgr.get("id", "")}
        except Exception:
            pass
        return {
            "id": person.get("id", ""),
            "name": person.get("displayName", ""),
            "title": person.get("jobTitle", ""),
            "department": person.get("department", ""),
            "email": person.get("mail", "") or person.get("userPrincipalName", ""),
            "office": person.get("officeLocation", ""),
            "phone": (person.get("businessPhones") or [None])[0] or person.get("mobilePhone", ""),
            "manager": manager,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/api/teams/joined-teams")
async def tp_joined_teams():
    """List teams the current user is a member of."""
    try:
        from skills._m365.helpers import make_teams_gc
        gc = make_teams_gc()
        result = gc.get("/me/joinedTeams", {"$select": "id,displayName"})
        teams = [{"id": t["id"], "name": t["displayName"]} for t in result.get("value", [])]
        teams.sort(key=lambda t: t["name"].lower())
        return {"teams": teams}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ChannelCreateRequest(BaseModel):
    team_id: str
    display_name: str
    description: str = ""
    membership_type: str = "standard"  # standard | private


@router.post("/api/teams/channels")
async def tp_create_channel(req: ChannelCreateRequest):
    """Create a new channel in a team."""
    try:
        from skills._m365.helpers import make_teams_gc
        gc = make_teams_gc()
        body = {
            "displayName": req.display_name,
            "description": req.description,
            "membershipType": req.membership_type,
        }
        result = gc.post(f"/teams/{req.team_id}/channels", body)
        return {"ok": True, "channel": {"id": result.get("id"), "name": result.get("displayName")}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class TeamsSendRequest(BaseModel):
    message: str
    hosted_images: list[TeamsHostedImage] = []
    mentions: list[dict] = []


def _upload_images_to_asm(content: str, hosted_images, chat_id: str,
                          skype_token: str) -> str:
    """Upload each hosted image to ASM and replace ../hostedContents/{n}/$value
    placeholders in `content` with the resulting asm.skype.com view URL.

    Permissions are granted to the THREAD (chat_id) — native Teams scopes hosted
    images to the thread, and that grant is what survives a later edit PUT. An
    "everyone"-only grant gets re-validated and rejected on edit (#112). Shared by
    the send and edit endpoints so newly-pasted images behave identically.
    """
    if not hosted_images:
        return content
    import httpx as _httpx
    import base64 as _b64
    _ASM = "https://us-api.asm.skype.com"
    _ASM_UA = "com.microsoft.teams2/1.0"
    _asm_headers = {
        "Authorization": f"skype_token {skype_token}",
        "Content-Type": "application/json",
        "User-Agent": _ASM_UA,
    }
    for i, img in enumerate(hosted_images):
        raw = _b64.b64decode(img.contentBytes)
        create_resp = _httpx.post(
            f"{_ASM}/v1/objects",
            headers=_asm_headers,
            json={"type": "pish/image", "permissions": {chat_id: ["read"]}},
            timeout=15,
        )
        create_resp.raise_for_status()
        obj_id = create_resp.json().get("id", "")
        if not obj_id:
            raise HTTPException(status_code=502, detail="ASM upload: no object ID returned")
        try:
            _httpx.put(
                f"{_ASM}/v1/objects/{obj_id}/permissions",
                headers=_asm_headers,
                json={chat_id: ["read"]},
                timeout=15,
            )
        except Exception as _perm_e:
            print(f"[teams-asm] permission PUT failed (non-fatal): {_perm_e}", flush=True)
        upload_resp = _httpx.put(
            f"{_ASM}/v1/objects/{obj_id}/content/imgpsh",
            headers={"Authorization": f"skype_token {skype_token}",
                     "Content-Type": img.contentType, "User-Agent": _ASM_UA},
            content=raw,
            timeout=30,
        )
        upload_resp.raise_for_status()
        cdn_url = f"{_ASM}/v1/objects/{obj_id}/views/imgo"
        content = content.replace(f"../hostedContents/{i + 1}/$value", cdn_url)
        print(f"[teams-asm] upload ok: obj={obj_id[:20]}", flush=True)
    return content


@router.post("/api/teams/chats/{chat_id}/send")
def tp_teams_send(chat_id: str, req: TeamsSendRequest):
    """Send a message to an existing Teams chat via Skype chatsvc API.

    Images are uploaded to ASM (api.asm.skype.com) first using the Skype token,
    then referenced by CDN URL in the message HTML. Graph ChatMessage.Send is
    Graph ChatMessage.Send may be blocked by tenant policy so we use the Skype path.
    """
    try:
        import httpx as _httpx
        import base64 as _b64

        _rc = _get_skype_module()
        skype_token, messaging_service = _rc.get_auth()

        # ── Upload images to ASM, rewrite hostedContents refs → CDN URLs ─────
        content = _upload_images_to_asm(req.message, req.hosted_images, chat_id, skype_token)

        encoded_chat = urllib.parse.quote(chat_id, safe="")
        url = f"{messaging_service}/users/ME/conversations/{encoded_chat}/messages"

        # Build Skype body — always RichText/Html so emoji are preserved.
        # Plain "Text" messagetype silently strips Unicode emoji in the Skype chatsvc API.
        has_mentions = 'itemtype="http://schema.skype.com/Mention"' in content
        if "<" not in content:
            content = f"<div>{content}</div>"
        content = _linkify_content(content)
        body: dict = _skype_send_body(content, "RichText/Html", _get_my_name())
        if has_mentions and req.mentions:
            skype_mentions = _build_skype_mentions(req.mentions)
            if skype_mentions:
                body["properties"] = {"mentions": json.dumps(skype_mentions)}
        print(f"[teams-send] body messagetype={body['messagetype']} content={body['content'][:120]!r}", flush=True)
        _send_headers = {"X-Skypetoken": skype_token, "Content-Type": "application/json"}
        resp = _httpx.post(url, headers=_send_headers, json=body, timeout=15)

        # LocationLookupFailed means the thread lives in a different Skype region than our
        # cached messaging_service URL. Retry once via the global amsV2 endpoint which
        # handles cross-region routing for @unq.gbl.spaces threads.
        if resp.status_code == 404 and "LocationLookupFailed" in resp.text:
            global_svc = _rc.get_global_service()
            if global_svc:
                print(f"[teams-send] LocationLookupFailed — retrying via global {global_svc}", flush=True)
                resp = _httpx.post(
                    f"{global_svc}/users/ME/conversations/{encoded_chat}/messages",
                    headers=_send_headers, json=body, timeout=15,
                )

        if resp.status_code not in (200, 201):
            raise HTTPException(status_code=resp.status_code, detail=f"Skype API: {resp.text[:300]}")

        result = resp.json() if resp.text else {}
        print(f"[teams-send] sent to {chat_id[:40]} via Skype API, id={result.get('id','?')}", flush=True)
        return {
            "ok": True,
            "message_id": result.get("id", ""),
            "created_at": result.get("composetime", ""),
            # Final HTML actually sent — has the real ASM image URLs (not the data:
            # URIs the editor pasted). The optimistic bubble stores this so a later
            # edit PATCHes ASM URLs, not a base64 blob native Teams can't store (#112).
            "body_html": content,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class TeamsRenameRequest(BaseModel):
    topic: str

@router.patch("/api/teams/chats/{chat_id}/rename")
def tp_teams_rename(chat_id: str, req: TeamsRenameRequest):
    """Rename a Teams group chat topic."""
    topic = req.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic cannot be empty")
    try:
        import httpx as _httpx
        _rc = _get_skype_module()
        skype_token, messaging_service = _rc.get_auth()
        # Skype threads endpoint for renaming: PUT {messaging_service}/threads/{chat_id}/properties
        url = f"{messaging_service}/threads/{urllib.parse.quote(chat_id, safe='')}/properties"
        resp = _httpx.put(url, headers={"X-Skypetoken": skype_token, "Content-Type": "application/json"},
                          json={"topic": topic}, timeout=15)
        if resp.status_code not in (200, 201, 204):
            raise HTTPException(status_code=resp.status_code, detail=f"Skype API: {resp.text[:200]}")
        return {"ok": True, "topic": topic}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class TeamsAddMembersRequest(BaseModel):
    emails: list[str]

@router.get("/api/teams/chats/{chat_id}/members")
def tp_teams_get_members(chat_id: str):
    """Fetch the current member roster for a Teams group chat via Skype chatsvc.

    The chat-list build only resolves the roster for UNNAMED groups (topic ==
    'Group Chat'); named groups skip it, leaving chat.members empty in the UI
    (#128). This endpoint fetches the roster on demand for any chat.
    """
    try:
        _rc = _get_skype_module()
        skype_token, messaging_service = _rc.get_auth()
        if not skype_token or not messaging_service:
            raise HTTPException(status_code=503, detail="Skype token unavailable — restart AI Gator to refresh")
        my_guid = (_get_my_mri() or "").split(":")[-1].lower()
        base = messaging_service.replace("/v1", "")
        thread_url = f"{base}/v1/threads/{urllib.parse.quote(chat_id, safe='')}"
        req_ = urllib.request.Request(
            thread_url,
            headers={"X-Skypetoken": skype_token, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req_, timeout=8) as r:
            raw_members = json.loads(r.read()).get("members", [])

        members = []
        for m in raw_members:
            mri = m.get("id", "")
            guid = mri.split(":")[-1].lower()
            name = m.get("friendlyName") or _name_cache.get(guid) or ""
            members.append({
                "name": name,
                "email": m.get("email", "") or _name_cache.get(f"email:{guid}", ""),
                "mri": mri,
                "guid": guid,
                "is_me": guid == my_guid,
            })

        # Resolve any still-unnamed members via Graph /users batch (same as the
        # chat-list build) so we show real names, not GUID fragments (#128).
        unresolved = [x["guid"] for x in members if not x["name"] and "-" in x["guid"]]
        if unresolved:
            try:
                from skills._m365.helpers import make_teams_gc
                gc = make_teams_gc()
                for cs in range(0, len(unresolved), 20):
                    chunk = unresolved[cs:cs + 20]
                    batch = [
                        {"id": g, "method": "GET", "url": f"/users/{g}?$select=displayName,mail,userPrincipalName"}
                        for g in chunk
                    ]
                    for resp in gc.batch(batch):
                        g = resp.get("id", "")
                        body = resp.get("body", {})
                        if not isinstance(body, dict):
                            continue
                        nm = body.get("displayName", "")
                        em = (body.get("mail") or body.get("userPrincipalName") or "").lower()
                        if nm:
                            _name_cache[g] = nm
                        if em:
                            _name_cache[f"email:{g}"] = em
                for x in members:
                    if not x["name"]:
                        x["name"] = _name_cache.get(x["guid"], "")
                    if not x["email"]:
                        x["email"] = _name_cache.get(f"email:{x['guid']}", "")
            except Exception:
                pass

        # Final fallback for anything Graph couldn't resolve
        for x in members:
            if not x["name"]:
                x["name"] = x["email"] or (x["guid"][:8] if x["guid"] else "Member")
            x.pop("guid", None)

        return {"members": members}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/teams/chats/{chat_id}/members/add")
def tp_teams_add_members(chat_id: str, req: TeamsAddMembersRequest):
    """Add members to a Teams group chat by email via Skype chatsvc API.

    Uses the FOCI-swapped Skype token (same as read path) which bypasses the
    Chat.ReadWrite / ChatMember.ReadWrite Graph scope gap.
    Endpoint: PUT {messaging_service}/v1/threads/{chat_id}/members/8:orgid:{aad_id}
    """
    if not req.emails:
        raise HTTPException(status_code=400, detail="No emails provided")
    try:
        from skills._m365.helpers import make_teams_gc
        _rc = _get_skype_module()
        skype_token, messaging_service = _rc.get_auth()
        if not skype_token or not messaging_service:
            raise HTTPException(status_code=503, detail="Skype token unavailable — restart AI Gator to refresh")

        gc = make_teams_gc()

        added = []
        failed = []
        for email in req.emails:
            email = email.strip().lower()
            if not email:
                continue
            user_id = None
            try:
                # Resolve email → AAD object ID (User.ReadBasic.All is sufficient)
                display = email
                for _filter in [f"mail eq '{email}'", f"userPrincipalName eq '{email}'"]:
                    r = gc.get("/users", params={"$filter": _filter, "$select": "id,displayName"})
                    users = r.get("value", [])
                    if users:
                        user_id = users[0]["id"]
                        display = users[0].get("displayName", email)
                        break
                if not user_id:
                    print(f"[add_members] could not resolve user: {email}", flush=True)
                    failed.append(email)
                    continue

                # Add via Skype chatsvc API — no Chat.ReadWrite scope needed
                # messaging_service already ends with /v1 — do NOT add /v1/ again
                mri = f"8:orgid:{user_id}"
                # Keep colons unencoded — Skype API expects literal 8:orgid:xxx in the path
                url = f"{messaging_service}/threads/{chat_id}/members/{urllib.parse.quote(mri, safe=':')}"
                resp = httpx.put(
                    url,
                    headers={"X-Skypetoken": skype_token, "Content-Type": "application/json"},
                    json={"role": "Admin"},
                    timeout=15,
                )
                if resp.status_code not in (200, 201):
                    raise RuntimeError(f"Skype API {resp.status_code}: {resp.text[:200]}")
                added.append(display)
                print(f"[add_members] added {display} ({mri}) via Skype API", flush=True)
            except Exception as _add_err:
                print(f"[add_members] failed to add {email} (id={user_id}): {_add_err}", flush=True)
                failed.append(email)
        return {"ok": True, "added": added, "failed": failed}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/teams/chats/{chat_id}/members/{member_mri:path}")
def tp_teams_remove_member(chat_id: str, member_mri: str):
    """Remove a member from a Teams group chat via Skype chatsvc API.

    member_mri: the Skype MRI of the member to remove (e.g. 8:orgid:{aad_id}).
    Endpoint: DELETE {messaging_service}/threads/{chat_id}/members/{mri}
    """
    try:
        import httpx as _httpx
        _rc = _get_skype_module()
        skype_token, messaging_service = _rc.get_auth()
        encoded_chat = urllib.parse.quote(chat_id, safe="")
        encoded_mri = urllib.parse.quote(member_mri, safe=":")
        url = f"{messaging_service}/threads/{encoded_chat}/members/{encoded_mri}"
        resp = _httpx.delete(url, headers={"X-Skypetoken": skype_token}, timeout=15)
        if resp.status_code in (200, 204):
            return {"ok": True, "removed": member_mri}
        raise HTTPException(status_code=resp.status_code, detail=f"Skype API: {resp.text[:200]}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class TeamsNewChatRequest(BaseModel):
    to: str       # single email or comma-separated emails
    message: str  # first message to send
    hosted_images: list[TeamsHostedImage] = []
    mentions: list[dict] = []


@router.post("/api/teams/chats/new")
async def tp_teams_new_chat(req: TeamsNewChatRequest):
    """Send a Teams message — 1:1 or group — entirely via Skype chatsvc API.

    No Chat.Create / Chat.Read Graph scopes needed.
    Flow:
      1. Resolve email(s) → AAD object IDs via Graph /users (User.ReadBasic.All — always available)
      2. Build MRIs (8:orgid:{aad_id}) for each recipient
      3. Find existing chat by scanning Skype conversation list (match on member MRIs)
      4. If not found: create via POST {messaging_service}/threads with member list
      5. Send first message via POST .../conversations/{chat_id}/messages
    """
    import httpx as _httpx
    try:
        from skills._m365.helpers import make_teams_gc, get_cached_me
        gc = make_teams_gc()
        me = get_cached_me(gc)
        my_id = me.get("id", "")
        my_mri = _get_my_mri()

        _rc = _get_skype_module()
        skype_token, messaging_service = _rc.get_auth()
        if not skype_token:
            raise HTTPException(status_code=503, detail="Skype token unavailable — restart AI Gator to refresh")

        recipients = [e.strip().lower() for e in req.to.split(",") if e.strip()]
        if not recipients:
            raise HTTPException(status_code=400, detail="No recipients provided")

        # ── Step 1: Resolve emails → AAD IDs (User.ReadBasic.All — always in token) ──
        def _resolve_email(email: str) -> str:
            for _filter in [f"mail eq '{email}'", f"userPrincipalName eq '{email}'"]:
                r = gc.get("/users", params={"$filter": _filter, "$select": "id"})
                users = r.get("value", [])
                if users:
                    return users[0]["id"]
            return ""

        recipient_ids: dict[str, str] = {}  # email → aad_id
        for email in recipients:
            uid = _resolve_email(email)
            if not uid:
                raise HTTPException(status_code=404, detail=f"Could not resolve user: {email}")
            recipient_ids[email] = uid

        # ── Step 2: Build MRIs ──
        their_mris = [f"8:orgid:{uid}" for uid in recipient_ids.values()]
        is_group = len(recipients) > 1

        # Self-chat: use 48:notes (Teams "Saved Messages" — always exists, no creation needed)
        is_self_chat = not is_group and list(recipient_ids.values())[0].lower() == my_id.lower()
        if is_self_chat:
            chat_id = "48:notes"
            print(f"[teams-new] Self-chat detected, using 48:notes", flush=True)

        # ── Step 3: Find existing chat via Skype conversation list ──
        if not is_self_chat:
            chat_id = ""
            try:
                convs, _ = _rc.list_chats(skype_token, messaging_service, limit=100)
                target_mri_set = set(their_mris) | {my_mri}
                for conv in convs:
                    conv_type = conv.get("thread_type", "").lower()
                    if is_group and conv_type not in ("group", ""):
                        continue
                    if not is_group and conv_type not in ("oneonone", ""):
                        continue
                    # For 1:1 chats the added_by_mri identifies the other party
                    if not is_group:
                        other_mri = conv.get("added_by_mri", "") or conv.get("last_sender_mri", "")
                        if other_mri and other_mri in their_mris:
                            chat_id = conv["id"]
                            print(f"[teams-new] Skype scan matched 1:1: {chat_id[:40]}", flush=True)
                            break
                    # For group chats we can only match on topic/participants heuristically
                    # Fall through to create if no match
                if not chat_id and not is_group:
                    print(f"[teams-new] No existing 1:1 found via Skype scan — will create", flush=True)
            except Exception as scan_err:
                print(f"[teams-new] Skype scan error (continuing to create): {scan_err}", flush=True)

        # ── Step 4: Create thread if not found ──
        if not chat_id:
            if is_group:
                # Group chats: create a new thread via POST /threads
                members = [{"id": my_mri, "role": "Admin"}] + [{"id": mri, "role": "Admin"} for mri in their_mris]
                thread_body = {"members": members, "properties": {"threadType": "Group"}}
                create_resp = _httpx.post(
                    f"{messaging_service}/threads",
                    headers={"X-Skypetoken": skype_token, "Content-Type": "application/json"},
                    json=thread_body,
                    timeout=15,
                )
                if create_resp.status_code not in (200, 201):
                    raise HTTPException(status_code=create_resp.status_code,
                                        detail=f"Skype thread create failed: {create_resp.text[:300]}")
                location = create_resp.headers.get("location", "")
                chat_id = location.rstrip("/").split("/")[-1] if location else (create_resp.json() or {}).get("id", "")
                if not chat_id:
                    raise HTTPException(status_code=500, detail="Thread created but could not determine chat ID")
                print(f"[teams-new] Created Skype group thread: {chat_id[:40]}", flush=True)
            else:
                # 1:1 DMs use the deterministic @unq.gbl.spaces id.  If chatsvc has never
                # seen this thread, the LocationLookupFailed handler below materializes it
                # via POST /v1/threads with a oneOnOne body (fixedRoster + uniquerosterthread).
                # This is what Teams Desktop does internally — no Graph Chat.Create needed.
                their_id = list(recipient_ids.values())[0]
                guids = sorted([my_id.lower(), their_id.lower()])
                chat_id = f"19:{guids[0]}_{guids[1]}@unq.gbl.spaces"
                print(f"[teams-new] Using deterministic 1:1 chat_id: {chat_id[:50]}", flush=True)

        # ── Step 5: Send first message via Skype API ──
        # Upload any inline pasted images to ASM and rewrite ../hostedContents refs.
        content = _upload_images_to_asm(req.message, req.hosted_images, chat_id, skype_token)
        # Wrap bare URLs so they render as clickable links in native Teams (#133).
        content = _linkify_content(content)
        has_mentions = 'itemtype="http://schema.skype.com/Mention"' in content
        msg_type = "RichText/Html" if "<" in content else "Text"
        encoded_chat = urllib.parse.quote(chat_id, safe="")
        send_body: dict = _skype_send_body(content, msg_type, _get_my_name() or me.get("displayName", ""))
        if has_mentions and req.mentions:
            skype_mentions = []
            for m in req.mentions:
                aad_id = ((m.get("mentioned") or {}).get("user") or {}).get("id", "")
                if not aad_id:
                    continue
                skype_mentions.append({
                    "itemid": m.get("id", 0),
                    "mri": f"8:orgid:{aad_id}",
                    "displayName": m.get("mentionText", ""),
                })
            if skype_mentions:
                send_body["properties"] = {"mentions": json.dumps(skype_mentions)}
        # Note: originalMessageContext in properties is rejected by Skype chatsvc with
        # errorCode 201. Navigation context is embedded as a deeplink <a> in the body instead.
        _send_hdrs = {"X-Skypetoken": skype_token, "Content-Type": "application/json"}
        send_resp = _httpx.post(
            f"{messaging_service}/users/ME/conversations/{encoded_chat}/messages",
            headers=_send_hdrs, json=send_body, timeout=15,
        )
        if send_resp.status_code == 404 and "LocationLookupFailed" in send_resp.text and not is_group:
            # Brand-new 1:1: chatsvc has no routing entry for the deterministic id yet.
            # Materialize the thread via POST /v1/threads with a oneOnOne body — this is
            # what Teams Desktop does internally on first-message-to-new-contact.  Uses
            # only the Skype token (no Graph Chat.Create scope), and produces a true
            # @unq.gbl.spaces 1:1 (not a @thread.v2 group).
            their_id = list(recipient_ids.values())[0]
            thread_body = {
                "type": "oneOnOne",
                "properties": {
                    "threadType": "oneOnOne",
                    "fixedRoster": "True",
                    "uniquerosterthread": "True",
                },
                "members": [
                    {"id": f"8:orgid:{my_id.lower()}",    "role": "Admin"},
                    {"id": f"8:orgid:{their_id.lower()}", "role": "Admin"},
                ],
            }
            for base, label in [(messaging_service, "regional"), (_rc.get_global_service(), "AFD")]:
                if not base:
                    continue
                try:
                    mat = _httpx.post(f"{base}/threads",
                                      headers=_send_hdrs, json=thread_body, timeout=15)
                    print(f"[teams-new] Materialize 1:1 via {label}: {mat.status_code}", flush=True)
                    if mat.status_code in (200, 201, 204):
                        break
                except Exception as mat_err:
                    print(f"[teams-new] Materialize {label} error: {mat_err}", flush=True)
            # Retry the send (try AFD if the regional materialize+resend still 404s)
            send_resp = _httpx.post(
                f"{messaging_service}/users/ME/conversations/{encoded_chat}/messages",
                headers=_send_hdrs, json=send_body, timeout=15,
            )
        if send_resp.status_code == 404 and "LocationLookupFailed" in send_resp.text:
            global_svc = _rc.get_global_service()
            if global_svc:
                print(f"[teams-new] LocationLookupFailed — retrying via global {global_svc}", flush=True)
                send_resp = _httpx.post(
                    f"{global_svc}/users/ME/conversations/{encoded_chat}/messages",
                    headers=_send_hdrs, json=send_body, timeout=15,
                )
        if send_resp.status_code not in (200, 201):
            raise HTTPException(status_code=send_resp.status_code,
                                detail=f"Skype send failed: {send_resp.text[:300]}")
        result = send_resp.json() if send_resp.text else {}
        print(f"[teams-new] Sent message to {chat_id[:40]} id={result.get('id','?')}", flush=True)
        return {"ok": True, "chat_id": chat_id, "message_id": result.get("id", "")}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class TeamsSendMessageRequest(BaseModel):
    to: str           # comma-separated email addresses
    message: str
    html: bool = False
    chat_id: str = "" # if known, send directly without resolving chat
    user_ids: str = "" # comma-separated Graph user IDs (from people search), avoids re-resolution
    recipients: list[dict] = [] # [{email,name,id}] from compose pane; source of truth when present
    mentions: list[dict] = []   # Graph-format mentions [{id, mentionText, mentioned: {user: {id, displayName}}}]


@router.post("/api/teams/send-message")
async def tp_teams_send_message(req: TeamsSendMessageRequest):
    """Send a Teams message from the compose pane — entirely via Skype chatsvc API.

    Fast path: chat_id known → send directly (no Graph needed).
    Slow path: no chat_id → delegate to tp_teams_new_chat logic.
    """
    import httpx as _httpx
    try:
        _rc = _get_skype_module()
        skype_token, messaging_service = _rc.get_auth()
        if not skype_token:
            raise HTTPException(status_code=503, detail="Skype token unavailable — restart AI Gator to refresh")

        # Fast path: chat_id already known — send directly via Skype
        if req.chat_id:
            content = req.message
            has_mentions = 'itemtype="http://schema.skype.com/Mention"' in content
            if "<" not in content:
                content = f"<div>{content}</div>"
            encoded_chat = urllib.parse.quote(req.chat_id, safe="")
            body: dict = _skype_send_body(content, "RichText/Html", _get_my_name())
            if has_mentions and req.mentions:
                skype_mentions = []
                for m in req.mentions:
                    aad_id = ((m.get("mentioned") or {}).get("user") or {}).get("id", "")
                    if not aad_id:
                        continue
                    skype_mentions.append({
                        "itemid": m.get("id", 0),
                        "mri": f"8:orgid:{aad_id}",
                        "displayName": m.get("mentionText", ""),
                    })
                if skype_mentions:
                    body["properties"] = {"mentions": json.dumps(skype_mentions)}
            _fp_hdrs = {"X-Skypetoken": skype_token, "Content-Type": "application/json"}
            resp = _httpx.post(
                f"{messaging_service}/users/ME/conversations/{encoded_chat}/messages",
                headers=_fp_hdrs, json=body, timeout=15,
            )
            if resp.status_code == 404 and "LocationLookupFailed" in resp.text:
                global_svc = _rc.get_global_service()
                if global_svc:
                    print(f"[teams-send] fast path LocationLookupFailed — retrying via global", flush=True)
                    resp = _httpx.post(
                        f"{global_svc}/users/ME/conversations/{encoded_chat}/messages",
                        headers=_fp_hdrs, json=body, timeout=15,
                    )
            if resp.status_code not in (200, 201):
                raise HTTPException(status_code=resp.status_code, detail=f"Skype API: {resp.text[:300]}")
            result = resp.json() if resp.text else {}
            print(f"[teams-send] fast path sent chat_id={req.chat_id[:30]} id={result.get('id','?')}", flush=True)
            return {"sent": True, "chat_id": req.chat_id, "message_id": result.get("id", "")}

        # Slow path: no chat_id — resolve recipients and find/create chat via tp_teams_new_chat
        if req.recipients:
            to_emails = ",".join(r.get("email", "") for r in req.recipients if r.get("email"))
        else:
            to_emails = req.to
        if not to_emails.strip():
            raise HTTPException(status_code=400, detail="Please provide at least one recipient.")

        new_req = TeamsNewChatRequest(to=to_emails, message=req.message, mentions=req.mentions)
        result = await tp_teams_new_chat(new_req)
        return {"sent": True, "chat_id": result.get("chat_id", ""), "message_id": result.get("message_id", "")}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/teams/channels/{team_id}/{channel_id}/messages")
async def tp_channel_messages(team_id: str, channel_id: str, top: int = 50):
    """Fetch messages from a Teams channel using Skype chatsvc (same as native Teams).

    Native Teams does NOT use Graph /teams/{id}/channels/{id}/messages \u2014 that requires
    ChannelMessage.Read.All which is not in our FOCI token. Instead it uses the Skype
    chatsvc conversations endpoint with the channel thread ID, which only needs the
    Skype token we already have.

    Flow:
    1. Fetch the channel conversation list to get root message (thread) IDs
    2. For each thread, fetch replies via ;messageid={rootId} suffix
    3. Return parents + replies structured for the frontend thread grouping
    """
    try:
        _rc = _get_skype_module()
        skype_token, messaging_service = _rc.get_auth()
        my_mri = _get_my_mri()
        my_name = _get_my_name()
        my_id = my_mri.split(":")[-1] if my_mri else ""

        # Step 1: Fetch the channel conversation to get its messages.
        # channel_id may or may not have the 19: prefix already — normalise.
        thread_id = channel_id if channel_id.startswith("19:") else f"19:{channel_id}"
        encoded_channel = urllib.parse.quote(thread_id, safe="")
        conv_url = (
            f"{messaging_service}/users/ME/conversations/{encoded_channel}/messages"
            f"?view=msnp24Equivalent|supportsMessageProperties&pageSize={top}&startTime=1"
        )
        import urllib.request as _ur
        req = _ur.Request(conv_url, headers={
            "X-Skypetoken": skype_token,
            "Accept": "application/json",
            "behavioroverride": "redirectAs404",
            "x-ms-migration": "True",
        })
        with _ur.urlopen(req, timeout=15) as resp:
            conv_data = json.loads(resp.read())

        raw_msgs = conv_data.get("messages", [])
        messages = []

        def _skype_sender_name(m: dict) -> str:
            name = m.get("imdisplayname", "")
            if name and not _GUID_NAME_RE.match(name):
                return name
            # Fall back to fromDisplayNameInToken fields
            given = m.get("fromGivenNameInToken", "")
            family = m.get("fromFamilyNameInToken", "")
            if family and given:
                return f"{family}, {given}"
            return name or ""

        def _skype_sender_id(m: dict) -> str:
            from_url = m.get("from", "")
            return from_url.split("/contacts/")[-1] if "/contacts/" in from_url else ""

        for m in raw_msgs:
            msgtype = m.get("messagetype", "")
            if msgtype.startswith("ThreadActivity") or msgtype in ("Event/Call",):
                continue
            sid = _skype_sender_id(m)
            sname = _skype_sender_name(m)
            is_mine = bool(my_mri and sid and sid.lower() == my_mri.lower())
            content_html = m.get("content", "")
            # Apply same normalization as _normalize_skype_messages
            content_html = _repair_blockquotes(content_html)
            messages.append({
                "id": m.get("id", ""),
                "sender_name": sname,
                "sender_id": sid,
                "is_mine": is_mine,
                "body": _rc._strip_html(content_html) if hasattr(_rc, "_strip_html") else "",
                "body_html": content_html,
                "created_at": m.get("composetime", ""),
                "last_modified_at": m.get("composetime", ""),
                "message_type": "message",
                "reactions": [],
                "reply_count": 0,
                "is_thread_parent": True,
                **_extract_forward_context(json.loads(m.get("properties", "{}") or "{}") if isinstance(m.get("properties"), str) else (m.get("properties") or {})),
            })

        # Step 2: For threads that have replies, fetch them via ;messageid= suffix
        # The rootMessageId field tells us which messages are thread roots with replies
        root_ids = {m["id"] for m in messages}
        for m_raw in raw_msgs:
            root_id = m_raw.get("rootMessageId", "")
            if not root_id or root_id == m_raw.get("id", ""):
                continue  # This IS the root, not a reply reference
            # This message is a reply to root_id \u2014 fetch all replies for that thread
            if root_id not in root_ids:
                continue
            # Already fetched above as part of the flat list; classify as reply
            sid = _skype_sender_id(m_raw)
            sname = _skype_sender_name(m_raw)
            is_mine = bool(my_mri and sid and sid.lower() == my_mri.lower())
            content_html = m_raw.get("content", "")
            content_html = _repair_blockquotes(content_html)
            # Update the message we already added, or add as reply
            existing = next((x for x in messages if x["id"] == m_raw.get("id", "")), None)
            if existing:
                existing["is_thread_parent"] = False
                existing["is_reply"] = True
                existing["reply_to_id"] = root_id
            else:
                messages.append({
                    "id": m_raw.get("id", ""),
                    "sender_name": sname,
                    "sender_id": sid,
                    "is_mine": is_mine,
                    "body": "",
                    "body_html": content_html,
                    "created_at": m_raw.get("composetime", ""),
                    "last_modified_at": m_raw.get("composetime", ""),
                    "message_type": "reply",
                    "reactions": [],
                    "is_reply": True,
                    "reply_to_id": root_id,
                    **_extract_forward_context(json.loads(m_raw.get("properties", "{}") or "{}") if isinstance(m_raw.get("properties"), str) else (m_raw.get("properties") or {})),
                })

        _resolve_sender_guids(messages)
        _resolve_quoted_guids(messages)
        messages.reverse()
        return {"messages": messages, "my_id": my_mri, "my_name": my_name}

    except Exception as e:
        # Fall back to Graph if Skype path fails (e.g. channel not in Skype index)
        print(f"[channel-skype] Skype path failed for {channel_id}: {e}", flush=True)

    # \u2500\u2500 Graph API fallback \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    EMOJI_TO_NAME = {"\U0001f44d": "like", "\u2764\ufe0f": "heart", "\U0001f602": "laugh", "\U0001f62e": "surprised", "\U0001f622": "sad", "\U0001f621": "angry"}
    try:
        from skills._m365.helpers import make_teams_gc, html_to_text, get_cached_me
        gc = make_teams_gc()
        me = get_cached_me(gc)
        my_id = me.get("id", "")
        my_name = me.get("displayName", "")
        result = gc.get(f"/teams/{team_id}/channels/{channel_id}/messages",
                        {"$top": str(top), "$expand": "replies"})
        raw = result.get("value", [])
        messages = []
        for m in raw:
            if m.get("messageType", "message") != "message":
                continue
            sender = ((m.get("from") or {}).get("user") or {})
            sender_id = sender.get("id", "")
            # displayName is sometimes missing from Graph channel message responses —
            # fall back to _name_cache (populated by prior batch lookups) then empty
            # string. Never surface the raw AAD GUID as a display name (#127).
            sender_name = sender.get("displayName", "") or _name_cache.get(sender_id, "")
            is_mine = bool(
                (my_id and sender_id and sender_id == my_id) or
                (my_name and sender_name and sender_name == my_name)
            )
            body_content = (m.get("body") or {}).get("content", "")
            content_type = (m.get("body") or {}).get("contentType", "text")
            if content_type == "html" and body_content:
                import html as _html_mod2
                rec_url2, rec_title2 = _parse_recording_uri_object(body_content)
                if rec_url2:
                    body_html = (
                        f'<div class="tp-recording-card">'
                        f'&#128249; {_html_mod2.escape(rec_title2)}: '
                        f'<a href="{_html_mod2.escape(rec_url2)}" target="_blank" rel="noopener">Play recording</a>'
                        f'</div>'
                    )
                else:
                    body_html = body_content
            else:
                body_html = ""
            body_text = html_to_text(body_content, max_len=2000) if content_type == "html" else body_content
            reactions_raw = m.get("reactions") or []
            reactions = []
            for r in reactions_raw:
                rtype = EMOJI_TO_NAME.get(r.get("reactionType", ""), r.get("reactionType", ""))
                ruser = ((r.get("user") or {}).get("user") or {}).get("displayName") or ""
                if my_name and ruser and ruser == my_name:
                    ruser = "You"
                reactions.append({"type": rtype, "user": ruser})
            reply_count = len(m.get("replies") or [])
            messages.append({
                "id": m.get("id", ""),
                "sender_name": sender_name,
                "sender_id": sender_id,
                "is_mine": is_mine,
                "body": body_text,
                "body_html": body_html,
                "created_at": m.get("createdDateTime", ""),
                "last_modified_at": m.get("lastModifiedDateTime", ""),
                "message_type": m.get("messageType", "message"),
                "reactions": reactions,
                "reply_count": reply_count,
                "is_thread_parent": True,
            })
            # Append replies inline, grouped directly after the parent (#127).
            # replies are sorted chronologically (oldest first).
            for rep in sorted(m.get("replies") or [], key=lambda x: x.get("createdDateTime", "")):
                if rep.get("messageType", "message") != "message":
                    continue
                rep_sender = ((rep.get("from") or {}).get("user") or {})
                rep_sid = rep_sender.get("id", "")
                rep_name = rep_sender.get("displayName", "") or _name_cache.get(rep_sid, "")
                rep_body = (rep.get("body") or {}).get("content", "")
                rep_ct = (rep.get("body") or {}).get("contentType", "text")
                rep_html = rep_body if rep_ct == "html" else ""
                rep_text = html_to_text(rep_body, max_len=2000) if rep_ct == "html" else rep_body
                messages.append({
                    "id": rep.get("id", ""),
                    "sender_name": rep_name,
                    "sender_id": rep_sid,
                    "is_mine": bool(my_id and rep_sid == my_id),
                    "body": rep_text,
                    "body_html": rep_html,
                    "created_at": rep.get("createdDateTime", ""),
                    "last_modified_at": rep.get("lastModifiedDateTime", ""),
                    "message_type": "reply",
                    "reactions": [],
                    "is_reply": True,
                    "reply_to_id": m.get("id", ""),
                })
        # Batch-resolve any sender IDs that are still missing a display name (#127).
        # Graph channel message responses sometimes omit displayName for guests/externals.
        # Collect unique unknown IDs, resolve once each via /users/{id}, backfill.
        # Also resolve when Graph returned the raw GUID as the displayName itself.
        def _name_is_guid(name: str) -> bool:
            return bool(name and _GUID_NAME_RE.match(name.strip()))
        unknown_ids = {
            m["sender_id"] for m in messages
            if m.get("sender_id") and (not m.get("sender_name") or _name_is_guid(m["sender_name"]))
        }
        for uid in unknown_ids:
            try:
                u = gc.get(f"/users/{uid}", {"$select": "displayName"})
                name = u.get("displayName", "")
                if name:
                    _name_cache[uid] = name
                    for msg in messages:
                        if msg.get("sender_id") == uid:
                            msg["sender_name"] = name
            except Exception:
                pass
        messages.reverse()
        return {"messages": messages, "my_id": my_id, "my_name": my_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _repair_blockquotes(content_html: str) -> str:
    """Repair blockquote itemtype corruption from the _linkify_content bug."""
    if not content_html or "schema.skype.com" not in content_html:
        return content_html
    return re.sub(
        r'(<blockquote\b[^>]*?)itemtype="&lt;a href=">'
        r'\s*(https?://schema\.skype\.com/[^"]+)"&gt;',
        r'\1itemtype="\2">',
        content_html,
    )


class ChannelSendRequest(BaseModel):
    message: str


@router.post("/api/teams/channels/{team_id}/{channel_id}/send")
def tp_channel_send(team_id: str, channel_id: str, req: ChannelSendRequest):
    """Send a message to a Teams channel."""
    try:
        from skills._m365.helpers import make_teams_gc
        gc = make_teams_gc()

        # ── SAFETY: Verify team/channel exists and user is a member ──
        try:
            ch_info = gc.get(f"/teams/{team_id}/channels/{channel_id}", {"$select": "id,displayName"})
            print(f"[teams-send] VERIFIED channel team={team_id} channel={ch_info.get('displayName','')[:30]}", flush=True)
        except Exception as verify_err:
            err_str = str(verify_err)
            if "404" in err_str:
                print(f"[teams-send] SAFETY BLOCK: channel {team_id}/{channel_id} not found", flush=True)
                raise HTTPException(status_code=404, detail="Channel not found — it may have been deleted")
            print(f"[teams-send] Channel verify skipped (scope issue): {verify_err} — proceeding", flush=True)

        content_type = "html" if "<" in req.message else "text"
        result = gc.post(f"/teams/{team_id}/channels/{channel_id}/messages", {
            "body": {"contentType": content_type, "content": req.message},
        })
        return {"ok": True, "message_id": result.get("id", ""), "created_at": result.get("createdDateTime", "")}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Meeting transcripts — beta drive-item endpoint
# ---------------------------------------------------------------------------
# Replaces the original /me/onlineMeetings/{id}/transcripts path, which requires
# OnlineMeetingTranscript.Read.All (often blocked by tenant policy). The beta
# /drives/{driveId}/items/{itemId}/media/transcripts path works with the
# Files.ReadWrite.All scope already on the token.
#
# Recordings live in the organizer's OneDrive. The (driveId, itemId) pair is
# resolved by scanning the meeting chat for the RichText/Media_CallRecording
# attachment, then dereferencing the embedded SharePoint share URL via
# /shares/{id}/driveItem.

import importlib.util as _txi
import logging as _txlog
from pathlib import Path as _TxPath

log = _txlog.getLogger("teams_route")

_TRANSCRIPT_SCRIPTS = _TxPath(__file__).resolve().parent.parent / "skills" / "m365-teams" / "scripts"


def _load_tx_module(name: str):
    import sys as _sys
    scripts_dir = str(_TRANSCRIPT_SCRIPTS)
    if scripts_dir not in _sys.path:
        _sys.path.insert(0, scripts_dir)
    mod_name = f"_tx_{name}"
    spec = _txi.spec_from_file_location(mod_name, str(_TRANSCRIPT_SCRIPTS / f"{name}.py"))
    mod = _txi.module_from_spec(spec)
    _sys.modules[mod_name] = mod  # register before exec so dataclasses can resolve __module__
    spec.loader.exec_module(mod)
    return mod


_tx_config = _load_tx_module("transcript_config")
_tx_vtt = _load_tx_module("transcript_vtt")
_tx_cache = _load_tx_module("transcript_cache")
_tx_beta = _load_tx_module("transcript_beta")
_tx_recording = _load_tx_module("transcript_recording")

# Patchable names for tests:
_tx_list_transcripts = _tx_beta.list_transcripts
_tx_fetch_content = _tx_beta.fetch_transcript_content
_tx_resolve_chat = _tx_recording.resolve_recording_from_chat
_tx_resolve_chat_all = _tx_recording.resolve_recordings_from_chat
_tx_resolve_event = _tx_recording.resolve_recording_from_event


def _get_or_cache_vtt(drive_id: str, item_id: str, transcript_id: str) -> str:
    text = _tx_cache.read(transcript_id)
    if text is None:
        text = _tx_fetch_content(drive_id, item_id, transcript_id)
        _tx_cache.write(transcript_id, text)
    return text


def _recording_to_dict(info) -> dict:
    return {
        "drive_id": info.drive_id,
        "item_id": info.item_id,
        "title": info.title,
        "original_name": info.original_name,
        "has_transcript": info.has_transcript,
        "web_url": info.web_url,
        "created_at": getattr(info, "created_at", ""),
    }


@router.get("/api/teams/meetings/config")
def transcripts_config():
    return {
        "recurring_occurrences_cap": _tx_config.RECURRING_OCCURRENCES_CAP,
        "full_fetch_token_threshold": _tx_config.FULL_FETCH_TOKEN_THRESHOLD,
        "search_context_seconds": _tx_config.SEARCH_CONTEXT_SECONDS,
    }


@router.get("/api/recordings/{drive_id}/{item_id}/transcripts")
def list_recording_transcripts(drive_id: str, item_id: str):
    try:
        items = _tx_list_transcripts(drive_id, item_id)[: _tx_config.RECURRING_OCCURRENCES_CAP]
    except Exception as e:
        log.info("list_transcripts(%s, %s) failed: %s", drive_id, item_id, e)
        return {"total": 0, "transcripts": []}
    out = []
    for it in items:
        out.append({
            "id": it.get("id"),
            "created": it.get("createdDateTime"),
            "language": it.get("languageTag"),
            "display_name": it.get("displayName"),
        })
    return {"total": len(out), "transcripts": out}


@router.get("/api/recordings/{drive_id}/{item_id}/transcripts/{transcript_id}/header")
def transcript_header(drive_id: str, item_id: str, transcript_id: str):
    vtt = _get_or_cache_vtt(drive_id, item_id, transcript_id)
    cues = _tx_vtt.parse_vtt(vtt)
    h = _tx_vtt.build_header(cues, preview_seconds=90)
    h["size_tokens_estimate"] = _tx_config.estimate_tokens_from_vtt_bytes(len(vtt.encode("utf-8")))
    return h


@router.get("/api/recordings/{drive_id}/{item_id}/transcripts/{transcript_id}/range")
def transcript_range(drive_id: str, item_id: str, transcript_id: str,
                     start_min: float = 0, end_min: float = 60):
    vtt = _get_or_cache_vtt(drive_id, item_id, transcript_id)
    cues = _tx_vtt.parse_vtt(vtt)
    sliced = _tx_vtt.slice_range(cues, start_min * 60.0, end_min * 60.0)
    return {"start_min": start_min, "end_min": end_min, "count": len(sliced),
            "text": _tx_vtt.cues_to_text(sliced)}


@router.get("/api/recordings/{drive_id}/{item_id}/transcripts/{transcript_id}/search")
def transcript_search(drive_id: str, item_id: str, transcript_id: str,
                      q: str, max_results: int = 5):
    vtt = _get_or_cache_vtt(drive_id, item_id, transcript_id)
    cues = _tx_vtt.parse_vtt(vtt)
    hits = _tx_vtt.search_cues(cues, q, _tx_config.SEARCH_CONTEXT_SECONDS, max_results)
    return {"total": len(hits), "hits": hits}


@router.get("/api/recordings/{drive_id}/{item_id}/transcripts/{transcript_id}/speaker")
def transcript_speaker(drive_id: str, item_id: str, transcript_id: str, name: str):
    vtt = _get_or_cache_vtt(drive_id, item_id, transcript_id)
    cues = _tx_vtt.parse_vtt(vtt)
    filt = _tx_vtt.filter_speaker(cues, name)
    return {"speaker": name, "count": len(filt), "text": _tx_vtt.cues_to_text(filt)}


@router.get("/api/recordings/{drive_id}/{item_id}/transcripts/{transcript_id}/full")
def transcript_full(drive_id: str, item_id: str, transcript_id: str):
    vtt = _get_or_cache_vtt(drive_id, item_id, transcript_id)
    cues = _tx_vtt.parse_vtt(vtt)
    return {"text": _tx_vtt.cues_to_text(cues),
            "size_tokens_estimate": _tx_config.estimate_tokens_from_vtt_bytes(len(vtt.encode("utf-8")))}


@router.get("/api/teams/chats/{chat_id}/recording")
def teams_chat_recording(chat_id: str):
    try:
        info = _tx_resolve_chat(chat_id)
    except Exception as e:
        log.info("resolve_recording_from_chat(%s) failed: %s", chat_id, e)
        return {"recording": None}
    return {"recording": _recording_to_dict(info) if info else None}


@router.get("/api/teams/chats/{chat_id}/recordings")
def teams_chat_recordings(chat_id: str):
    try:
        recs = _tx_resolve_chat_all(chat_id)
    except Exception as e:
        log.info("resolve_recordings_from_chat(%s) failed: %s", chat_id, e)
        return {"total": 0, "recordings": []}
    out = [_recording_to_dict(r) for r in recs]
    return {"total": len(out), "recordings": out}


@router.get("/api/calendar/events/{event_id}/recording")
def calendar_event_recording(event_id: str):
    try:
        info = _tx_resolve_event(event_id)
    except Exception as e:
        log.info("resolve_recording_from_event(%s) failed: %s", event_id, e)
        return {"recording": None}
    return {"recording": _recording_to_dict(info) if info else None}
