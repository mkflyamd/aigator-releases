# AI Gator permission design

What AI Gator asks before it acts, how each tool is classified, and where "Always allow" can be set. This is the design record. `tests/test_permission_actions.py` enforces the tool lists below.

## Action types

Every tool, built in or from an MCP server, has one of four action types.

| Action type                      | What it does                                                                                          | Always allow | Examples                                                                        |
| -------------------------------- | ----------------------------------------------------------------------------------------------------- | ------------ | ------------------------------------------------------------------------------- |
| Read                             | Changes nothing anywhere.                                                                             | Yes          | Search mail, read a Jira issue, list OneDrive files.                            |
| Write to private                 | Changes only things the user alone sees.                                                              | Yes          | Open a draft in the compose window, create a contact, create a OneNote page.    |
| Write to public (reversible)     | Changes something others can see, and the app keeps real version history or a recycle bin to undo it. | Yes          | Move a OneDrive file, edit a OneNote page.                                      |
| Write to public (not reversible) | Others are notified or see it in a way that cannot be undone.                                         | Never        | Send a message, send or cancel an invite, comment on an issue, delete for good. |

Always allow is granted per app plus action type. "Always allow read for Outlook mail" does not allow writing to Outlook mail, and allowing changes in OneNote does not allow anything in OneDrive.

Settings → Permissions lists one row per app and action type, using the same words as the table above.

## Notifying someone is not reversible

A change that notifies another person counts as not reversible, even when the content can be deleted afterwards. A notification, an email or a chat message has already been seen by then. Jira and Confluence changes notify watchers and nothing in AI Gator suppresses that, so they count too. This covers:

- sending, replying to and forwarding email
- Teams and Slack messages
- calendar invites, added attendees, cancellations and responses
- @mentions and comments that notify watchers
- GitHub issues and comments
- Jira and Confluence changes that notify watchers
- permanent deletes

Teams and Slack messages are therefore not reversible, which is what keeps them draft-only. CLAUDE.md requires that email, Teams and Slack messages never auto-send.

Reversible requires real version history or a recycle bin. A tool whose undo is unclear is treated as not reversible. A tool with no action type is also not reversible, and a built-in tool without one fails the test.

A not-reversible tool is never remembered or allowed for a tab. It does one of two things:

- Draft card. The tool only prepares a draft or is refused. The draft's approval card is the per-call approval, and the access gate in front of it is the app's "Write to private" permission.
- Asks every time. The tool acts as soon as it runs, so each call gets its own card with only Allow this time and Deny.

Some tools depend on the call. Creating a calendar event or an out-of-office event with nobody to notify is a private write. Running `gh` with a read-only command is a read. Any other call to these tools is not reversible.

## MCP tools

An MCP tool is a read only when its server declares `readOnlyHint: true`, does not declare `destructiveHint: true`, and is Atlassian's own server (`mcp.atlassian.com` over https). A hint from any other server proves nothing, so everything else from an MCP server asks every time. Tools that AI Gator parks as approval drafts (gated Google Workspace writes, unverified Jira writes) are filed under the server's "Write to private" permission, and the draft card remains the per-call approval. An MCP server can be granted read and, for drafts, save drafts. It can never be granted anything that sends or changes shared content.

## Button meanings

| Button            | Effect                                                            |
| ----------------- | ----------------------------------------------------------------- |
| Always allow      | Remembered across tabs and restarts until removed in Settings.    |
| Allow in this tab | Lasts until that tab closes. Other tabs still ask.                |
| Allow once        | Covers only this one request. Nothing is saved.                   |
| Allow this time   | Covers only this one request of a kind that cannot be remembered. |
| Deny              | Refuses the request. Always shown.                                |

## Other permissions

"Primary" is the highlighted button. Low-risk permissions lead with Always allow. High-risk permissions lead with Allow in this tab.

