"""Draft approval router.

All HITL draft types flow through /api/drafts/{id}/approve here.
Email, Slack, Teams, Jira, and Calendar each have an explicit branch;
there is no dynamic dispatch on model-provided type strings beyond the
safe allowlist at the bottom of the handler.

open_draft_in_outlook is email-specific but lives here alongside approve
so email.py contains only email-read/inbox/send routes.
"""

from __future__ import annotations

import asyncio
from functools import partial
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException

from security import verify_csrf

router = APIRouter()


async def _run_sync(fn, *args, **kwargs):
    """Run a synchronous function in a thread — same pattern as execute_tool in app.py.

    rovo_jira_call and MCP client.call() use asyncio.run() internally which
    raises RuntimeError when called from a running event loop (FastAPI async
    handlers). asyncio.to_thread() gives the function its own thread with no
    running event loop, matching how the agent loop dispatches tool calls.
    """
    return await asyncio.to_thread(partial(fn, *args, **kwargs))


# â”€â”€ Jira helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Small, operation-specific wrappers that keep the approve handler readable
# without introducing an adapter class hierarchy.  Every helper is explicit
# about which transport it uses and enforces the no-fallback invariant.

def _jira_tab_guard(p: dict, body: dict | None) -> None:
    """Raise 409 if the approve request comes from a different tab than the draft.

    Only enforces the tab check when the draft was created with a context_id.
    Drafts without a context_id (e.g. from tests or legacy clients) are always
    approvable, but if both sides provide a context_id they must match.
    """
    draft_ctx = str(p.get("context_id", ""))
    request_ctx = str((body or {}).get("context_id", ""))
    if draft_ctx and draft_ctx != request_ctx:
        raise HTTPException(
            status_code=409,
            detail="This Jira draft belongs to a different tab. Re-draft the action.",
        )


def _jira_get_target(p: dict, body: dict | None):
    """Rehydrate and revalidate the captured JiraTarget or raise 409."""
    from skills.jira.mutations import JiraTargetResolutionError, target_from_draft
    try:
        return target_from_draft(p.get("jira_target"), str((body or {}).get("context_id", "")))
    except JiraTargetResolutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _direct_read_issue(target, issue_key: str, fields: str = "*all") -> dict:
    from skills.jira.api import jira_api_for_target
    return jira_api_for_target(target, "GET", f"issue/{issue_key}?fields={fields}")


async def _rovo_read_issue(target, issue_key: str) -> dict:
    from skills.jira.mutations import rovo_jira_call
    raw = await _run_sync(rovo_jira_call, target, "get_issue", {
        "issueIdOrKey": issue_key,
        "fields": ["*all"],
        "responseContentFormat": "adf",
    })
    if isinstance(raw, dict):
        return raw.get("data", raw)
    return {}


async def _read_issue(target, issue_key: str, fields: str = "*all") -> dict:
    """Read an issue from whichever transport owns the target. No fallback."""
    if target.adapter == "builtin-rest":
        return _direct_read_issue(target, issue_key, fields)
    if target.adapter == "rovo-mcp":
        return await _rovo_read_issue(target, issue_key)
    raise HTTPException(status_code=409, detail=f"Unknown adapter {target.adapter!r} on Jira target.")


