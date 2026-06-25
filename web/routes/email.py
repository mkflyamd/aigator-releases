"""Email route group -- inbox, message detail, reply, forward, send, drafts, delta sync."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import shared
from security import verify_csrf
from skills._m365.helpers import GraphClient, html_to_text

router = APIRouter()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _apply_delta_changes(state: dict, result: dict):
    """Merge Graph delta response into stored item list."""
    items_by_id = {m["id"]: m for m in state["items"] if "id" in m}
    for item in result.get("value", []):
        item_id = item.get("id", "")
        if not item_id:
            continue
        if "@removed" in item:
            items_by_id.pop(item_id, None)
        else:
            items_by_id[item_id] = item
    state["items"] = list(items_by_id.values())


def _format_email_message(m: dict) -> dict:
    """Convert a raw Graph message dict to the API response format."""
    from_obj = (m.get("from") or {}).get("emailAddress") or {}
    return {
        "id": m.get("id", ""),
        "subject": m.get("subject", ""),
        "from_name": from_obj.get("name", ""),
        "from_email": from_obj.get("address", ""),
        "received_at": m.get("receivedDateTime", ""),
        "preview": (m.get("bodyPreview") or "")[:120],
        "is_read": m.get("isRead", True),
        "has_attachments": m.get("hasAttachments", False),
    }


# ── Pydantic Models ───────────────────────────────────────────────────────────

class EmailReadRequest(BaseModel):
    id: str


class MarkReadRequest(BaseModel):
    is_read: bool = True


class MeetingRespondRequest(BaseModel):
    response: str  # "accept", "decline", or "tentativelyAccept"
    event_id: str = ""  # preferred: use /me/events/{id}/accept when available
    send_response: bool = True


class EmailReplyRequest(BaseModel):
    message_id: str
    body: str
    reply_all: bool = False
    to: str = ""   # optional comma-separated override; createReply sets defaults if blank
    cc: str = ""
    bcc: str = ""


class EmailForwardRequest(BaseModel):
    message_id: str
    to: str  # comma-separated emails
    cc: str = ""  # comma-separated emails
    bcc: str = ""  # comma-separated emails
    comment: str = ""


class EmailAttachment(BaseModel):
    name: str
    contentType: str = "application/octet-stream"
    contentBytes: str  # base64, no data URI prefix


class EmailSendRequest(BaseModel):
    to: str
    subject: str
    body: str
    cc: str = ""
    bcc: str = ""
    attachments: list[EmailAttachment] = []


# ── Action Routes ──────────────────────────────────────────────────────────────

@router.post("/api/actions/email")
async def action_email():
    try:
        gc = GraphClient()
        inbox = gc.get("/me/mailFolders/inbox")
        unread = inbox.get("unreadItemCount", 0)
        total = inbox.get("totalItemCount", 0)

        msgs = gc.get("/me/mailFolders/inbox/messages", params={
            "$top": 5,
            "$filter": "isRead eq false",
            "$select": "id,subject,from,receivedDateTime",
        })
        items = msgs.get("value", [])
        recent = [
            {
                "id": m.get("id", ""),
                "subject": m.get("subject", "(no subject)"),
                "from": m.get("from", {}).get("emailAddress", {}).get("name", ""),
                "received": m.get("receivedDateTime", "")[:10],
            }
            for m in items
        ]
        return {"unread": unread, "total": total, "recent": recent}
    except BaseException as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/actions/email/read")
async def action_email_read(req: EmailReadRequest):
    try:
        gc = GraphClient()
        msg = gc.get(f"/me/messages/{req.id}", params={
            "$select": "id,subject,from,receivedDateTime,body,toRecipients"
        })
        return {
            "id": msg.get("id", req.id),
            "subject": msg.get("subject", ""),
            "from": msg.get("from", {}).get("emailAddress", {}).get("name", ""),
            "from_email": msg.get("from", {}).get("emailAddress", {}).get("address", ""),
            "received": msg.get("receivedDateTime", "")[:10],
            "to": [r["emailAddress"]["name"] for r in msg.get("toRecipients", [])],
            "body": html_to_text(msg.get("body", {}).get("content", "")),
            "content_type": "text",
        }
    except BaseException as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Inbox & Message Routes ────────────────────────────────────────────────────

@router.get("/api/email/inbox")
async def tp_email_inbox(skip: int = 0, top: int = 50, filter: str = "all", delta: bool = False):
    """Inbox list with full/unread filter, pagination, and optional delta sync."""
    try:
        gc = GraphClient()

        if not delta:
            # -- Legacy full-fetch path (backward compatible) --
            select = "id,subject,from,receivedDateTime,bodyPreview,isRead,importance,hasAttachments"
            params = {
                "$top": str(top),
                "$skip": str(skip),
                "$select": select,
                "$orderby": "receivedDateTime desc",
            }
            filters = []
            if filter == "unread":
                filters.append("isRead eq false")
            if filters:
                params["$filter"] = " and ".join(filters)
            result = gc.get("/me/mailFolders/inbox/messages", params)
            folder = gc.get("/me/mailFolders/inbox", {"$select": "unreadItemCount"})
            unread_count = folder.get("unreadItemCount", 0)
            messages = [_format_email_message(m) for m in result.get("value", [])]
            return {"messages": messages, "total_unread": unread_count}

        # -- Delta sync path --
        if "email" in shared._delta_unsupported:
            return await tp_email_inbox(skip, top, filter, delta=False)

        state = shared._delta_state.get("email")

        # Cold start: no delta state yet -- use fast non-delta path first
        if not state or not state.get("delta_link"):
            return await tp_email_inbox(skip, top, filter, delta=False)

        if state and state.get("delta_link"):
            # Incremental sync
            try:
                result = gc.get_absolute(state["delta_link"])
            except Exception as e:
                if "410" in str(e):
                    # Delta token expired -- fall back to initial sync
                    shared._delta_state.pop("email", None)
                    return await tp_email_inbox(skip, top, filter, delta=True)
                raise
            _apply_delta_changes(state, result)
            while "@odata.nextLink" in result:
                result = gc.get_absolute(result["@odata.nextLink"])
                _apply_delta_changes(state, result)
            if "@odata.deltaLink" in result:
                state["delta_link"] = result["@odata.deltaLink"]
        else:
            # Initial delta sync -- cap pages to avoid chasing hundreds of nextLinks
            _MAX_DELTA_PAGES = 5
            try:
                select = "id,subject,from,receivedDateTime,bodyPreview,isRead,importance,hasAttachments"
                result = gc.get("/me/mailFolders/inbox/messages/delta", {"$select": select})
                all_items = list(result.get("value", []))
                _pages = 1
                while "@odata.nextLink" in result and _pages < _MAX_DELTA_PAGES:
                    result = gc.get_absolute(result["@odata.nextLink"])
                    all_items.extend(result.get("value", []))
                    _pages += 1
                if _pages >= _MAX_DELTA_PAGES and "@odata.nextLink" in result:
                    print(f"[email] Delta init capped at {_pages} pages ({len(all_items)} items)", flush=True)
                state = {
                    "delta_link": result.get("@odata.deltaLink", result.get("@odata.nextLink", "")),
                    "items": all_items,
                }
                shared._delta_state["email"] = state
            except Exception as e:
                if "401" in str(e) or "403" in str(e):
                    raise
                shared._delta_unsupported.add("email")
                shared._save_delta_unsupported()
                print(f"[email] Delta not supported -- disabling: {e}", flush=True)
                return await tp_email_inbox(skip, top, filter, delta=False)

        # Cap stored items to prevent unbounded growth
        if len(state["items"]) > shared._DELTA_MAX_ITEMS:
            state["items"].sort(key=lambda m: m.get("receivedDateTime", ""), reverse=True)
            state["items"] = state["items"][:shared._DELTA_MAX_ITEMS]

        # Get unread count (cheap call)
        folder = gc.get("/me/mailFolders/inbox", {"$select": "unreadItemCount"})
        unread_count = folder.get("unreadItemCount", 0)

        # Apply filter, sort, paginate
        items = state["items"]
        if filter == "unread":
            items = [m for m in items if not m.get("isRead", True)]
        items.sort(key=lambda m: m.get("receivedDateTime", ""), reverse=True)
        page = items[skip:skip + top]
        messages = [_format_email_message(m) for m in page]
        return {"messages": messages, "total_unread": unread_count}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/email/search")
def tp_email_search(q: str = "", top: int = 25):
    """Full-mailbox search via Graph $search (searches all folders, not just inbox)."""
    if not q.strip():
        return {"messages": []}
    try:
        gc = GraphClient()
        # Graph $search on messages supports KQL: subject, from, body keywords
        result = gc.get("/me/messages", params={
            "$search": f'"{q}"',
            "$select": "id,subject,from,receivedDateTime,bodyPreview,isRead,importance,hasAttachments",
            "$top": str(min(top, 50)),
        })
        messages = [_format_email_message(m) for m in result.get("value", [])]
        return {"messages": messages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/email/messages/{message_id}")
def tp_email_message(message_id: str):
    """Full email with HTML body (not stripped to plain text)."""
    try:
        gc = GraphClient()
        select = "id,subject,from,toRecipients,ccRecipients,receivedDateTime,body,isRead,importance,conversationId"
        m = gc.get(f"/me/messages/{message_id}", {"$select": select})
        # Meeting detection — always check beta endpoint; plain invites have no subject prefix
        meeting_message_type = ""
        event_id = ""
        meeting_details = {}
        subject = m.get("subject", "")
        try:
            # No $select — the full beta message object includes meetingMessageType
            # (and iCalUId). Adding a $select that names an unsupported field would
            # make the whole request 400 and silently hide the RSVP buttons (#137).
            raw = gc.get(f"/me/messages/{message_id}", base_url="https://graph.microsoft.com/beta")
            meeting_message_type = raw.get("meetingMessageType") or ""
            ical_uid = raw.get("iCalUId") or ""
            if meeting_message_type:
                # Resolve the linked calendar event so RSVP targets /me/events/{id}/accept.
                # Primary: the /me/messages/{id}/event navigation property (direct link).
                # Fallback: look up the event by iCalUId — works when the navigation
                # property is missing (e.g. some recurring or forwarded invites).
                ev = None
                try:
                    ev = gc.get(
                        f"/me/messages/{message_id}/event",
                        {"$select": "id,subject,start,end,location,isAllDay,organizer,attendees,isOnlineMeeting,onlineMeeting,responseStatus"},
                    )
                except Exception:
                    ev = None
                _ev_select = "id,subject,start,end,location,isAllDay,organizer,attendees,isOnlineMeeting,onlineMeeting,responseStatus"
                if (not ev or not ev.get("id")):
                    try:
                        from skills._m365.helpers import get_cal_client
                        cal_gc = get_cal_client()
                        # By iCalUId when present…
                        if ical_uid:
                            found = cal_gc.get("/me/events", {
                                "$filter": f"iCalUId eq '{ical_uid}'", "$select": _ev_select, "$top": "1",
                            })
                            vals = found.get("value", [])
                            if vals:
                                ev = vals[0]
                        # …else by subject + start date (invites often lack iCalUId).
                        if (not ev or not ev.get("id")):
                            _subj = (raw.get("subject") or "").replace("'", "''")
                            _mstart = (raw.get("startDateTime") or {}).get("dateTime", "")[:10]
                            if _subj:
                                found = cal_gc.get("/me/events", {
                                    "$filter": f"subject eq '{_subj}'", "$select": _ev_select, "$top": "10",
                                })
                                cands = found.get("value", [])
                                ev = next(
                                    (c for c in cands if (c.get("start") or {}).get("dateTime", "")[:10] == _mstart),
                                    cands[0] if cands else ev,
                                )
                    except Exception:
                        ev = ev or None
                if ev:
                    event_id = ev.get("id", "")
                    if event_id:
                        meeting_details = {
                            "start": ev.get("start", {}),
                            "end": ev.get("end", {}),
                            "is_all_day": ev.get("isAllDay", False),
                            "location": (ev.get("location") or {}).get("displayName", ""),
                            "organizer": (ev.get("organizer") or {}).get("emailAddress", {}).get("name", ""),
                            "is_online": ev.get("isOnlineMeeting", False),
                            "join_url": (ev.get("onlineMeeting") or {}).get("joinUrl", ""),
                            "response_status": (ev.get("responseStatus") or {}).get("response", ""),
                            "attendees": [
                                {
                                    "name": (a.get("emailAddress") or {}).get("name", ""),
                                    "email": (a.get("emailAddress") or {}).get("address", ""),
                                    "status": (a.get("status") or {}).get("response", "none"),
                                }
                                for a in (ev.get("attendees") or [])
                            ],
                        }
        except Exception:
            pass
        from_obj = (m.get("from") or {}).get("emailAddress") or {}
        body_obj = m.get("body") or {}
        content_type = body_obj.get("contentType", "text")
        body_content = body_obj.get("content", "")
        body_html = body_content if content_type == "html" else ""
        body_text = html_to_text(body_content, max_len=3000) if content_type == "html" else body_content

        def _recip(r):
            ea = (r.get("emailAddress") or {})
            return {"name": ea.get("name", ""), "email": ea.get("address", "")}

        return {
            "id": m.get("id", ""),
            "subject": m.get("subject", ""),
            "from_name": from_obj.get("name", ""),
            "from_email": from_obj.get("address", ""),
            "to": [_recip(r) for r in (m.get("toRecipients") or [])],
            "cc": [_recip(r) for r in (m.get("ccRecipients") or [])],
            "received_at": m.get("receivedDateTime", ""),
            "body_html": body_html,
            "body_text": body_text,
            "is_read": m.get("isRead", True),
            "importance": m.get("importance", "normal"),
            "meeting_message_type": meeting_message_type,
            "event_id": event_id,
            "meeting_details": meeting_details,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/email/messages/{message_id}/respond")
async def tp_email_respond(message_id: str, req: MeetingRespondRequest):
    """Accept, decline, or tentatively accept a meeting invite.

    RSVP only works on the calendar EVENT (/me/events/{id}/accept), never on the
    mail message (/me/messages/{id}/accept returns 400 'segment accept' — #137).
    Resolves the event id from: (1) frontend-supplied event_id, (2) the
    /me/messages/{id}/event navigation property, (3) iCalUId lookup. Returns 422
    with a clear message if none resolve.
    """
    if req.response not in ("accept", "decline", "tentativelyAccept"):
        raise HTTPException(status_code=400, detail="response must be accept, decline, or tentativelyAccept")
    try:
        from skills._m365.helpers import get_graph_client
        gc = get_graph_client()

        def _post(path):
            try:
                gc.post(path, {"sendResponse": req.send_response})
            except RuntimeError as e:
                if "hasn't requested a response" in str(e) and req.send_response:
                    gc.post(path, {"sendResponse": False})
                else:
                    raise

        # RSVP must target the calendar EVENT (/me/events/{id}/{response}) — the
        # same path the Calendar pane uses. /me/messages/{id}/accept returns
        # "Resource not found for segment 'accept'" (#137), and the
        # eventMessageRequest type-cast doesn't expose the action either.
        # Resolve the event id from (in order):
        from skills._m365.helpers import get_cal_client
        cal_gc = get_cal_client()
        event_id = req.event_id

        # 1) /me/messages/{id}/event navigation property
        if not event_id:
            try:
                ev = gc.get(f"/me/messages/{message_id}/event", {"$select": "id"})
                event_id = ev.get("id", "") if ev else ""
            except Exception:
                event_id = ""

        # 2) iCalUId or subject+start match against the calendar. eventMessageRequest
        #    invites often lack iCalUId and the /event nav prop, but always carry a
        #    subject + startDateTime we can match (this is what makes RSVP work — #137).
        if not event_id:
            try:
                raw = gc.get(f"/me/messages/{message_id}", base_url="https://graph.microsoft.com/beta")
                ical = raw.get("iCalUId", "")
                if ical:
                    found = cal_gc.get("/me/events", {
                        "$filter": f"iCalUId eq '{ical}'", "$select": "id", "$top": "1",
                    })
                    vals = found.get("value", [])
                    if vals:
                        event_id = vals[0].get("id", "")
                if not event_id:
                    subj = (raw.get("subject") or "").replace("'", "''")
                    if subj:
                        found = cal_gc.get("/me/events", {
                            "$filter": f"subject eq '{subj}'",
                            "$select": "id,start",
                            "$top": "10",
                        })
                        cands = found.get("value", [])
                        msg_start = (raw.get("startDateTime") or {}).get("dateTime", "")[:10]
                        # Prefer the event whose start date matches the invite; else first match.
                        match = next(
                            (c for c in cands if (c.get("start") or {}).get("dateTime", "")[:10] == msg_start),
                            cands[0] if cands else None,
                        )
                        if match:
                            event_id = match.get("id", "")
            except Exception:
                pass

        if not event_id:
            raise HTTPException(
                status_code=422,
                detail="Could not find the calendar event for this invite. RSVP from the Calendar instead.",
            )

        _post(f"/me/events/{event_id}/{req.response}")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/email/messages/{message_id}/markread")
async def tp_email_markread(message_id: str, req: MarkReadRequest):
    """Mark an email as read or unread."""
    try:
        gc = GraphClient()
        gc.patch(f"/me/messages/{message_id}", {"isRead": req.is_read})
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/email/reply")
def tp_email_reply(req: EmailReplyRequest):
    """Reply to an email -- uses createReply + update body + send to preserve HTML formatting."""
    try:
        from skills._m365.helpers import get_graph_client
        gc = get_graph_client()

        # -- SAFETY: Verify message exists and belongs to user --
        try:
            msg_check = gc.get(f"/me/messages/{req.message_id}", {"$select": "id,subject,from"})
            from_name = (msg_check.get("from") or {}).get("emailAddress", {}).get("name", "")
            print(f"[email-reply] VERIFIED message_id={req.message_id[:20]}... subject=\"{msg_check.get('subject','')[:40]}\" from={from_name} reply_all={req.reply_all}", flush=True)
        except Exception as verify_err:
            print(f"[email-reply] SAFETY BLOCK: message_id={req.message_id[:20]}... verification failed: {verify_err}", flush=True)
            raise HTTPException(status_code=404, detail="Original message not found -- it may have been deleted or moved")

        # Step 1: Create a draft reply (preserves original thread + headers)
        action = "createReplyAll" if req.reply_all else "createReply"
        draft = gc.post(f"/me/messages/{req.message_id}/{action}", {})
        draft_id = draft.get("id", "")
        # Step 2: Prepend the new text to the draft's existing body. createReply
        # already populated the draft with the quoted original thread; replacing
        # the body outright would strip it (#1), so fetch and prepend instead.
        body_html = req.body
        if "<" not in body_html:
            import html as _html
            body_html = _html.escape(body_html).replace("\n", "<br>")
        quoted = ((gc.get(f"/me/messages/{draft_id}", {"$select": "body"}).get("body")
                   or {}).get("content", ""))
        update: dict = {"body": {"contentType": "HTML", "content": body_html + quoted}}
        # Optional recipient overrides — only patch a field the user actually edited,
        # so an untouched reply keeps the correct recipients createReply already set.
        to_list = [e.strip() for e in req.to.split(",") if e.strip()]
        if to_list:
            update["toRecipients"] = [{"emailAddress": {"address": e}} for e in to_list]
        cc_list = [e.strip() for e in req.cc.split(",") if e.strip()]
        if cc_list:
            update["ccRecipients"] = [{"emailAddress": {"address": e}} for e in cc_list]
        bcc_list = [e.strip() for e in req.bcc.split(",") if e.strip()]
        if bcc_list:
            update["bccRecipients"] = [{"emailAddress": {"address": e}} for e in bcc_list]
        gc.patch(f"/me/messages/{draft_id}", update)
        # Step 3: Send the draft
        gc.post(f"/me/messages/{draft_id}/send", {})
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/email/forward")
def tp_email_forward(req: EmailForwardRequest):
    """Forward an email -- uses createForward + update body + recipients + send to preserve formatting."""
    try:
        from skills._m365.helpers import get_graph_client
        gc = get_graph_client()

        # -- SAFETY: Validate recipients --
        recipients_list = [e.strip() for e in req.to.split(",") if e.strip()]
        if not recipients_list:
            raise HTTPException(status_code=400, detail="No recipients specified for forward")

        # -- SAFETY: Verify message exists and belongs to user --
        try:
            msg_check = gc.get(f"/me/messages/{req.message_id}", {"$select": "id,subject"})
            print(f"[email-forward] VERIFIED message_id={req.message_id[:20]}... subject=\"{msg_check.get('subject','')[:40]}\" to={','.join(recipients_list)}", flush=True)
        except Exception as verify_err:
            print(f"[email-forward] SAFETY BLOCK: message_id={req.message_id[:20]}... verification failed: {verify_err}", flush=True)
            raise HTTPException(status_code=404, detail="Original message not found -- it may have been deleted or moved")

        # Step 1: Create a draft forward (preserves original message + attachments)
        draft = gc.post(f"/me/messages/{req.message_id}/createForward", {})
        draft_id = draft.get("id", "")
        # Step 2: Set recipients, and prepend any comment to the draft's existing
        # body. createForward already populated the draft with the quoted original
        # message; replacing the body outright would strip it (#1), so prepend.
        recipients = [{"emailAddress": {"address": e}} for e in recipients_list]
        update: dict = {"toRecipients": recipients}
        cc_list = [e.strip() for e in req.cc.split(",") if e.strip()]
        if cc_list:
            update["ccRecipients"] = [{"emailAddress": {"address": e}} for e in cc_list]
        bcc_list = [e.strip() for e in req.bcc.split(",") if e.strip()]
        if bcc_list:
            update["bccRecipients"] = [{"emailAddress": {"address": e}} for e in bcc_list]
        if req.comment:
            comment_html = req.comment
            if "<" not in comment_html:
                import html as _html
                comment_html = _html.escape(comment_html).replace("\n", "<br>")
            forwarded = ((gc.get(f"/me/messages/{draft_id}", {"$select": "body"}).get("body")
                          or {}).get("content", ""))
            update["body"] = {"contentType": "HTML", "content": comment_html + forwarded}
        gc.patch(f"/me/messages/{draft_id}", update)
        # Step 3: Send the draft
        gc.post(f"/me/messages/{draft_id}/send", {})
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Draft Approval Endpoint ─────────────────────────────────────────────────
@router.post("/api/drafts/{draft_id}/approve", dependencies=[Depends(verify_csrf)])
async def approve_draft(draft_id: str):
    """Execute a previously-drafted outbound message after user approval.

    Guarded by verify_csrf so only the UI (which receives the per-process
    token at page load) can invoke this. The in-process agent loop has no
    path to read window.__CSRF_TOKEN__ and cannot forge the header.
    """
    from skills._drafts import pop_draft
    draft = pop_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found or expired. Please ask Gator to re-draft.")
    try:
        dtype = draft["type"]
        p = draft["params"]
        if dtype == "email-reply":
            from skills._m365.helpers import get_graph_client
            import html as _html
            gc = get_graph_client()
            # -- SAFETY: Verify original message still exists --
            try:
                gc.get(f"/me/messages/{p['message_id']}", {"$select": "id"})
                print(f"[draft-approve] VERIFIED email-reply message_id={p['message_id'][:20]}...", flush=True)
            except Exception:
                raise HTTPException(status_code=404, detail="Original message no longer exists -- cannot reply")
            action = "createReplyAll" if p.get("reply_all") else "createReply"
            draft = gc.post(f"/me/messages/{p['message_id']}/{action}", {})
            draft_id = draft.get("id", "")
            body_html = p["body"]
            if "<" not in body_html:
                body_html = _html.escape(body_html).replace("\n", "<br>")
            # Prepend to the draft's existing body; createReply already populated it
            # with the quoted original thread, so replacing it outright strips it (#1).
            quoted = ((gc.get(f"/me/messages/{draft_id}", {"$select": "body"}).get("body")
                       or {}).get("content", ""))
            gc.patch(f"/me/messages/{draft_id}", {
                "body": {"contentType": "HTML", "content": body_html + quoted},
            })
            gc.post(f"/me/messages/{draft_id}/send", {})
            return {"ok": True, "action": action.replace("create", "").lower()}
        elif dtype == "email-forward":
            from skills._m365.helpers import get_graph_client
            import html as _html
            gc = get_graph_client()
            # -- SAFETY: Verify original message still exists --
            try:
                gc.get(f"/me/messages/{p['message_id']}", {"$select": "id"})
                print(f"[draft-approve] VERIFIED email-forward message_id={p['message_id'][:20]}... to={p.get('to','')}", flush=True)
            except Exception:
                raise HTTPException(status_code=404, detail="Original message no longer exists -- cannot forward")
            draft = gc.post(f"/me/messages/{p['message_id']}/createForward", {})
            draft_id = draft.get("id", "")
            to_addrs = [a.strip() for a in p["to"].split(",") if a.strip()]
            if not to_addrs:
                raise HTTPException(status_code=400, detail="No recipients specified for forward")
            update: dict = {"toRecipients": [{"emailAddress": {"address": a}} for a in to_addrs]}
            if p.get("comment"):
                comment_html = p["comment"]
                if "<" not in comment_html:
                    comment_html = _html.escape(comment_html).replace("\n", "<br>")
                # Prepend to the draft's existing body; createForward already populated
                # it with the quoted original message, so replacing it strips it (#1).
                forwarded = ((gc.get(f"/me/messages/{draft_id}", {"$select": "body"}).get("body")
                              or {}).get("content", ""))
                update["body"] = {"contentType": "HTML", "content": comment_html + forwarded}
            gc.patch(f"/me/messages/{draft_id}", update)
            gc.post(f"/me/messages/{draft_id}/send", {})
            return {"ok": True, "forwarded_to": to_addrs}
        elif dtype == "slack-post":
            from routes.slack import _slack_mcp_call
            return _slack_mcp_call("slack_send_message", p)
        elif dtype == "slack-dm":
            from routes.slack import _slack_mcp_call
            return _slack_mcp_call("slack_send_message", p)
        elif dtype == "slack-schedule":
            from routes.slack import _slack_mcp_call
            return _slack_mcp_call("slack_schedule_message", p)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown draft type: {dtype}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/email/send")
def tp_email_send(req: EmailSendRequest):
    """Send a new email -- direct Graph API call for frontend-initiated sends."""
    try:
        from skills._m365.helpers import get_graph_client
        gc = get_graph_client()
        to_addrs = [a.strip() for a in req.to.split(",") if a.strip()]

        # -- SAFETY: Validate recipients exist --
        if not to_addrs:
            raise HTTPException(status_code=400, detail="No recipients specified")
        print(f"[email-send] to={','.join(to_addrs)} subject=\"{req.subject[:40]}\"", flush=True)

        body_content = req.body
        # Outlook desktop (Word engine) requires a full <html><head><body> document.
        # Fragments render blank in native Outlook even though Web Outlook handles them fine.
        if "<html" not in body_content.lower():
            body_content = (
                "<!DOCTYPE html><html><head>"
                '<meta http-equiv="Content-Type" content="text/html; charset=utf-8">'
                "</head><body>"
                + body_content
                + "</body></html>"
            )
        msg: dict = {
            "subject": req.subject,
            "body": {"contentType": "HTML", "content": body_content},
            "toRecipients": [{"emailAddress": {"address": a}} for a in to_addrs],
        }
        if req.cc:
            cc_addrs = [a.strip() for a in req.cc.split(",") if a.strip()]
            msg["ccRecipients"] = [{"emailAddress": {"address": a}} for a in cc_addrs]
        if req.bcc:
            bcc_addrs = [a.strip() for a in req.bcc.split(",") if a.strip()]
            msg["bccRecipients"] = [{"emailAddress": {"address": a}} for a in bcc_addrs]
        if req.attachments:
            msg["attachments"] = [{
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": att.name,
                "contentType": att.contentType,
                "contentBytes": att.contentBytes,
            } for att in req.attachments]
        gc.post("/me/sendMail", {"message": msg})
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
