#!/usr/bin/env python3
"""Read Teams chat messages via FOCI token swap + Skype API.

Uses the same approach as the Teams Desktop client: swap the existing refresh
token for an api.spaces.skype.com token, then exchange that for a Skype token
to hit Teams' internal messaging APIs.

Usage:
    python3 read_chats.py                    # list recent chats
    python3 read_chats.py --chat-id <id>     # messages from a specific chat
    python3 read_chats.py --limit 30         # control page size
    python3 read_chats.py --json             # JSON output
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CLIENT_ID = "1fec8e78-bce4-4aaf-ab1b-5451cc387264"  # Teams Desktop — FOCI family-1
TOKEN_FILE = Path.home() / ".config" / "microsoft-graph" / "token.json"
SKYPE_TOKEN_FILE = Path.home() / ".config" / "microsoft-graph" / "skype_token.json"
AUTHZ_URL = "https://teams.microsoft.com/api/authsvc/v1.0/authz"


# ── Token management ──────────────────────────────────────────────────────────

def _load_graph_tokens() -> dict:
    if not TOKEN_FILE.exists():
        raise RuntimeError("Not authenticated. Sign in via Settings first.")
    return json.loads(TOKEN_FILE.read_text())


def _load_cached_skype_token() -> dict | None:
    if not SKYPE_TOKEN_FILE.exists():
        return None
    try:
        data = json.loads(SKYPE_TOKEN_FILE.read_text())
        if time.time() < data.get("expires_at", 0) - 300:  # 5-min buffer
            return data
    except Exception:
        pass
    return None


def _save_skype_token(skype_token: str, messaging_service: str, expires_in: int, global_service: str = "") -> None:
    SKYPE_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SKYPE_TOKEN_FILE.write_text(json.dumps({
        "skype_token": skype_token,
        "messaging_service": messaging_service,
        "global_service": global_service,
        "expires_at": time.time() + expires_in,
    }, indent=2))
    os.chmod(str(SKYPE_TOKEN_FILE), 0o600)


def _foci_swap(refresh_token: str, tenant_id: str) -> str:
    """Exchange the Graph refresh token for an api.spaces.skype.com access token."""
    data = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": "https://api.spaces.skype.com/.default offline_access",
    }).encode()
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["access_token"]


def _exchange_skype_token(spaces_token: str) -> tuple[str, str]:
    """Exchange api.spaces.skype.com token for Skype token + regional messaging URL."""
    req = urllib.request.Request(
        AUTHZ_URL,
        data=b'""',
        method="POST",
        headers={
            "Authorization": f"Bearer {spaces_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        d = json.loads(resp.read())
    skype_token = d["tokens"]["skypeToken"]
    gtms = d.get("regionGtms", {})
    messaging_service = gtms["chatService"] + "/v1"
    # chatServiceAfd is the AFD global routing endpoint — handles cross-region @unq.gbl.spaces threads
    global_service = (gtms.get("chatServiceAfd") or gtms.get("chatService") or "").rstrip("/") + "/v1"
    expires_in = d["tokens"].get("expiresIn", 86400)
    _save_skype_token(skype_token, messaging_service, expires_in, global_service)
    return skype_token, messaging_service


def get_auth() -> tuple[str, str]:
    """Return (skype_token, messaging_service_url), using cache when valid."""
    cached = _load_cached_skype_token()
    if cached:
        return cached["skype_token"], cached["messaging_service"]

    token_data = _load_graph_tokens()
    refresh_token = token_data.get("refresh_token", "")
    tenant_id = token_data.get("tenant_id", "organizations")
    if not refresh_token:
        raise RuntimeError("No refresh token in cache. Re-authenticate via Settings.")

    spaces_token = _foci_swap(refresh_token, tenant_id)
    return _exchange_skype_token(spaces_token)


def get_global_service() -> str:
    """Return the global/cross-region chatsvc URL (amsV2), or empty string if unknown."""
    cached = _load_cached_skype_token()
    return (cached or {}).get("global_service", "")


# ── Teams internal API calls ──────────────────────────────────────────────────

def _get(url: str, skype_token: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"X-Skypetoken": skype_token, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _sender(raw: str) -> str:
    """Extract a readable sender name from a Skype MRI like '8:user@domain'."""
    return raw.split(":")[-1] if raw else ""


_PREVIEW_MESSAGETYPES = {"Text", "RichText/Html", "RichText/Media_Video", "RichText/Media_AudioMsg"}

# Deleted messages in Teams keep their original messagetype but replace content with
# the sender's MRI or AAD object ID (e.g. "dc59cb67-087b-4ea0-98b7-77cf070e55a8:").
# Filter out content that is just a bare GUID (with or without trailing colon/whitespace).
_GUID_ONLY_RE = re.compile(
    r"^\s*[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:?\s*$",
    re.IGNORECASE,
)
# GUID prefix before actual message text (e.g. "dc59cb67-...: Sounds good")
_GUID_PREFIX_RE = re.compile(
    r"^\s*[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:\s*",
    re.IGNORECASE,
)


def list_chats(skype_token: str, messaging_service: str, limit: int = 30, backward_link: str = "") -> tuple[list[dict], str]:
    """Fetch up to `limit` recent conversations, or follow `backward_link` for older ones.

    Returns (chats, backward_link) where backward_link is from _metadata.backwardLink.
    Pass it back on the next call to page to older conversations.
    """
    if backward_link:
        url = backward_link
    else:
        url = (
            f"{messaging_service}/users/ME/conversations"
            f"?pageSize={limit}&view=msnp24Equivalent"
            f"&targetType=Passport|Skype|Lync|Thread|PSTN|Agent|ShortMessage"
        )
    data = _get(url, skype_token)
    chats = []
    for conv in data.get("conversations", []):
        last = conv.get("lastMessage", {})
        props = conv.get("properties", {})
        thread_props = conv.get("threadProperties", {})
        # Extract other-person's MRI for DMs (addedBy = 8:orgid:{guid} of the initiating party)
        added_by_mri = props.get("addedBy", "")
        # Only use last_message content when it comes from a real user message type.
        # System events (ThreadActivity/*), call events (Event/Call), deleted messages,
        # and bot cards leave garbage content (raw MRIs, GUIDs, or empty HTML) that
        # should never appear in the chat list preview.
        last_msgtype = last.get("messagetype", "")
        if last_msgtype in _PREVIEW_MESSAGETYPES:
            last_message = _strip_html(last.get("content", ""))
            # Deleted messages keep their messagetype but replace content with the
            # sender's AAD object ID / MRI (e.g. "dc59cb67-...:").  Suppress those.
            if _GUID_ONLY_RE.match(last_message):
                last_message = ""
            elif _GUID_PREFIX_RE.match(last_message):
                last_message = _GUID_PREFIX_RE.sub("", last_message)
        else:
            last_message = ""
        chats.append({
            "id": conv.get("id", ""),
            "type": conv.get("threadtype", ""),
            "topic": (thread_props.get("topic", "")
                      or thread_props.get("spaceThreadTopic", "")
                      or conv.get("topic", "")),
            "last_message": last_message,
            "last_sender": last.get("imdisplayname", "") or _sender(last.get("from", "")),
            "last_sender_mri": _sender(last.get("from", "")),
            "last_time": last.get("composetime", ""),
            "consumption_horizon": props.get("consumptionhorizon", ""),
            "thread_type": thread_props.get("threadType", conv.get("threadtype", "")),
            "added_by_mri": added_by_mri,
            # Member count for distinguishing 2-person group threads from real groups.
            # Skype's conversations endpoint may expose this under several keys; try each.
            "member_count": (
                len(thread_props.get("members", []) or [])
                or len(conv.get("members", []) or [])
                or int(thread_props.get("memberCount") or 0)
            ),
        })
    meta = data.get("_metadata") or {}
    next_backward_link = meta.get("backwardLink", "")
    return chats, next_backward_link


def read_messages(chat_id: str, skype_token: str, messaging_service: str, limit: int = 20, backward_link: str = "") -> tuple[list[dict], str]:
    """Fetch up to `limit` messages, or follow `backward_link` to page to older messages.

    Returns (messages, backward_link) where backward_link is the full URL from
    _metadata.backwardLink — pass it back on the next call to load older messages.
    Returns "" for backward_link when no more history exists.
    """
    if backward_link:
        url = backward_link
    else:
        encoded_id = urllib.parse.quote(chat_id, safe="")
        url = (
            f"{messaging_service}/users/ME/conversations/{encoded_id}/messages"
            f"?pageSize={limit}&view=msnp24Equivalent|supportsMessageProperties"
        )
    data = _get(url, skype_token)
    messages = []
    for msg in data.get("messages", []):
        # Skip system events (member joins, topic changes, etc.)
        if msg.get("messagetype", "").startswith("ThreadActivity"):
            continue
        from_url = msg.get("from", "")
        # Extract MRI from URL: .../contacts/8:user@domain → 8:user@domain
        from_mri = from_url.split("/contacts/")[-1] if "/contacts/" in from_url else _sender(from_url)
        content_raw = msg.get("content", "")
        # Parse reactions from properties.emotions (may be dict, JSON string, or list)
        props = msg.get("properties") or {}
        if isinstance(props, str):
            try:
                props = json.loads(props)
            except Exception:
                props = {}
        if not isinstance(props, dict):
            props = {}
        emotions_raw = props.get("emotions", [])
        if isinstance(emotions_raw, str):
            try:
                emotions_raw = json.loads(emotions_raw)
            except Exception:
                emotions_raw = []
        # Parse mentions: [{itemid, mri, displayName}] — itemid matches span's itemid attr
        mentions_raw = props.get("mentions", [])
        if isinstance(mentions_raw, str):
            try:
                mentions_raw = json.loads(mentions_raw)
            except Exception:
                mentions_raw = []
        # Build itemid → aad_guid map for use when rendering <at> tags
        mention_map: dict[str, str] = {}
        for mention in (mentions_raw if isinstance(mentions_raw, list) else []):
            iid = str(mention.get("itemid", ""))
            mri = mention.get("mri", "")  # "8:orgid:{aad_guid}"
            guid = mri.split(":")[-1] if mri else ""
            if iid and guid:
                mention_map[iid] = guid
        messages.append({
            "id": msg.get("id", ""),
            "from": _sender(from_url),
            "from_mri": from_mri,
            "sender_name": msg.get("imdisplayname", "") or _sender(from_url),
            "content": _strip_html(content_raw),
            "content_html": content_raw,
            "time": msg.get("composetime", ""),
            "edit_time": msg.get("edittime", ""),
            "emotions_raw": emotions_raw if isinstance(emotions_raw, list) else [],
            "mention_map": mention_map,
        })
    # _metadata.backwardLink is the full URL to fetch the next (older) page
    meta = data.get("_metadata") or {}
    next_backward_link = meta.get("backwardLink", "")
    return messages, next_backward_link


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Read Teams chats via Skype token")
    parser.add_argument("--chat-id", help="Read messages from a specific chat ID")
    parser.add_argument("--limit", type=int, default=20, help="Number of items to fetch (default: 20)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        skype_token, messaging_service = get_auth()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if args.chat_id:
        messages, backward_link = read_messages(args.chat_id, skype_token, messaging_service, args.limit)
        if args.json:
            print(json.dumps({"chat_id": args.chat_id, "messages": messages}, indent=2))
        else:
            if not messages:
                print("No messages found.")
                return
            for m in messages:
                ts = m["time"][:19].replace("T", " ") if m["time"] else "?"
                print(f"[{ts}] {m['from']}: {m['content']}")
    else:
        chats, _ = list_chats(skype_token, messaging_service, args.limit)
        if args.json:
            print(json.dumps({"total": len(chats), "chats": chats}, indent=2))
        else:
            if not chats:
                print("No chats found.")
                return
            print(f"Recent chats ({len(chats)}):\n")
            for c in chats:
                topic = c["topic"] or c["type"] or c["id"][:30]
                preview = c["last_message"][:70] if c["last_message"] else "(no preview)"
                sender = f"{c['last_sender']}: " if c["last_sender"] else ""
                print(f"  {topic}")
                print(f"    {sender}{preview}")
                print(f"    ID: {c['id']}\n")


if __name__ == "__main__":
    main()
