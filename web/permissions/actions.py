"""What a tool call does, in four action types. "Always allow" is granted per app plus action type.

read           changes nothing anywhere
write_private  changes only things the user alone sees (a draft, a personal note, a file in their own folder)
write_public   changes something others can see, and the app itself can undo it (version history or a recycle bin)
irreversible   others see it in a way that cannot be undone: a delivered message or notification, a permanent
               delete. Notifying someone always counts as irreversible, even when the message can be deleted
               afterwards. Teams and Slack messages are irreversible for that reason, which is what keeps them
               draft-only (CLAUDE.md: "Email, Teams, and Slack messages must NEVER auto-send").

An irreversible tool is never remembered or allowed for a tab. It either only prepares a draft (the approval card
on the draft is the per-call approval, see DRAFT_BACKED) or it asks on every call. A tool this module does not
know counts as irreversible, so a new tool asks until someone classifies it.
"""
from __future__ import annotations

READ = "read"
WRITE_PRIVATE = "write_private"
WRITE_PUBLIC = "write_public"
IRREVERSIBLE = "irreversible"

REMEMBERABLE = (READ, WRITE_PRIVATE, WRITE_PUBLIC)
ALL = REMEMBERABLE + (IRREVERSIBLE,)

PHRASE = {
    READ: "read",
    WRITE_PRIVATE: "save drafts and private changes",
    WRITE_PUBLIC: "change shared content (can be undone)",
    IRREVERSIBLE: "send or change things that cannot be undone",
}
DESCRIPTION = {
    READ: "Look things up. Nothing is changed.",
    WRITE_PRIVATE: "Prepare drafts and change things only you can see. Sending anything still needs your approval each time.",
    WRITE_PUBLIC: "Change content other people can see, where the app keeps version history or a recycle bin to undo it.",
}

_READ_TOOLS = """
read_email get_email_detail search_email
check_availability find_meeting_times get_calendar_event_detail read_calendar
search_contacts get_person_profile search_people
find_meeting_transcripts get_meeting_transcript_full get_meeting_transcript_header get_meeting_transcript_range
get_meeting_transcript_speaker search_meeting_transcript list_teams read_channel_messages read_teams_chats
download_onedrive_file get_onedrive_item list_onedrive_files read_onedrive_file resolve_teams_attachment
search_onedrive_files
list_sharepoint_drives list_sharepoint_files list_sharepoint_sites search_sharepoint_sites
find_onenote_notebook list_onenote_notebooks list_onenote_pages list_onenote_sections read_onenote_page
jira_get jira_get_epic_children jira_get_issue jira_get_issue_links jira_get_project_meta jira_list_fields
jira_list_link_types jira_search jira_search_user jira_show_issues list_jira_issues
confluence_show_pages get_confluence_child_pages get_confluence_edit_context get_confluence_page_outline
list_confluence_spaces read_confluence_page search_confluence
slack_read_channel slack_read_thread slack_read_user_profile slack_search_channels slack_search_public_and_private
slack_search_users
github_get_issue github_get_pr github_list_issues github_list_my_issues github_list_my_prs github_list_my_repos
github_list_review_requests github_search_code github_search_repos github_whoami
""".split()

_WRITE_PRIVATE_TOOLS = """
email_open_compose teams_open_compose create_contact save_meeting_transcript
create_onenote_notebook create_onenote_section create_onenote_page pin_onenote_page
jira_open_create_form jira_update_form_fields jira_stage_teams_attachment jira_stage_teams_image
confluence_open_create_form confluence_open_edit_form
""".split()

_WRITE_PUBLIC_TOOLS = """
update_onenote_page
""".split()

# Tools that only prepare a draft (or are refused outright). The draft's approval card is the per-call approval.
DRAFT_BACKED = frozenset("""
send_email reply_email forward_email send_teams_message slack_send_message
jira_add_comment jira_add_watcher jira_stage_attachment
jira_create_issue jira_add_remote_link jira_unlink_issues jira_mutate
jira_update_issue jira_transition jira_link_issues
""".split())

