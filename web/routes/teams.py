"""Teams route group — extracted from app.py."""

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

    messages = []
    for m in raw_msgs:
        from_mri = m.get("from_mri", "")
        sender_name = m.get("sender_name", "") or from_mri.split(":")[-1]
        is_mine = bool(my_mri and from_mri and from_mri.lower() == my_mri.lower())
        content_html = m.get("content_html", "")
        mention_map: dict[str, str] = m.get("mention_map", {})
        if content_html and "<img" in content_html:
            import logging as _log
            _log.getLogger("teams.img").debug("RAW img HTML: %s", content_html[:2000])
        if content_html:
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
        # Parse reactions: [{key, users:[{mri}]}] → [{type, user}]
        # Tag current user's reactions as "You" so the frontend can detect toggles.
        reactions = []
        for emotion in m.get("emotions_raw", []):
            rtype = emotion.get("key", "")
            for u in emotion.get("users", []):
                umri = u.get("mri", "")
                is_my_reaction = bool(my_mri and umri and umri.lower() == my_mri.lower())
                reactions.append({"type": rtype, "user": "You" if is_my_reaction else _resolve_mri(umri)})

        created_at = m.get("time", "")
        last_modified = m.get("edit_time", "") or created_at
        messages.append({
            "id": m.get("id", ""),
            "sender_name": sender_name,
            "sender_id": from_mri,
            "is_mine": is_mine,
            "body": m.get("content", ""),
            "body_html": content_html,
            "created_at": created_at,
            "last_modified_at": last_modified,
            "message_type": "message",
            "reactions": reactions,
            "attachments": [],
        })
    return messages


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

    # Build GUID → display name map from all senders across all conversations.
    # This lets us resolve DM partner names without extra API calls.
    # Key: lowercase AAD GUID; value: display name
    _guid_to_name: dict[str, str] = {}
    for _c in convs:
        _sender_mri = _c.get("last_sender_mri", "")  # e.g. "8:orgid:{guid}" or "orgid:{guid}"
        _sender_name = _c.get("last_sender", "")
        if _sender_name and _sender_mri:
            # Extract GUID from MRI: "8:orgid:{guid}" → "{guid}"
            _guid = _sender_mri.split(":")[-1].lower()
            if _guid and "-" in _guid:
                _guid_to_name[_guid] = _sender_name

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
        unread = 1 if (last_dt and read_dt and last_dt > read_dt) else 0

        # Clean up topics that are roster dumps (raw MRI strings)
        raw_topic = conv.get("topic", "")
        if any(p in raw_topic for p in ("8:orgid:", "8:teamsvisitor:", "8:live:")):
            raw_topic = ""

        if cid == "48:notes":
            topic = "Notes to Self"
        elif raw_topic:
            topic = raw_topic
        elif chat_type == "meeting":
            topic = "Meeting"
        elif chat_type == "oneOnOne":
            topic = _resolve_other_dm_name(conv) or conv.get("last_sender") or "Chat"
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

        chats.append({
            "id": cid,
            "topic": topic,
            "last_message": _last_msg,
            "last_message_time": last_time,
            "last_sender": _last_sender,
            "last_read_time": last_read_time,
            "unread_count": unread,
            "chat_type": chat_type,
            "member_emails": [],
            "members": [],
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
        if chat.get("topic"):
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
        except Exception as e:
            print(f"[chat-names] batch resolve failed: {e}", flush=True)

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


@router.get("/api/teams/chats")
def tp_teams_chats(skip: int = 0, top: int = 50, delta: bool = False, skype_cursor: str = ""):
    """Chat list via FOCI/Skype token. Pass skype_cursor from a previous response to page back."""
    try:
        _rc = _get_skype_module()
        skype_token, messaging_service = _rc.get_auth()
        convs, backward_link = _rc.list_chats(skype_token, messaging_service, limit=top, backward_link=skype_cursor)
        chats = _normalize_skype_chats(convs)
        _resolve_chat_names(chats)
        has_more = bool(backward_link)
        return {"chats": chats, "has_viewpoint": True, "has_more": has_more, "skype_cursor": backward_link}
    except RuntimeError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        s = str(e)
        raise HTTPException(status_code=500, detail=s)


@router.get("/api/teams/search")
def tp_teams_search(q: str = "", top: int = 50):
    """Search Teams chats/channels by name, topic, or last message text."""
    if not q.strip():
        return {"chats": []}
    try:
        _rc = _get_skype_module()
        skype_token, messaging_service = _rc.get_auth()
        # Fetch a wide window then filter — Teams has no server-side chat search.
        # This must be decoupled from (and far larger than) the list-view default so
        # conversations older than the list horizon are still searchable (#66).
        convs, _ = _rc.list_chats(skype_token, messaging_service, limit=1000)
        chats = _normalize_skype_chats(convs)
        _resolve_chat_names(chats)
        ql = q.lower()
        matched = [
            c for c in chats
            if ql in (c.get("topic") or "").lower()
            or ql in (c.get("last_message") or "").lower()
            or any(ql in (m.get("name") or "").lower() for m in (c.get("members") or []))
        ]
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
                        print(f"[chats] Delta init capped at {_pages} pages ({len(all_items)} items) — using last deltaLink", flush=True)
                    state = {
                        "delta_link": result.get("@odata.deltaLink", result.get("@odata.nextLink", "")),
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
        _rc = _get_skype_module()
        skype_token, messaging_service = _rc.get_auth()
        my_mri = _get_my_mri()
        my_name = _get_my_name()
        raw_msgs, backward_link = _rc.read_messages(
            chat_id, skype_token, messaging_service, limit=top,
            backward_link=skype_cursor,
        )
        messages = _normalize_skype_messages(raw_msgs, my_mri, my_name)
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
            if m.get("messageType", "message") != "message":
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
            body_html = ""
            if content_type == "html" and body_content:
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
            # asm.skype.com requires "Authorization: skype_token <token>"
            # Other Teams hosts accept X-Skypetoken
            if "asm.skype.com" in url:
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


class TeamsEditRequest(BaseModel):
    body: str  # new HTML or plain text content


@router.patch("/api/teams/chats/{chat_id}/messages/{message_id}")
async def tp_teams_edit_message(chat_id: str, message_id: str, req: TeamsEditRequest):
    """Edit a sent Teams message via Skype chatsvc API (no Chat.ReadWrite scope needed)."""
    try:
        _rc = _get_skype_module()
        skype_token, messaging_service = _rc.get_auth()
        if not skype_token:
            raise HTTPException(status_code=503, detail="Skype token unavailable — restart AI Gator to refresh")
        is_html = req.body.strip().startswith("<")
        msg_type = "RichText/Html" if is_html else "Text"
        # Encode chat_id the same way read_messages does — Skype API requires it
        # messaging_service already ends with /v1 — do NOT add /v1/ again
        encoded_chat = urllib.parse.quote(chat_id, safe="")
        _edit_headers = {"X-Skypetoken": skype_token, "Content-Type": "application/json"}
        _edit_body = {"content": req.body, "messagetype": msg_type}
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
        return {"ok": True}
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
    reaction: str   # emoji character, e.g. "👍" (any emoji accepted by Graph setReaction)
    action: str = "add"   # "add" or "remove"


# Normalise legacy Skype key names → emoji chars (Graph rejects the word form)
_REACTION_KEY_TO_EMOJI = {"like": "👍", "heart": "❤️", "laugh": "😆", "surprised": "😮", "sad": "😢", "angry": "😡"}


def _get_graph_token() -> str:
    from pathlib import Path as _P
    tok = json.loads((_P.home() / ".config" / "microsoft-graph" / "token.json").read_text())
    return tok.get("access_token", "")


@router.post("/api/teams/chats/{chat_id}/messages/{message_id}/react")
async def tp_teams_react(chat_id: str, message_id: str, req: TeamsReactionRequest):
    """Add or remove an emoji reaction via Graph setReaction / unsetReaction.

    Graph accepts Unicode emoji characters directly as reactionType.
    The frontend sends either an emoji char or a named key — normalise to emoji.
    """
    if not req.reaction or len(req.reaction.encode()) > 32:
        raise HTTPException(status_code=400, detail="reaction must be a non-empty emoji character")
    if req.action not in ("add", "remove"):
        raise HTTPException(status_code=400, detail="action must be 'add' or 'remove'")
    # Frontend may send named key ("like") or emoji ("👍") — Graph needs emoji char
    reaction_emoji = _REACTION_KEY_TO_EMOJI.get(req.reaction, req.reaction)
    try:
        import httpx as _httpx
        token = _get_graph_token()
        if not token:
            raise HTTPException(status_code=401, detail="No Graph access token available. Re-authenticate via Settings.")
        action_path = "setReaction" if req.action == "add" else "unsetReaction"
        encoded_chat = urllib.parse.quote(chat_id, safe="")
        url = f"https://graph.microsoft.com/v1.0/chats/{encoded_chat}/messages/{message_id}/{action_path}"
        resp = _httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"reactionType": reaction_emoji},
            timeout=15,
        )
        print(f"[reactions] {req.action} emoji_bytes={reaction_emoji.encode()!r} -> HTTP {resp.status_code}", flush=True)
        if resp.status_code in (200, 201, 204):
            return {"ok": True}
        raise HTTPException(status_code=resp.status_code, detail=f"Graph API: {resp.text[:300]}")
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


@router.post("/api/teams/chats/{chat_id}/mark-read")
async def tp_teams_mark_read(chat_id: str):
    """Mark a chat as read by advancing the consumption horizon to now."""
    import time as _time
    try:
        now_ms = int(_time.time() * 1000)
        horizon = f"{now_ms};{now_ms};0"
        _skype_set_consumption_horizon(chat_id, horizon)
        print(f"[mark-read] chat {chat_id[:30]}... -> ok", flush=True)
        return {"ok": True}
    except Exception as e:
        print(f"[mark-read] FAILED: {e}", flush=True)
        return {"ok": False, "detail": str(e)}


@router.post("/api/teams/chats/{chat_id}/mark-unread")
async def tp_teams_mark_unread(chat_id: str):
    """Mark a chat as unread by resetting the consumption horizon to zero."""
    try:
        _skype_set_consumption_horizon(chat_id, "0;0;0")
        print(f"[mark-unread] chat {chat_id[:30]}... -> ok", flush=True)
        return {"ok": True}
    except Exception as e:
        print(f"[mark-unread] FAILED: {e}", flush=True)
        return {"ok": False, "detail": str(e)}


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


class TeamsHostedImage(BaseModel):
    contentType: str
    contentBytes: str  # base64


class TeamsSendRequest(BaseModel):
    message: str
    hosted_images: list[TeamsHostedImage] = []
    mentions: list[dict] = []


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
        content = req.message
        if req.hosted_images:
            _ASM = "https://us-api.asm.skype.com"
            _ASM_UA = "com.microsoft.teams2/1.0"
            _asm_headers = {
                "Authorization": f"skype_token {skype_token}",
                "Content-Type": "application/json",
                "User-Agent": _ASM_UA,
            }
            for i, img in enumerate(req.hosted_images):
                raw = _b64.b64decode(img.contentBytes)
                # Step 1: create the object and get a permUrl
                create_resp = _httpx.post(
                    f"{_ASM}/v1/objects",
                    headers=_asm_headers,
                    json={"type": "pish/image", "permissions": {"everyone": ["read"]}},
                    timeout=15,
                )
                create_resp.raise_for_status()
                obj_id = create_resp.json().get("id", "")
                if not obj_id:
                    raise HTTPException(status_code=502, detail="ASM upload: no object ID returned")
                # Step 2: upload the image bytes
                upload_resp = _httpx.put(
                    f"{_ASM}/v1/objects/{obj_id}/content/imgpsh",
                    headers={"Authorization": f"skype_token {skype_token}", "Content-Type": img.contentType, "User-Agent": _ASM_UA},
                    content=raw,
                    timeout=30,
                )
                upload_resp.raise_for_status()
                # Step 3: replace the hostedContents placeholder with the ASM view URL
                cdn_url = f"{_ASM}/v1/objects/{obj_id}/views/imgo"
                placeholder = f"../hostedContents/{i + 1}/$value"
                content = content.replace(placeholder, cdn_url)
                print(f"[teams-send] ASM upload ok: obj={obj_id[:20]}", flush=True)

        encoded_chat = urllib.parse.quote(chat_id, safe="")
        url = f"{messaging_service}/users/ME/conversations/{encoded_chat}/messages"

        # Build Skype body — always RichText/Html so emoji are preserved.
        # Plain "Text" messagetype silently strips Unicode emoji in the Skype chatsvc API.
        has_mentions = 'itemtype="http://schema.skype.com/Mention"' in content
        if "<" not in content:
            content = f"<div>{content}</div>"
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
        content = req.message
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
    """Fetch messages from a Teams channel (chronological order)."""
    EMOJI_TO_NAME = {"\U0001f44d": "like", "\u2764\ufe0f": "heart", "\U0001f602": "laugh", "\U0001f62e": "surprised", "\U0001f622": "sad", "\U0001f621": "angry"}
    try:
        from skills._m365.helpers import make_teams_gc, html_to_text, get_cached_me
        gc = make_teams_gc()
        me = get_cached_me(gc)
        my_id = me.get("id", "")
        my_name = me.get("displayName", "")
        result = gc.get(f"/teams/{team_id}/channels/{channel_id}/messages", {"$top": str(top)})
        raw = result.get("value", [])
        messages = []
        for m in raw:
            if m.get("messageType", "message") != "message":
                continue
            sender = ((m.get("from") or {}).get("user") or {})
            sender_id = sender.get("id", "")
            sender_name = sender.get("displayName", "")
            is_mine = bool(
                (my_id and sender_id and sender_id == my_id) or
                (my_name and sender_name and sender_name == my_name)
            )
            body_content = (m.get("body") or {}).get("content", "")
            content_type = (m.get("body") or {}).get("contentType", "text")
            body_html = body_content if content_type == "html" else ""
            body_text = html_to_text(body_content, max_len=2000) if content_type == "html" else body_content
            reactions_raw = m.get("reactions") or []
            reactions = []
            for r in reactions_raw:
                rtype = EMOJI_TO_NAME.get(r.get("reactionType", ""), r.get("reactionType", ""))
                ruser = ((r.get("user") or {}).get("user") or {}).get("displayName") or ""
                if my_name and ruser and ruser == my_name:
                    ruser = "You"
                reactions.append({"type": rtype, "user": ruser})
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
            })
        messages.reverse()
        return {"messages": messages, "my_id": my_id, "my_name": my_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
