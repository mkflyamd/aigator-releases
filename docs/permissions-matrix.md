# AI Gator permission matrix

What AI Gator asks before it acts, what each approval card offers, and where "Always allow" can be set.

## Button meanings

| Button            | Effect                                                         |
| ----------------- | -------------------------------------------------------------- |
| Always allow      | Remembered across tabs and restarts until removed in Settings. |
| Allow in this tab | Lasts until that tab closes. Other tabs still ask.             |
| Allow once        | Covers only this one request. Nothing is saved.                |
| Deny              | Refuses the request. Always shown.                             |

## Permissions

"Primary" is the highlighted button. Low-risk permissions lead with Always allow. High-risk permissions lead with Allow in this tab.

| Permission                                         | Risk | Card buttons                    | Primary           | "Always allow" set from                                   | Remembered as                          |
| -------------------------------------------------- | ---- | ------------------------------- | ----------------- | --------------------------------------------------------- | -------------------------------------- |
| Outlook mail, calendar, contacts, people directory | Low  | Always allow, Allow in this tab | Always allow      | Card or Settings                                          | Whole category                         |
| Teams, SharePoint and OneDrive, OneNote            | Low  | Always allow, Allow in this tab | Always allow      | Card or Settings                                          | Whole category                         |
| Jira, Confluence, Slack, GitHub (read access)      | Low  | Always allow, Allow in this tab | Always allow      | Card or Settings                                          | Whole category                         |
| Websites (fetch a page)                            | Low  | Always allow, Allow in this tab | Always allow      | Card only                                                 | One host, for example `github.com`     |
| Browser control                                    | High | Allow in this tab               | Allow in this tab | Settings only                                             | Whole category                         |
| Scheduled tasks (create)                           | High | Allow in this tab               | Allow in this tab | Settings only                                             | Whole category                         |
| Run Python code (a skill needs it)                 | High | Allow in this tab               | Allow in this tab | Settings only                                             | Whole category                         |
| Run shell commands (a skill needs it)              | High | Allow in this tab               | Allow in this tab | Settings only                                             | Whole category                         |
| Switch to the fallback model                       | High | Allow in this tab, Allow once   | Allow in this tab | Settings only                                             | Whole category                         |
| Shell command access (extra folders or network)    | High | Always allow, Allow in this tab | Allow in this tab | Card only, when every program in the command can be saved | One set of folders, hosts and programs |
| Python code access (extra folders or network)      | High | Allow in this tab, Allow once   | Allow in this tab | Never                                                     | Not rememberable                       |

Settings → Access shows an Ask / Always allow toggle for each whole-category permission. Websites and shell command access are listed under "Remembered for specific items", each with Remove and Remove all.

## Never remembered

These always ask, with no Always allow button.

| Action                                                                | Rule                                                                                                               |
| --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Sending email, Teams or Slack messages, Jira writes, calendar changes | Always a draft card that needs an explicit approval click, even when the matching read permission is Always allow. |
| Raw Rovo or MCP Jira writes, gated MCP writes                         | Parked as approval drafts.                                                                                         |
| Payments, fetching private-network addresses                          | Refused, no card.                                                                                                  |
| Recorder consent, marketplace digest consent                          | Use their own consent cards.                                                                                       |

## Rules that apply to everything

1. Check order: admin policy, then saved Always allow rule, then this-tab grant, then a card.
2. Always allow rules for permissions and websites never apply to background runs, which keep their existing restrictions. A saved shell set applies to scheduled runs as it did before.
3. The admin setting `persistent_permissions: deny` hides Always allow everywhere and ignores saved rules. The admin setting `saved_permissions` also controls saved shell sets.
4. A card only appears in the tab that asked. A card for another tab waits for that tab.
5. Removing a rule in Settings takes effect on the next call, with no refresh.
6. Each tool call let through by a saved rule is recorded in turn telemetry as `approval=saved`, with category names only. No paths, hosts or content are recorded.
