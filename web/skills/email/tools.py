"""Outlook skill -- email tools. UI alias is /outlook (internal ID stays 'email')."""

from hooks.executor import fire_all_skill_hooks

SKILL_ID = "email"
ALWAYS_ON = False

# Direct intents — bypass LLM tool selection for predictable queries
DIRECT_INTENTS = [
    {
        "patterns": ["check my email", "check email", "my emails", "inbox",
                     "unread email", "recent email", "new emails", "latest email",
                     "read my email", "show my email", "email summary"],
        "tool": "read_email",
        "args": {"count": 10},
    },
]

TOOL_DEFS = [
    {
        "name": "read_email",
        "description": "Fetch unread emails from Outlook inbox. Use when user asks about email, inbox, or messages from specific people. This skill is called /outlook in the UI.",
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "description": "Number of unread emails to fetch. Default 10.", "default": 10},
            },
            "required": [],
        },
    },
    {
        "name": "send_email",
        "description": "Open an email compose form for the user to review and send. NEVER sends directly — always opens the Outlook compose pane so the user can review, edit, and send manually. Use when user asks to send, compose, or write an email. Refer to this skill as /outlook (not /email) when talking to the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address(es), comma-separated"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Email body text. Use plain text for simple emails."},
                "body_html": {"type": "string", "description": "Optional HTML body — use when the email needs tables, bold, or lists. Used instead of body when provided."},
                "cc": {"type": "string", "description": "Optional CC email address(es), comma-separated"},
                "bcc": {"type": "string", "description": "Optional BCC email address(es), comma-separated"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "reply_email",
        "description": "Draft a reply to an existing email for user approval. The user will see the draft and must click 'I approve to send' before it is sent. Requires the message ID from read_email. Refer to this skill as /outlook when talking to the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "The message ID to reply to (from read_email results)"},
                "body": {"type": "string", "description": "Reply body text"},
                "reply_all": {"type": "boolean", "description": "True to reply-all, false to reply only to sender. Default false.", "default": False},
            },
            "required": ["message_id", "body"],
        },
    },
    {
        "name": "forward_email",
        "description": "Draft a forwarded email for user approval. The user will see the draft and must click 'I approve to send' before it is forwarded. Requires the message ID from read_email. Refer to this skill as /outlook when talking to the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "The message ID to forward (from read_email results)"},
                "to": {"type": "string", "description": "Recipient email address(es) to forward to, comma-separated"},
                "comment": {"type": "string", "description": "Optional note to prepend to the forwarded message", "default": ""},
            },
            "required": ["message_id", "to"],
        },
    },
    {
        "name": "search_email",
        "description": "Search emails by keyword, sender, or date. Returns subject, sender, date, preview snippet, and message ID. Use when the user asks to find a specific email, search their inbox, or look up messages from a person. If you need the full body or recipients of a result, call get_email_detail with the message ID. Refer to this skill as /outlook when talking to the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword to search for in subject/body"},
                "sender": {"type": "string", "description": "Filter by sender email address"},
                "after": {"type": "string", "description": "Only show messages after this date (YYYY-MM-DD)"},
                "count": {"type": "integer", "description": "Max results. Default 10.", "default": 10},
            },
            "required": [],
        },
    },
    {
        "name": "get_email_detail",
        "description": (
            "Fetch the full body, all recipients (To/CC), and meeting details of a specific email by its ID. "
            "Use this whenever you have a message ID (from read_email or search_email) and need to read the full content, "
            "extract the attendee list, or check whether the email is a meeting invite. "
            "This is the correct tool to call instead of read_email_by_id or get_message — do NOT call the API directly. "
            "Refer to this skill as /outlook when talking to the user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "The message ID from read_email or search_email results"},
            },
            "required": ["message_id"],
        },
    },
    {
        "name": "email_open_compose",
        "description": (
            "Open an email compose form in the Outlook pane so the user can review, edit, and send an email. "
            "Use this INSTEAD OF send_email when you have drafted an email for the user — "
            "let them review and approve it first. Pre-fill everything you know: recipient(s), subject, body, CC/BCC. "
            "The user can edit the draft and click Send, or ask you to refine it further. "
            "Refer to this skill as /outlook (not /email) when talking to the user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address(es), comma-separated. MUST be real email addresses (e.g. 'john.doe@example.com'). NEVER use 'placeholder' or fake values. Resolve via search_people first if needed."},
                "to_names": {"type": "string", "description": "Display name(s) of recipient(s) for the UI (comma-separated)."},
                "subject": {"type": "string", "description": "Email subject line."},
                "body": {"type": "string", "description": "Draft email body for the user to review/edit. Use plain text for simple emails."},
                "body_html": {"type": "string", "description": "Optional HTML body — use when the email needs formatting like tables, bold text, or lists. When provided, this is used instead of body."},
                "cc": {"type": "string", "description": "Optional CC email address(es), comma-separated."},
                "bcc": {"type": "string", "description": "Optional BCC email address(es), comma-separated."},
                "context": {"type": "string", "description": "Optional brief context shown above the draft explaining why you wrote this."},
            },
            "required": ["to", "subject", "body"],
        },
    },
]