# Tools that act the moment they are called, so each call gets its own approval card. Confluence changes notify
# watchers and nothing here suppresses that, so they are not reversible.
_ASK_EVERY_TIME_TOOLS = """
add_calendar_attendees update_calendar_event delete_calendar_event respond_calendar_event
create_calendar_event create_ooo_event delete_contact
github_create_issue github_add_issue_comment github_gh
create_confluence_page patch_confluence_page update_confluence_page
move_onedrive_file copy_onedrive_file
""".split()

BUILTIN_ACTIONS: dict[str, str] = {
    **dict.fromkeys(_READ_TOOLS, READ),
    **dict.fromkeys(_WRITE_PRIVATE_TOOLS, WRITE_PRIVATE),
    **dict.fromkeys(_WRITE_PUBLIC_TOOLS, WRITE_PUBLIC),
    **dict.fromkeys(DRAFT_BACKED, IRREVERSIBLE),
    **dict.fromkeys(_ASK_EVERY_TIME_TOOLS, IRREVERSIBLE),
}


def _has_value(value) -> bool:
    return bool(value) if not isinstance(value, str) else bool(value.strip())


def _calendar_action(inputs: dict) -> str:
    notifies = _has_value(inputs.get("attendees")) or _has_value(inputs.get("optional_attendees"))
    return IRREVERSIBLE if notifies else WRITE_PRIVATE


def _ooo_action(inputs: dict) -> str:
    return IRREVERSIBLE if _has_value(inputs.get("notify")) else WRITE_PRIVATE


def _gh_action(inputs: dict) -> str:
    args = inputs.get("args")
    if not isinstance(args, list):
        return IRREVERSIBLE
    try:
        from skills.github import gh_cli
        return READ if gh_cli.is_read_only(args) else IRREVERSIBLE
    except Exception:
        return IRREVERSIBLE


def _drive_move_action(inputs: dict) -> str:
    """Inside one drive the file stays under that drive's version history and recycle bin. Into another drive it can
    reach people who could not see it before, and that cannot be taken back."""
    source = str(inputs.get("source_drive_id") or "").strip()
    return WRITE_PUBLIC if source and source == str(inputs.get("dest_drive_id") or "").strip() else IRREVERSIBLE


def _onenote_create_action(inputs: dict) -> str:
    """A notebook, section or page created with a site_id lives in a team notebook that others can see."""
    return WRITE_PUBLIC if _has_value(inputs.get("site_id")) else WRITE_PRIVATE


# Tools whose action depends on the call: the rule, and every action a call can end up with.
_BY_INPUTS = {
    "create_calendar_event": (_calendar_action, (WRITE_PRIVATE, IRREVERSIBLE)),
    "create_ooo_event": (_ooo_action, (WRITE_PRIVATE, IRREVERSIBLE)),
    "github_gh": (_gh_action, (READ, IRREVERSIBLE)),
    "move_onedrive_file": (_drive_move_action, (WRITE_PUBLIC, IRREVERSIBLE)),
    "copy_onedrive_file": (_drive_move_action, (WRITE_PUBLIC, IRREVERSIBLE)),
    "create_onenote_notebook": (_onenote_create_action, (WRITE_PRIVATE, WRITE_PUBLIC)),
    "create_onenote_section": (_onenote_create_action, (WRITE_PRIVATE, WRITE_PUBLIC)),
    "create_onenote_page": (_onenote_create_action, (WRITE_PRIVATE, WRITE_PUBLIC)),
}


def action_for_call(tool: str, inputs: dict | None = None) -> str:
    """The action type of one call. An unknown tool is irreversible."""
    rule = _BY_INPUTS.get(tool)
    if rule:
        return rule[0](inputs or {})
    return BUILTIN_ACTIONS.get(tool, IRREVERSIBLE)


def _gate_for(tool: str, action: str) -> str | None:
    if action != IRREVERSIBLE:
        return action
    return WRITE_PRIVATE if tool in DRAFT_BACKED else None


def gate_action(tool: str, inputs: dict | None = None) -> str | None:
    """The action type whose permission lets this call through, or None when every call needs its own card."""
    return _gate_for(tool, action_for_call(tool, inputs))


def gate_actions_possible(tool: str) -> set[str]:
    """Every action type a permission for this tool could be filed under."""
    rule = _BY_INPUTS.get(tool)
    possible = rule[1] if rule else (BUILTIN_ACTIONS.get(tool, IRREVERSIBLE),)
    return {gate for gate in (_gate_for(tool, a) for a in possible) if gate}