| Permission                                      | Risk | Card buttons                    | Primary           | "Always allow" set from                                   | Remembered as                          |
| ----------------------------------------------- | ---- | ------------------------------- | ----------------- | --------------------------------------------------------- | -------------------------------------- |
| Websites (fetch a page)                         | Low  | Always allow, Allow in this tab | Always allow      | Card only                                                 | One host, for example `github.com`     |
| MCP server: read-only tools                     | Low  | Always allow, Allow in this tab | Always allow      | Card or Settings                                          | One server, read                       |
| MCP server: tools parked as drafts              | Low  | Always allow, Allow in this tab | Always allow      | Card or Settings                                          | One server, save drafts                |
| Browser control                                 | High | Allow in this tab               | Allow in this tab | Settings only                                             | Whole category                         |
| Scheduled tasks (create)                        | High | Allow in this tab               | Allow in this tab | Settings only                                             | Whole category                         |
| Run Python code (a skill needs it)              | High | Allow in this tab               | Allow in this tab | Settings only                                             | Whole category                         |
| Run shell commands (a skill needs it)           | High | Allow in this tab               | Allow in this tab | Settings only                                             | Whole category                         |
| Switch to the fallback model                    | High | Allow in this tab, Allow once   | Allow in this tab | Settings only                                             | Whole category                         |
| Shell command access (extra folders or network) | High | Always allow, Allow in this tab | Allow in this tab | Card only, when every program in the command can be saved | One set of folders, hosts and programs |
| Python code access (extra folders or network)   | High | Allow in this tab, Allow once   | Allow in this tab | Never                                                     | Not rememberable                       |

Settings → Permissions shows an Ask / Always allow toggle for each whole-category permission. Websites and shell command access are listed under "Remembered for specific items", each with Remove and Remove all.

## Never remembered

These always ask, with no Always allow button.

| Action                                                                | Rule                                                                                                                                        |
| --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Sending email, Teams or Slack messages, Jira writes, calendar changes | Always a draft card or a per-call card that needs an explicit approval click, even when every other permission for the app is Always allow. |
| Raw Rovo or MCP Jira writes, gated MCP writes                         | Parked as approval drafts.                                                                                                                  |
| Payments, fetching private-network addresses                          | Refused, no card.                                                                                                                           |
| Recorder consent, marketplace digest consent                          | Use their own consent cards.                                                                                                                |

## Rules that apply to everything

1. Check order: admin policy, then saved Always allow rule, then this-tab grant, then a card.
2. Always allow rules never apply to background runs, which keep their existing restrictions. A saved shell set applies to scheduled runs as it did before.
3. The admin setting `persistent_permissions: deny` hides Always allow everywhere and ignores saved rules. The admin setting `saved_permissions` also controls saved shell sets.
4. A card only appears in the tab that asked. A card for another tab waits for that tab.
5. Removing a rule in Settings takes effect on the next call, with no refresh.
6. Each tool call let through by a saved rule is recorded in turn telemetry as `approval=saved`, with category names only. No paths, hosts or content are recorded.

## Built-in tools and their action types

The tables list every built-in tool of the connected apps. The tool names in `web/permissions/actions.py` are the source of truth, and the test fails when a built-in tool is missing from it.

### Outlook mail

| Action type                | Tools                                            |
| -------------------------- | ------------------------------------------------ |
| Read                       | `get_email_detail`, `read_email`, `search_email` |
| Write to private           | `email_open_compose`                             |
| Not reversible, draft card | `forward_email`, `reply_email`, `send_email`     |

### Outlook calendar

| Action type                     | Tools                                                                                                                                             |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Read                            | `check_availability`, `find_meeting_times`, `get_calendar_event_detail`, `read_calendar`                                                          |
| Not reversible, asks every time | `add_calendar_attendees`, `create_calendar_event`, `create_ooo_event`, `delete_calendar_event`, `respond_calendar_event`, `update_calendar_event` |

### Outlook contacts

| Action type                     | Tools             |
| ------------------------------- | ----------------- |
| Read                            | `search_contacts` |
| Write to private                | `create_contact`  |
| Not reversible, asks every time | `delete_contact`  |