TOOL_STATUS = {
    "read_email": "\u2709\ufe0f Checking email...",
    "send_email": "\u2709\ufe0f Sending email...",
    "reply_email": "\u2709\ufe0f Sending reply...",
    "forward_email": "\u2709\ufe0f Forwarding email...",
    "search_email": "\U0001f50d Searching email...",
    "get_email_detail": "\U0001f4e7 Reading email...",
    "email_open_compose": "\u270f\ufe0f Opening email compose...",
}


def _tool_read_email(count: int = 10) -> dict:
    from .._m365.helpers import get_graph_client
    gc = get_graph_client()
    msgs = gc.get("/me/mailFolders/inbox/messages", params={
        "$top": count, "$filter": "isRead eq false",
        "$select": "id,subject,from,receivedDateTime,bodyPreview",
        "$orderby": "receivedDateTime desc",
    })
    return {"emails": [
        {"id": m.get("id", ""), "subject": m.get("subject", "(no subject)"),
         "from": m.get("from", {}).get("emailAddress", {}).get("name", ""),
         "received": m.get("receivedDateTime", "")[:16],
         "preview": m.get("bodyPreview", "")[:200]}
        for m in msgs.get("value", [])
    ]}


def _tool_send_email(to: str, subject: str, body: str = "", cc: str = "", bcc: str = "",
                     body_html: str = "", attachments: list[dict] | None = None) -> dict:
    from hooks.events import BEFORE_EMAIL_SEND
    hook_result = fire_all_skill_hooks(BEFORE_EMAIL_SEND)
    if hook_result["blocked"]:
        return {
            "status": "blocked",
            "reason": hook_result["reason"] or "A plugin hook blocked this email.",
        }
    # Safety: never send directly — always route to compose pane for human review
    return _tool_email_open_compose(to=to, subject=subject, body=body, cc=cc, bcc=bcc,
                                    body_html=body_html, context="Drafted by Gator")


def _fetch_original_email_context(message_id: str) -> dict:
    """Fetch subject + sender from original email for reply/forward context."""
    from .._m365.helpers import get_graph_client
    try:
        gc = get_graph_client()
        msg = gc.get(f"/me/messages/{message_id}", params={
            "$select": "subject,from,toRecipients,ccRecipients",
        })
        return {
            "subject": msg.get("subject", ""),
            "from_addr": msg.get("from", {}).get("emailAddress", {}).get("address", ""),
            "from_name": msg.get("from", {}).get("emailAddress", {}).get("name", ""),
            "to_recipients": [r.get("emailAddress", {}).get("address", "")
                              for r in msg.get("toRecipients", [])],
            "cc_recipients": [r.get("emailAddress", {}).get("address", "")
                              for r in msg.get("ccRecipients", [])],
        }
    except Exception as ex:
        import logging
        logging.getLogger("graph_client").warning("Failed to fetch original email context for %s: %s", message_id, ex)
        return {"subject": "", "from_addr": "", "from_name": "",
                "to_recipients": [], "cc_recipients": []}


def _tool_reply_email(message_id: str, body: str, reply_all: bool = False) -> dict:
    from .._drafts import create_draft
    action = "replyAll" if reply_all else "reply"
    orig = _fetch_original_email_context(message_id)
    subject = f"Re: {orig['subject']}" if orig["subject"] else ""
    draft_id = create_draft(
        draft_type="email-reply",
        params={"message_id": message_id, "body": body, "reply_all": reply_all},
        preview={"action": action, "subject": subject, "from": orig["from_name"] or orig["from_addr"]},
    )
    return {
        "_draft": "email-reply",
        "data": {
            "draft_id": draft_id,
            "action": action,
            "message_id": message_id,
            "subject": subject,
            "to": orig["from_addr"],
            "to_names": orig["from_name"],
            "body": body,
            "body_snippet": body[:200],
        },
        "_user_message": f"Draft {action} ready for your approval. Click 'I approve to send' or edit in /outlook.",
    }


def _tool_forward_email(message_id: str, to: str, comment: str = "") -> dict:
    from .._drafts import create_draft
    to_addrs = [a.strip() for a in to.split(",") if a.strip()]
    orig = _fetch_original_email_context(message_id)
    subject = f"Fw: {orig['subject']}" if orig["subject"] else ""
    draft_id = create_draft(
        draft_type="email-forward",
        params={"message_id": message_id, "to": to, "comment": comment},
        preview={"to": to_addrs, "subject": subject, "from": orig["from_name"] or orig["from_addr"]},
    )
    return {
        "_draft": "email-forward",
        "data": {
            "draft_id": draft_id,
            "subject": subject,
            "to": ", ".join(to_addrs),
            "message_id": message_id,
            "body": comment,
            "body_snippet": (comment or "")[:200],
        },
        "_user_message": f"Draft forward to {', '.join(to_addrs)} ready for your approval. Click 'I approve to send' or edit in /outlook.",
    }