# â”€â”€ approve_draft â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/api/drafts/{draft_id}/approve", dependencies=[Depends(verify_csrf)])
async def approve_draft(draft_id: str, body: dict = None):
    """Execute a previously-drafted outbound message after user approval.

    Guarded by verify_csrf so only the UI (which receives the per-process
    token at page load) can invoke this. The in-process agent loop has no
    path to read window.__CSRF_TOKEN__ and cannot forge the header.

    Optional body: { "edited_message": "user-edited text" } â€” overrides the
    draft's message with the user's edits from the textarea.

    Fix (PR #10 review): the draft was pop'd BEFORE any delivery attempt, so
    a transient Graph/Slack/Teams error permanently consumed it (retry ->
    404). Now: claim_for_sending atomically transitions the draft to
    "sending" (preventing a concurrent double-send from a duplicate Approve
    click); on delivery failure release_claim_for_retry releases the claim
    back to "pending" so the user can retry (without disturbing a
    "handed_off" draft -- see PR #58 review below); the draft is only pop'd
    on confirmed success. If the process crashes mid-delivery the draft is
    left in "sending" -- a retry will see status=="sending" and treat it as
    already-in-flight (claim returns None -> 409). That's strictly better
    than the prior silent loss; a future "stuck sending" reset could be
    added if it becomes a problem.

    PR #58 review: open_draft_in_outlook can concurrently claim this same
    draft for a native-Outlook handoff. claim_for_sending and claim_for_handoff
    both atomically transition from "pending", so whichever claims first
    locks the other out. If this draft is currently "handed_off" or
    "handing_off", say so explicitly rather than a generic 409.
    """
    from skills._drafts import claim_for_sending, pop_draft, release_claim_for_retry

    draft = claim_for_sending(draft_id)
    if draft is None:
        from skills._drafts import get_draft
        existing = get_draft(draft_id)
        if existing is not None and existing.get("status") == "sending":
            raise HTTPException(
                status_code=409,
                detail="This draft is already being sent. Wait for the in-flight send to finish.",
            )
        if existing is not None and existing.get("status") == "handed_off":
            raise HTTPException(
                status_code=409,
                detail="This draft was opened in Outlook. Send or discard it there — approving here is disabled to avoid a duplicate send.",
            )
        if existing is not None and existing.get("status") == "handing_off":
            raise HTTPException(
                status_code=409,
                detail="A native draft is being created for this message in Outlook. Try again in a moment.",
            )
        raise HTTPException(
            status_code=404,
            detail="Draft not found or expired. Please ask Gator to re-draft.",
        )
    # Apply user edits if provided. email-reply/email-forward store their
    # editable text under "body"/"comment" (not "message"), so the edit must
    # land in the same key the draft type branch below reads.
    if body is not None and "edited_message" in body:
        if draft["type"] == "email-reply":
            draft["params"]["body"] = body["edited_message"]
        elif draft["type"] == "email-forward":
            draft["params"]["comment"] = body["edited_message"]
        else:
            draft["params"]["message"] = body["edited_message"]
    if body and isinstance(body.get("mentions"), list):
        draft["params"]["mentions"] = body["mentions"]

    delivery_result: dict | None = None
    try:
        dtype = draft["type"]
        p = draft["params"]

        # â”€â”€ Email â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if dtype == "email-reply":
            from skills._m365.helpers import get_graph_client
            import html as _html

            gc = get_graph_client()
            try:
                gc.get(f"/me/messages/{p['message_id']}", {"$select": "id"})
                print(
                    f"[draft-approve] VERIFIED email-reply message_id={p['message_id'][:20]}...",
                    flush=True,
                )
            except Exception:
                raise HTTPException(
                    status_code=404,
                    detail="Original message no longer exists -- cannot reply",
                )
            action = "createReplyAll" if p.get("reply_all") else "createReply"
            draft_msg = gc.post(f"/me/messages/{p['message_id']}/{action}", {})
            draft_msg_id = draft_msg.get("id", "")
            body_html = p["body"]
            if "<" not in body_html:
                body_html = _html.escape(body_html).replace("\n", "<br>")
            quoted = (
                gc.get(f"/me/messages/{draft_msg_id}", {"$select": "body"}).get("body") or {}
            ).get("content", "")
            gc.patch(
                f"/me/messages/{draft_msg_id}",
                {"body": {"contentType": "HTML", "content": body_html + quoted}},
            )
            gc.post(f"/me/messages/{draft_msg_id}/send", {})
            delivery_result = {"ok": True, "action": action.replace("create", "").lower()}

        elif dtype == "email-forward":
            from skills._m365.helpers import get_graph_client
            import html as _html

            gc = get_graph_client()
            try:
                gc.get(f"/me/messages/{p['message_id']}", {"$select": "id"})
                print(
                    f"[draft-approve] VERIFIED email-forward message_id={p['message_id'][:20]}... to={p.get('to', '')}",
                    flush=True,
                )
            except Exception:
                raise HTTPException(
                    status_code=404,
                    detail="Original message no longer exists -- cannot forward",
                )
            draft_msg = gc.post(f"/me/messages/{p['message_id']}/createForward", {})
            draft_msg_id = draft_msg.get("id", "")
            to_addrs = [a.strip() for a in p["to"].split(",") if a.strip()]
            if not to_addrs:
                raise HTTPException(status_code=400, detail="No recipients specified for forward")
            update: dict = {"toRecipients": [{"emailAddress": {"address": a}} for a in to_addrs]}
            if p.get("comment"):
                comment_html = p["comment"]
                if "<" not in comment_html:
                    comment_html = _html.escape(comment_html).replace("\n", "<br>")
                forwarded = (
                    gc.get(f"/me/messages/{draft_msg_id}", {"$select": "body"}).get("body") or {}
                ).get("content", "")
                update["body"] = {"contentType": "HTML", "content": comment_html + forwarded}
            gc.patch(f"/me/messages/{draft_msg_id}", update)
            gc.post(f"/me/messages/{draft_msg_id}/send", {})
            delivery_result = {"ok": True, "forwarded_to": to_addrs}

        elif dtype == "email-send":
            from skills._m365.helpers import get_graph_client

            gc = get_graph_client()
            edited = p.get("message")
            body_content = edited if edited is not None else (p.get("body_html") or p.get("body") or "")
            to_addrs = [a.strip() for a in p.get("to", "").split(",") if a.strip()]
            if not to_addrs:
                raise HTTPException(status_code=400, detail="No recipients specified")
            if "<html" not in body_content.lower():
                body_content = (
                    "<!DOCTYPE html><html><head>"
                    '<meta http-equiv="Content-Type" content="text/html; charset=utf-8">'
                    "</head><body>" + body_content + "</body></html>"
                )
            msg: dict = {
                "subject": p.get("subject", ""),
                "body": {"contentType": "HTML", "content": body_content},
                "toRecipients": [{"emailAddress": {"address": a}} for a in to_addrs],
            }
            if p.get("cc"):
                msg["ccRecipients"] = [{"emailAddress": {"address": a.strip()}} for a in p["cc"].split(",") if a.strip()]
            if p.get("bcc"):
                msg["bccRecipients"] = [{"emailAddress": {"address": a.strip()}} for a in p["bcc"].split(",") if a.strip()]
            gc.post("/me/sendMail", {"message": msg, "saveToSentItems": True})
            delivery_result = {"ok": True, "sent_to": to_addrs}

        # â”€â”€ Slack â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        elif dtype == "slack-post":
            from routes.slack import _slack_web_api
            from skills.slack.mcp_client import _load_token

            active_team_id = _load_token().get("team_id", "")
            if not p.get("team_id") or not active_team_id or active_team_id != p["team_id"]:
                raise HTTPException(
                    status_code=409,
                    detail="Slack workspace changed after this draft was created. Reselect the destination and draft again.",
                )
            channel_info = _slack_web_api("conversations.info", {"channel": p["channel_id"]})
            channel = channel_info.get("channel", {}) if channel_info.get("ok") else {}
            if not channel_info.get("ok") or channel.get("is_archived"):
                raise HTTPException(
                    status_code=409,
                    detail=f"Slack channel is unavailable: {channel_info.get('error', 'archived_or_not_accessible')}",
                )
            if channel.get("is_private") and channel.get("is_member") is False:
                raise HTTPException(
                    status_code=409,
                    detail="You are not a member of this private Slack channel. Join it, then create a new draft.",
                )
            payload = {"channel": p["channel_id"], "text": p["message"]}
            if p.get("thread_ts"):
                payload["thread_ts"] = p["thread_ts"]
            data = _slack_web_api("chat.postMessage", payload, method="POST")
            if not data.get("ok"):
                raise HTTPException(status_code=503, detail=f"Slack error: {data.get('error', 'unknown')}")
            delivery_result = {"ok": True, "ts": data.get("ts"), "channel_id": p["channel_id"], "thread_ts": p.get("thread_ts", "")}

        elif dtype == "slack-dm":
            from routes.slack import _slack_web_api
            from skills.slack.mcp_client import _load_token

            active_team_id = _load_token().get("team_id", "")
            if not p.get("team_id") or not active_team_id or active_team_id != p["team_id"]:
                raise HTTPException(
                    status_code=409,
                    detail="Slack workspace changed after this draft was created. Reselect the destination and draft again.",
                )
            opened = _slack_web_api("conversations.open", {"users": p["user_id"]}, method="POST")
            if not opened.get("ok") or not (opened.get("channel") or {}).get("id"):
                raise HTTPException(status_code=503, detail=f"Slack could not open the DM: {opened.get('error', 'unknown')}")
            dm_channel_id = opened["channel"]["id"]
            data = _slack_web_api("chat.postMessage", {"channel": dm_channel_id, "text": p["message"]}, method="POST")
            if not data.get("ok"):
                raise HTTPException(status_code=503, detail=f"Slack error: {data.get('error', 'unknown')}")
            delivery_result = {"ok": True, "ts": data.get("ts"), "channel_id": dm_channel_id}

        # â”€â”€ Teams â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        elif dtype == "teams-message":
            from routes.teams import tp_teams_send_message, TeamsSendMessageRequest

            send_req = TeamsSendMessageRequest(
                to=p.get("to", ""),
                message=p.get("message", ""),
                html=p.get("html", False),
                chat_id=p.get("chat_id", ""),
                recipients=p.get("recipients", []),
                mentions=p.get("mentions", []),
            )
            delivery_result = await tp_teams_send_message(send_req)

        # â”€â”€ Jira â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        elif dtype == "jira-create":
            from skills.jira.api import jira_api_for_target
            from skills.jira.mutations import (
                JiraTargetResolutionError,
                compare_jira_fields,
                rovo_jira_call,
                verified_result,
            )
            from skills.jira.tools import _build_adf_doc

            _jira_tab_guard(p, body)
            target = _jira_get_target(p, body)
            is_cloud = target.is_cloud

            fields: dict = {
                "project": {"key": p["project"]},
                "summary": p["summary"],
                "issuetype": {"name": p["issue_type"]},
            }
            if p.get("description"):
                if target.adapter == "rovo-mcp":
                    fields["description"] = p["description"]
                else:
                    try:
                        fields["description"] = _build_adf_doc(p["description"]) if is_cloud else p["description"]
                    except Exception:
                        fields["description"] = p["description"]
            if p.get("priority"):
                fields["priority"] = {"name": p["priority"]}
            if p.get("assignee_account_id"):
                fields["assignee"] = (
                    {"accountId": p["assignee_account_id"]} if is_cloud
                    else {"name": p["assignee_account_id"]}
                )
            if p.get("parent_key"):
                if is_cloud:
                    fields["parent"] = {"key": p["parent_key"]}
                else:
                    fields["customfield_10008"] = {"key": p["parent_key"]}
            if p.get("extra_fields") and isinstance(p["extra_fields"], dict):
                fields.update(p["extra_fields"])

            try:
                if target.adapter == "rovo-mcp":
                    additional = {k: v for k, v in fields.items()
                                  if k not in {"project", "issuetype", "summary", "description", "parent", "assignee"}}
                    rovo_args: dict = {
                        "projectKey": p["project"],
                        "issueTypeName": p["issue_type"],
                        "summary": p["summary"],
                        "contentFormat": "markdown",
                    }
                    if p.get("description"):
                        rovo_args["description"] = p["description"]
                    if p.get("parent_key"):
                        rovo_args["parent"] = p["parent_key"]
                    if p.get("assignee_account_id"):
                        rovo_args["assignee_account_id"] = p["assignee_account_id"]
                    if additional:
                        rovo_args["additional_fields"] = additional
                    raw = await _run_sync(rovo_jira_call, target, "create_issue", rovo_args)
                    created_obj = raw.get("data", raw) if isinstance(raw, dict) else {}
                else:
                    created_obj = jira_api_for_target(target, "POST", "issue", {"fields": fields})
            except JiraTargetResolutionError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except RuntimeError as exc:
                msg = str(exc)
                # Jira 400 = missing/invalid fields â€” surface the field errors so
                # the frontend can relay them to the model for re-drafting.
                if msg.startswith("HTTP 400:"):
                    import json as _json
                    try:
                        body_str = msg[len("HTTP 400:"):].strip()
                        jira_err = _json.loads(body_str)
                        field_errors = jira_err.get("errors", {})
                        messages = jira_err.get("errorMessages", [])
                        if field_errors:
                            detail = field_errors
                        elif messages:
                            detail = messages
                        else:
                            detail = f"Jira rejected the request: {msg}"
                    except Exception:
                        detail = f"Jira rejected the request: {msg}"
                    raise HTTPException(status_code=422, detail=detail) from exc
                raise HTTPException(status_code=500, detail=f"Jira issue creation failed: {msg}") from exc
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Jira issue creation failed: {exc}") from exc

            issue_key = str(created_obj.get("key") or created_obj.get("issueKey") or "")
            if not issue_key:
                raise HTTPException(status_code=500, detail=f"Jira did not return an issue key. Response: {created_obj}")

            try:
                read_back = await _read_issue(target, issue_key)
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Jira issue verification read failed: {exc}") from exc
            cf = read_back.get("fields", {}) if isinstance(read_back, dict) else {}
            confirmed, rejected = compare_jira_fields(fields, cf)
            warnings = [
                f"{f} was not verified as requested: {ev['requested']!r}."
                for f, ev in rejected.items()
            ]
            issue_url = target.issue_url(issue_key)
            delivery_result = verified_result(
                target,
                requested={"operation": "create_issue", "project": p["project"], "summary": p["summary"],
                           "issue_type": p["issue_type"], "parent_key": p.get("parent_key", ""),
                           "assignee_account_id": p.get("assignee_account_id", "")},
                applied={"issue_key": issue_key},
                verified={"issue_key": issue_key, "fields": confirmed, "not_verified": rejected},
            )
            delivery_result.update({
                "ok": True if not warnings else "partial",
                "issue_key": issue_key,
                "issue_url": issue_url,
                "warnings": warnings,
                "not_verified": rejected,
                "navigate_to": {"app": "jira", "url": issue_url},
            })

        elif dtype == "jira-update":
            from skills.jira.api import jira_api_for_target
            from skills.jira.mutations import (
                JiraTargetResolutionError,
                compare_jira_fields,
                rovo_jira_call,
                verified_result,
            )

            _jira_tab_guard(p, body)
            target = _jira_get_target(p, body)
            issue_key = str(p.get("issue_key", ""))
            fields = p.get("fields") or {}
            if not issue_key or not isinstance(fields, dict) or not fields:
                raise HTTPException(status_code=400, detail="Jira update draft is missing its verified issue or fields.")

            try:
                # Pre-read: confirms issue still exists on this target before writing.
                await _read_issue(target, issue_key)
                if target.adapter == "rovo-mcp":
                    await _run_sync(rovo_jira_call, target, "update_issue", {"issueIdOrKey": issue_key, "fields": fields})
                else:
                    jira_api_for_target(target, "PUT", f"issue/{issue_key}", {"fields": fields})
                read_back = await _read_issue(target, issue_key)
            except JiraTargetResolutionError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Jira update could not be verified: {exc}") from exc

            actual = read_back.get("fields", {}) if isinstance(read_back, dict) else {}
            confirmed, rejected = compare_jira_fields(fields, actual)
            delivery_result = verified_result(
                target,
                requested={"operation": "update_issue", "issue_key": issue_key, "fields": fields},
                applied={"issue_key": issue_key},
                verified={"issue_key": issue_key, "confirmed": confirmed, "not_verified": rejected},
            )
            delivery_result.update({
                "ok": True if not rejected else "partial",
                "issue_key": issue_key,
                "not_verified": rejected,
                "navigate_to": {"app": "jira", "url": target.issue_url(issue_key)},
            })

        elif dtype == "jira-watcher":
            from skills.jira.api import jira_api_for_target
            from skills.jira.mutations import (
                JiraTargetResolutionError,
                verified_result,
            )

            _jira_tab_guard(p, body)
            target = _jira_get_target(p, body)
            issue_key = str(p.get("issue_key", ""))
            account_id = str(p.get("account_id", ""))
            if not issue_key or not account_id:
                raise HTTPException(status_code=400, detail="Jira watcher draft is missing the issue or account ID.")

            if target.adapter == "rovo-mcp":
                # Rovo schema does not expose a watcher API â€” refuse explicitly.
                delivery_result = verified_result(
                    target,
                    requested={"operation": "add_watcher", "issue_key": issue_key, "account_id": account_id},
                    applied={},
                    verified={"unavailable": True, "reason": "Rovo does not expose a watcher API."},
                )
                delivery_result.update({
                    "ok": False,
                    "issue_key": issue_key,
                    "error": "Watcher management is not available for Rovo-connected Jira sites.",
                    "navigate_to": {"app": "jira", "url": target.issue_url(issue_key)},
                })
            else:
                try:
                    jira_api_for_target(target, "GET", f"issue/{issue_key}?fields=watcher")
                    jira_api_for_target(target, "POST", f"issue/{issue_key}/watchers", account_id)
                    watchers = jira_api_for_target(target, "GET", f"issue/{issue_key}/watchers")
                except JiraTargetResolutionError as exc:
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
                except Exception as exc:
                    raise HTTPException(status_code=502, detail=f"Jira watcher change could not be verified: {exc}") from exc
                users = watchers.get("watchers", []) if isinstance(watchers, dict) else []
                found = any(
                    str(u.get("accountId") or u.get("name") or "") == account_id
                    for u in users if isinstance(u, dict)
                )
                delivery_result = verified_result(
                    target,
                    requested={"operation": "add_watcher", "issue_key": issue_key, "account_id": account_id},
                    applied={"issue_key": issue_key, "account_id": account_id},
                    verified={"issue_key": issue_key, "watcher_present": found},
                )
                delivery_result.update({
                    "ok": True if found else "partial",
                    "issue_key": issue_key,
                    "navigate_to": {"app": "jira", "url": target.issue_url(issue_key)},
                })
                if not found:
                    delivery_result["warning"] = (
                        "Jira accepted the watcher request but the exact account was not present on read-back."
                    )

        elif dtype == "jira-attachment":
            from skills.jira.api import jira_api_for_target, jira_upload_attachment_for_target
            from skills.jira.mutations import (
                JiraTargetResolutionError,
                staged_attachment,
                verified_result,
            )

            _jira_tab_guard(p, body)
            target = _jira_get_target(p, body)

            if target.adapter == "rovo-mcp":
                # Rovo schema does not expose a file attachment API â€” refuse explicitly.
                delivery_result = verified_result(
                    target,
                    requested={"operation": "attach_file", "issue_key": p.get("issue_key", "")},
                    applied={},
                    verified={"unavailable": True, "reason": "Rovo does not expose a file attachment API."},
                )
                delivery_result.update({
                    "ok": False,
                    "error": "File attachment is not available for Rovo-connected Jira sites.",
                })
            else:
                try:
                    attachment = staged_attachment(str(p.get("upload_id", "")))
                    jira_api_for_target(target, "GET", f"issue/{p['issue_key']}?fields=attachment")
                    uploaded = jira_upload_attachment_for_target(
                        target, p["issue_key"],
                        attachment["_content"], attachment["filename"], attachment["content_type"],
                    )
                except JiraTargetResolutionError as exc:
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
                except Exception as exc:
                    raise HTTPException(status_code=502, detail=f"Jira attachment upload could not be verified: {exc}") from exc
                matched = next(
                    (item for item in uploaded
                     if item.get("filename") == attachment["filename"]
                     and int(item.get("size", -1)) == attachment["size"]),
                    None,
                )
                delivery_result = verified_result(
                    target,
                    requested={"operation": "attach_file", "issue_key": p["issue_key"],
                               "filename": attachment["filename"], "size": attachment["size"],
                               "sha256": attachment["sha256"]},
                    applied={"issue_key": p["issue_key"], "attachment_id": (matched or {}).get("id", "")},
                    verified={"attachment_id": (matched or {}).get("id", ""), "filename": attachment["filename"],
                              "size": attachment["size"], "sha256": attachment["sha256"],
                              "metadata_match": bool(matched)},
                )
                delivery_result["ok"] = True if matched else "partial"
                if not matched:
                    delivery_result["warning"] = (
                        "Jira returned no attachment metadata matching the approved filename and size."
                    )

        elif dtype == "jira-comment":
            from skills.jira.api import jira_api_for_target
            from skills.jira.mutations import (
                JiraTargetResolutionError,
                rovo_jira_call,
                verified_result,
            )
            from skills.jira.tools import _build_adf_comment

            _jira_tab_guard(p, body)
            target = _jira_get_target(p, body)
            issue_key = str(p.get("issue_key", ""))
            comment_text = str(p.get("comment", ""))

            try:
                if target.adapter == "rovo-mcp":
                    raw = await _run_sync(rovo_jira_call, target, "add_comment", {
                        "issueIdOrKey": issue_key,
                        "commentBody": comment_text,
                        "contentFormat": "markdown",
                    })
                    created = raw.get("data", raw) if isinstance(raw, dict) else {}
                    comment_id = str(created.get("id", ""))
                    read_back = await _read_issue(target, issue_key)
                else:
                    body_value = _build_adf_comment(comment_text) if target.is_cloud else comment_text
                    created = jira_api_for_target(target, "POST", f"issue/{issue_key}/comment", {"body": body_value})
                    comment_id = str(created.get("id", ""))
                    read_back = jira_api_for_target(target, "GET", f"issue/{issue_key}?fields=comment")
            except JiraTargetResolutionError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Jira comment could not be verified: {exc}") from exc

            comments = ((read_back.get("fields") or {}).get("comment") or {}).get("comments", [])
            found = bool(comment_id) and any(
                str(item.get("id", "")) == comment_id for item in comments if isinstance(item, dict)
            )
            delivery_result = verified_result(
                target,
                requested={"operation": "add_comment", "issue_key": issue_key, "comment": comment_text},
                applied={"issue_key": issue_key, "comment_id": comment_id},
                verified={"comment_id": comment_id, "present": found},
            )
            delivery_result["ok"] = True if found else "partial"
            delivery_result["navigate_to"] = {"app": "jira", "url": target.issue_url(issue_key)}

        elif dtype == "jira-transition":
            from skills.jira.api import jira_api_for_target
            from skills.jira.mutations import (
                JiraTargetResolutionError,
                verified_result,
            )

            _jira_tab_guard(p, body)
            target = _jira_get_target(p, body)
            issue_key = str(p.get("issue_key", ""))

            # Rovo transition is unsupported: the Rovo schema requires a
            # non-empty transition ID, and there is no Rovo endpoint to look
            # one up. A legitimate Rovo transition draft cannot be created by
            # the staging tool, so reaching this branch for a Rovo target means
            # the draft was crafted externally â€” refuse it.
            if target.adapter == "rovo-mcp":
                raise HTTPException(
                    status_code=409,
                    detail="Jira transition is not supported for Rovo-connected sites. Use the Jira browser UI to change issue status.",
                )

            try:
                jira_api_for_target(target, "GET", f"issue/{issue_key}?fields=status")
                jira_api_for_target(target, "POST", f"issue/{issue_key}/transitions", p["payload"])
                read_back = await _read_issue(target, issue_key)
            except JiraTargetResolutionError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Jira transition could not be verified: {exc}") from exc

            status = ((read_back.get("fields") or {}).get("status") or {}).get("name", "")
            expected_status = str(p.get("expected_status") or p.get("transition_name", ""))
            matched = status.lower() == expected_status.lower()
            delivery_result = verified_result(
                target,
                requested={"operation": "transition", "issue_key": issue_key,
                           "transition": p.get("transition_name", ""), "expected_status": expected_status},
                applied={"issue_key": issue_key, "transition": p.get("transition_name", "")},
                verified={"status": status, "expected_status": expected_status, "matched": matched},
            )
            delivery_result["ok"] = True if matched else "partial"
            delivery_result["navigate_to"] = {"app": "jira", "url": target.issue_url(issue_key)}

        elif dtype == "jira-link":
            from skills.jira.api import jira_api_for_target
            from skills.jira.mutations import (
                JiraTargetResolutionError,
                rovo_jira_call,
                verified_result,
            )

            _jira_tab_guard(p, body)
            target = _jira_get_target(p, body)
            issue_key = str(p.get("issue_key", ""))
            other_key = str(p.get("other_key", ""))
            link_type = str(p.get("link_type", ""))

            try:
                await _read_issue(target, issue_key)   # pre-read confirms issue exists
                if target.adapter == "rovo-mcp":
                    payload_raw = p.get("payload") or {}
                    rovo_inward = str((payload_raw.get("inwardIssue") or {}).get("key", "") or other_key)
                    rovo_outward = str((payload_raw.get("outwardIssue") or {}).get("key", "") or issue_key)
                    await _run_sync(rovo_jira_call, target, "create_link", {
                        "inwardIssue": rovo_inward,
                        "outwardIssue": rovo_outward,
                        "type": link_type,
                    })
                else:
                    jira_api_for_target(target, "POST", "issueLink", p["payload"])
                read_back = await _read_issue(target, issue_key)
            except JiraTargetResolutionError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Jira link could not be verified: {exc}") from exc

            links = ((read_back.get("fields") or {}).get("issuelinks") or [])
            before_ids = {str(lid) for lid in p.get("before_link_ids", [])}
            matched_link = next(
                (lnk for lnk in links if
                 isinstance(lnk, dict)
                 and str(lnk.get("id", "")) not in before_ids
                 and lnk.get("type", {}).get("name", "").lower() == link_type.lower()
                 and (lnk.get("inwardIssue", {}).get("key") == other_key
                      or lnk.get("outwardIssue", {}).get("key") == other_key)),
                None,
            )
            delivery_result = verified_result(
                target,
                requested={"operation": "link_issues", "issue_key": issue_key,
                           "other_key": other_key, "link_type": link_type},
                applied={"issue_key": issue_key, "other_key": other_key,
                         "link_id": (matched_link or {}).get("id", "")},
                verified={"link_id": (matched_link or {}).get("id", ""), "link_present": bool(matched_link)},
            )
            delivery_result["ok"] = True if matched_link else "partial"
            delivery_result["navigate_to"] = {"app": "jira", "url": target.issue_url(issue_key)}

        # â”€â”€ Calendar (Google Workspace MCP) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        elif dtype == "calendar-write":
            from mcp.manager import _load_connections, _client_for

            conn_id = p.get("connection_id", "")
            tool_name = p.get("tool", "")
            tool_args = p.get("arguments", {}) or {}
            if not conn_id or not tool_name:
                raise HTTPException(status_code=400, detail="Calendar draft missing connection_id or tool")
            conn = next((c for c in _load_connections() if c.get("id") == conn_id), None)
            if conn is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Calendar connection '{conn_id}' no longer exists â€” reconnect and try again.",
                )
            client = None
            try:
                client = _client_for(conn, pooled=False)
                raw = client.call(tool_name, tool_args)
                delivery_result = {"ok": True, "result": raw if raw else "ok", "tool": tool_name}
            finally:
                if client is not None:
                    close = getattr(client, "close", None)
                    if close:
                        try:
                            close()
                        except Exception:
                            pass

        else:
            raise HTTPException(status_code=400, detail=f"Unknown draft type: {dtype}")

    except HTTPException:
        # release_claim_for_retry (not mark_status) so a concurrent
        # open_draft_in_outlook that already flipped this draft to
        # "handed_off" isn't clobbered back to "pending" (PR #58 review).
        release_claim_for_retry(draft_id)
        raise
    except Exception as e:
        release_claim_for_retry(draft_id)
        raise HTTPException(status_code=500, detail=str(e))

    pop_draft(draft_id)

    _nav_app = {
        "email-reply": "outlook",
        "email-forward": "outlook",
        "email-send": "outlook",
        "slack-post": "slack",
        "slack-dm": "slack",
        "slack-announce": "slack",
        "teams-message": "teams",
    }.get(dtype)
    if _nav_app:
        _nav: dict = {"app": _nav_app}
        if _nav_app == "slack":
            _channel_id = delivery_result.get("channel_id") or p.get("channel_id")
            if _channel_id:
                _nav["channel_id"] = _channel_id
            if delivery_result.get("thread_ts"):
                _nav["thread_ts"] = delivery_result["thread_ts"]
        elif _nav_app == "teams":
            _chat_id = delivery_result.get("chat_id") or p.get("chat_id")
            if _chat_id:
                _nav["chat_id"] = _chat_id
        delivery_result["navigate_to"] = _nav

    return delivery_result


