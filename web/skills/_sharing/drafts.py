"""Draft the share message on email, Teams or Slack. Drafts only: the author approves each one before it sends."""

from .errors import ShareError

CHANNELS = ("email", "teams", "slack")


def _unavailable(result: dict, channel: str) -> ShareError:
    text = result.get("_user_message") or result.get("result") or result.get("error") or ""
    return ShareError("channel_unavailable", str(text)[:300] or f"Could not prepare a {channel} draft.")


def _email(skill_id: str, people: list[str], message: str) -> dict:
    from skills.email.tools import _tool_email_open_compose

    return {
        "drafts": [
            _tool_email_open_compose(
                to=",".join(people), subject=f'AI Gator skill shared with you: "{skill_id}"', body=message
            )
        ],
        "unmatched": [],
    }


def _teams(people: list[str], message: str) -> dict:
    from skills.teams.tools import _tool_teams_open_compose

    result = _tool_teams_open_compose(to=",".join(people), message=message)
    if result.get("error"):
        raise _unavailable(result, "Teams")
    return {"drafts": [result], "unmatched": []}


def _slack(people: list[str], message: str) -> dict:
    from skills.slack.tools import _handle_slack_search_users, _handle_slack_send_message

    drafts, unmatched = [], []
    for email in people:
        found = _handle_slack_search_users(email)
        if found.get("error"):
            raise _unavailable(found, "Slack")
        match = next((u for u in found.get("users", []) if (u.get("email") or "").lower() == email), None)
        if not match:
            unmatched.append(email)
            continue
        result = _handle_slack_send_message(user_id=match["user_id"], team_id=match.get("team_id", ""), message=message)
        if result.get("error"):
            raise _unavailable(result, "Slack")
        drafts.append(result)
    if not drafts:
        raise ShareError("channel_unavailable", "None of these people were found in your Slack workspace.")
    return {"drafts": drafts, "unmatched": unmatched}


def build(channel: str, *, skill_id: str, people: list[str], message: str) -> dict:
    """Create approval drafts for `message`. Returns {"drafts": [tool results], "unmatched": [emails with no draft]}."""
    people = [p.lower() for p in people]
    if channel == "email":
        return _email(skill_id, people, message)
    if channel == "teams":
        return _teams(people, message)
    if channel == "slack":
        return _slack(people, message)
    raise ShareError("invalid", "Choose email, Teams or Slack.")