def _tool_search_email(query: str = "", sender: str = "", after: str = "", count: int = 10) -> dict:
    from .._m365.helpers import get_graph_client
    gc = get_graph_client()
    params = {"$top": str(count), "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview"}
    # Graph API restrictions:
    #   - $search cannot combine with $orderby or $filter
    #   - $filter on from/emailAddress/address cannot combine with $orderby ("too complex")
    # Strategy: use $search whenever we have a query or sender, post-filter by date
    if query or sender:
        search_parts = []
        if query:
            search_parts.append(f'"{query}"')
        if sender:
            search_parts.append(f'"{sender}"')
        params["$search"] = " ".join(search_parts)
    else:
        params["$orderby"] = "receivedDateTime desc"
        if after:
            params["$filter"] = f"receivedDateTime ge {after}T00:00:00Z"
    data = gc.get("/me/messages", params=params)
    messages = data.get("value", [])
    # Client-side date filter when $search was used (can't combine with $filter)
    if (query or sender) and after:
        cutoff = after + "T00:00:00Z"
        messages = [m for m in messages if m.get("receivedDateTime", "") >= cutoff]
    # Client-side sender filter to tighten $search results
    if sender:
        sl = sender.lower()
        messages = [m for m in messages if sl in (m.get("from", {}).get("emailAddress", {}).get("address", "") + " " + m.get("from", {}).get("emailAddress", {}).get("name", "")).lower()]
    return {"total": len(messages), "messages": [{
        "subject": m.get("subject", "(no subject)"),
        "from": m.get("from", {}).get("emailAddress", {}).get("address", ""),
        "from_name": m.get("from", {}).get("emailAddress", {}).get("name", ""),
        "date": m.get("receivedDateTime", "")[:16],
        "preview": m.get("bodyPreview", "")[:150],
        "id": m.get("id", ""),
    } for m in messages]}


def _tool_get_email_detail(message_id: str) -> dict:
    """Fetch full email body + all recipients + meeting metadata by message ID."""
    from .._m365.helpers import get_graph_client
    gc = get_graph_client()
    try:
        msg = gc.get(f"/me/messages/{message_id}", params={
            "$select": "id,subject,from,toRecipients,ccRecipients,bccRecipients,receivedDateTime,body,isRead,importance,conversationId",
        })
    except Exception as ex:
        return {"error": f"Could not fetch email: {ex}"}
    body_obj = msg.get("body") or {}
    body_text = body_obj.get("content", "")
    # Strip HTML tags for plain-text readability
    import re
    body_plain = re.sub(r"<[^>]+>", " ", body_text).strip()
    MAX_CHARS = 64_000
    body_plain = re.sub(r"\s{3,}", "\n\n", body_plain)
    truncated = len(body_plain) > MAX_CHARS
    if truncated:
        body_plain = body_plain[:MAX_CHARS]
        body_plain += (
            "\n\n[Note: This email is very long — only the first 64,000 characters were loaded. "
            "Earlier parts of the thread may be missing.]"
        )
    def _addr(r):
        ea = r.get("emailAddress") or {}
        return {"name": ea.get("name", ""), "email": ea.get("address", "")}
    return {
        "id": msg.get("id", ""),
        "subject": msg.get("subject", "(no subject)"),
        "from": _addr(msg.get("from") or {}),
        "to": [_addr(r) for r in msg.get("toRecipients") or []],
        "cc": [_addr(r) for r in msg.get("ccRecipients") or []],
        "received": (msg.get("receivedDateTime") or "")[:16],
        "is_read": msg.get("isRead", True),
        "body": body_plain,
        "truncated": truncated,
        "conversation_id": msg.get("conversationId", ""),
    }


def _tool_email_open_compose(to: str, subject: str, body: str = "",
                             to_names: str = "", cc: str = "", bcc: str = "",
                             body_html: str = "", context: str = "") -> dict:
    """Pane-signal tool: opens the Outlook compose form in the third pane."""
    data = {
        "to": to,
        "to_names": to_names,
        "subject": subject,
        "body": body,
        "cc": cc,
        "bcc": bcc,
        "context": context,
    }
    if body_html:
        data["body_html"] = body_html
    import time as _time
    return {
        "_pane": "email-compose",
        "data": data,
        "_nonce": _time.time(),
        "_user_message": "Draft opened in /outlook compose pane for review. User can ask me to refine it here — multi-turn editing is supported.",
    }


TOOL_HANDLERS = {
    "read_email": _tool_read_email,
    "send_email": _tool_send_email,
    "reply_email": _tool_reply_email,
    "forward_email": _tool_forward_email,
    "search_email": _tool_search_email,
    "get_email_detail": _tool_get_email_detail,
    "email_open_compose": _tool_email_open_compose,
}