### The people directory

| Action type | Tools                                 |
| ----------- | ------------------------------------- |
| Read        | `get_person_profile`, `search_people` |

### Microsoft Teams

| Action type                | Tools                                                                                                                                                                                                                                                |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Read                       | `find_meeting_transcripts`, `get_meeting_transcript_full`, `get_meeting_transcript_header`, `get_meeting_transcript_range`, `get_meeting_transcript_speaker`, `list_teams`, `read_channel_messages`, `read_teams_chats`, `search_meeting_transcript` |
| Write to private           | `save_meeting_transcript`, `teams_open_compose`                                                                                                                                                                                                      |
| Not reversible, draft card | `send_teams_message`                                                                                                                                                                                                                                 |

### SharePoint and OneDrive

| Action type                  | Tools                                                                                                                                                                                                                                                  |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Read                         | `download_onedrive_file`, `get_onedrive_item`, `list_onedrive_files`, `list_sharepoint_drives`, `list_sharepoint_files`, `list_sharepoint_sites`, `read_onedrive_file`, `resolve_teams_attachment`, `search_onedrive_files`, `search_sharepoint_sites` |
| Write to public (reversible) | `copy_onedrive_file`, `move_onedrive_file`                                                                                                                                                                                                             |

### OneNote

| Action type                  | Tools                                                                                                                 |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Read                         | `find_onenote_notebook`, `list_onenote_notebooks`, `list_onenote_pages`, `list_onenote_sections`, `read_onenote_page` |
| Write to private             | `create_onenote_notebook`, `create_onenote_page`, `create_onenote_section`, `pin_onenote_page`                        |
| Write to public (reversible) | `update_onenote_page`                                                                                                 |

### Jira

| Action type                     | Tools                                                                                                                                                                                                                          |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Read                            | `jira_get`, `jira_get_epic_children`, `jira_get_issue`, `jira_get_issue_links`, `jira_get_project_meta`, `jira_list_fields`, `jira_list_link_types`, `jira_search`, `jira_search_user`, `jira_show_issues`, `list_jira_issues` |
| Write to private                | `jira_open_create_form`, `jira_stage_teams_attachment`, `jira_stage_teams_image`, `jira_update_form_fields`                                                                                                                    |
| Not reversible, draft card      | `jira_add_comment`, `jira_add_remote_link`, `jira_add_watcher`, `jira_create_issue`, `jira_mutate`, `jira_stage_attachment`, `jira_unlink_issues`                                                                              |
| Not reversible, asks every time | `jira_link_issues`, `jira_transition`, `jira_update_issue`                                                                                                                                                                     |

### Confluence

| Action type                     | Tools                                                                                                                                                                                      |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Read                            | `confluence_show_pages`, `get_confluence_child_pages`, `get_confluence_edit_context`, `get_confluence_page_outline`, `list_confluence_spaces`, `read_confluence_page`, `search_confluence` |
| Write to private                | `confluence_open_create_form`, `confluence_open_edit_form`                                                                                                                                 |
| Not reversible, asks every time | `create_confluence_page`, `patch_confluence_page`, `update_confluence_page`                                                                                                                |

### Slack

| Action type                | Tools                                                                                                                                                  |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Read                       | `slack_read_channel`, `slack_read_thread`, `slack_read_user_profile`, `slack_search_channels`, `slack_search_public_and_private`, `slack_search_users` |
| Not reversible, draft card | `slack_send_message`                                                                                                                                   |

### GitHub

| Action type                     | Tools                                                                                                                                                                                                                         |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Read                            | `github_get_issue`, `github_get_pr`, `github_list_issues`, `github_list_my_issues`, `github_list_my_prs`, `github_list_my_repos`, `github_list_review_requests`, `github_search_code`, `github_search_repos`, `github_whoami` |
| Not reversible, asks every time | `github_add_issue_comment`, `github_create_issue`, `github_gh`                                                                                                                                                                |