# â”€â”€ open_draft_in_outlook â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/api/drafts/{draft_id}/open-in-outlook", dependencies=[Depends(verify_csrf)])
async def open_draft_in_outlook(draft_id: str, body: dict = None):
    """Create a real OWA draft from a pending Gator draft and return its URL.

    Optional body: { "edited_message": "user-edited text" } uses the same
    per-draft routing as approve_draft so approval-card edits survive handoff.

    claim_for_handoff reserves the draft (pending -> handing_off) BEFORE any
    Graph call is made, exactly mirroring how approve_draft's
    claim_for_sending reserves "sending" before its own Graph call. This is
    what makes the two operations mutually exclusive: whichever claims first
    locks the other out before either has created its external side effect,
    not after. Once the OWA draft is created, complete_handoff finalizes the
    Gator draft as "handed_off": it stays visible so the UI can explain why,
    but is now permanently unclaimable by approve_draft. Without claiming
    first, a concurrent Approve could slip in and deliver via Gator in the
    gap before the native draft's creation was ever recorded, producing both
    a sent Gator message and an independently sendable OWA draft (PR #58
    review, round 2).

    PR #58 review, round 3: reply/forward create the native draft first and
    only patch its body afterward (to quote/forward the original content). If
    that later GET/PATCH fails, the native draft still exists -- releasing
    the claim back to "pending" would let Approve deliver a second,
    independent message via Gator. So the except blocks below must not
    blindly abort: once msg_id has been assigned from a successful create
    call, the native draft is known to exist and the claim must resolve to
    "handed_off" (terminal), never back to "pending".

    PR #58 review, round 4: the same ambiguity applies to the *creation* call
    itself failing with a bare network error (no HTTP response ever received,
    e.g. a timeout -- GraphAPIError.status_code left at its 0 default, see
    graph_client.py's _request retry loop) or with a 5xx/gateway status. In
    both cases Graph, or a proxy in front of it, may have processed the
    request before the client saw the failure, and the retries _request
    already performed only widen that window. Only a definitive client-side
    rejection (a real, non-5xx status -- the request was refused before Graph
    did anything) is safe to release back to "pending"; status_code == 0 or
    >= 500 is treated as "maybe created" and resolved as a terminal handoff
    instead, same as a known msg_id.
    """
    import html as _html
    from skills._drafts import get_draft, claim_for_handoff, abort_handoff, complete_handoff

    msg_id = ""

    draft = get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found or expired.")

    dtype = draft["type"]

    if dtype not in ("email-send", "email-reply", "email-forward"):
        raise HTTPException(
            status_code=400,
            detail=f"Open-in-Outlook not supported for draft type '{dtype}'.",
        )

    claimed = claim_for_handoff(draft_id)
    if claimed is None:
        existing = get_draft(draft_id)
        status = existing.get("status") if existing else None
        if status == "sending":
            raise HTTPException(
                status_code=409,
                detail="This draft is currently being sent from Gator. Wait for it to finish first.",
            )
        if status in ("handing_off", "handed_off"):
            raise HTTPException(
                status_code=409,
                detail="This draft has already been opened in Outlook.",
            )
        raise HTTPException(status_code=404, detail="Draft not found or expired.")
    p = claimed["params"]

    if body is not None and "edited_message" in body:
        if dtype == "email-reply":
            p["body"] = body["edited_message"]
        elif dtype == "email-forward":
            p["comment"] = body["edited_message"]
        else:
            p["message"] = body["edited_message"]

    try:
        from skills._m365.helpers import get_graph_client

        gc = get_graph_client()

        if dtype == "email-send":
            to_addrs = [a.strip() for a in p.get("to", "").split(",") if a.strip()]
            if not to_addrs:
                raise HTTPException(status_code=400, detail="No recipients in draft.")
            edited = p.get("message")
            body_content = edited if edited is not None else (p.get("body_html") or p.get("body") or "")
            if "<" not in body_content:
                body_content = _html.escape(body_content).replace("\n", "<br>")
            msg: dict = {
                "subject": p.get("subject", ""),
                "body": {"contentType": "HTML", "content": body_content},
                "toRecipients": [{"emailAddress": {"address": a}} for a in to_addrs],
            }
            if p.get("cc"):
                msg["ccRecipients"] = [{"emailAddress": {"address": a.strip()}} for a in p["cc"].split(",") if a.strip()]
            if p.get("bcc"):
                msg["bccRecipients"] = [{"emailAddress": {"address": a.strip()}} for a in p["bcc"].split(",") if a.strip()]
            created = gc.post("/me/messages", msg)
            msg_id = created.get("id", "")

        elif dtype == "email-reply":
            try:
                gc.get(f"/me/messages/{p['message_id']}", {"$select": "id"})
            except Exception:
                raise HTTPException(status_code=404, detail="Original message no longer exists.")
            action = "createReplyAll" if p.get("reply_all") else "createReply"
            reply_draft = gc.post(f"/me/messages/{p['message_id']}/{action}", {})
            msg_id = reply_draft.get("id", "")
            body_html = p.get("body", "")
            if "<" not in body_html:
                body_html = _html.escape(body_html).replace("\n", "<br>")
            quoted = (gc.get(f"/me/messages/{msg_id}", {"$select": "body"}).get("body") or {}).get("content", "")
            gc.patch(f"/me/messages/{msg_id}", {"body": {"contentType": "HTML", "content": body_html + quoted}})

        else:  # email-forward
            try:
                gc.get(f"/me/messages/{p['message_id']}", {"$select": "id"})
            except Exception:
                raise HTTPException(status_code=404, detail="Original message no longer exists.")
            fwd_draft = gc.post(f"/me/messages/{p['message_id']}/createForward", {})
            msg_id = fwd_draft.get("id", "")
            to_addrs = [a.strip() for a in p.get("to", "").split(",") if a.strip()]
            update: dict = {"toRecipients": [{"emailAddress": {"address": a}} for a in to_addrs]}
            if p.get("comment"):
                comment_html = p["comment"]
                if "<" not in comment_html:
                    comment_html = _html.escape(comment_html).replace("\n", "<br>")
                forwarded = (gc.get(f"/me/messages/{msg_id}", {"$select": "body"}).get("body") or {}).get("content", "")
                update["body"] = {"contentType": "HTML", "content": comment_html + forwarded}
            gc.patch(f"/me/messages/{msg_id}", update)

    except HTTPException:
        if msg_id:
            complete_handoff(draft_id)
            raise HTTPException(
                status_code=502,
                detail=(
                    "A native Outlook draft was created, but Gator could not "
                    "finish preparing it. Check Outlook directly — Approve is "
                    "disabled for this message to avoid a duplicate send."
                ),
            )
        abort_handoff(draft_id)
        raise
    except Exception as e:
        status_code = getattr(e, "status_code", None)
        side_effect_uncertain = bool(msg_id) or (
            isinstance(status_code, int) and (status_code == 0 or status_code >= 500)
        )
        if side_effect_uncertain:
            complete_handoff(draft_id)
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Outlook may already have created a native draft for this "
                    f"message, but Gator could not confirm or finish it ({e}). "
                    "Check Outlook directly — Approve is disabled for this "
                    "message to avoid a duplicate send."
                ),
            )
        abort_handoff(draft_id)
        raise HTTPException(status_code=500, detail=str(e))

    complete_handoff(draft_id)
    enc = quote(msg_id, safe="")
    return {"url": f"https://outlook.office.com/mail/drafts/id/{enc}"}
