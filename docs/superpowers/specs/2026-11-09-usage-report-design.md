# Daily Usage Report — Design

## Goal

Measure adoption of AI Gator per individual user. Each install writes one row per active user per day to a SharePoint list through Microsoft Graph. Admins read the list outside Gator.

## Scope

In: the daily write from Gator, and the list it writes to.
Out: any dashboard or read path in Gator. Admins use a SharePoint view, Excel, or Power BI on the list.

## Who is reported

The Microsoft account email from `web/identity.py` (see the identity spec). With no Microsoft sign-in there is no identity and nothing is sent.

A day is active when the user sent at least one chat message or ran at least one tool. An inactive day sends no row. Only complete past UTC days are sent, up to 7 days back.

## What is sent

Counts only. Never message text, file names, or tool arguments.

| Column | Value |
|---|---|
| `Title` | key `email|date` (lowercase email, `YYYY-MM-DD`), unique |
| `Email` | identity email |
| `ReportDate` | the UTC date |
| `OS` | Windows, macOS or Linux |
| `AppVersion` | contents of `version.txt` |
| `InstallId` | random UUID created once per install |
| `Messages` | chat responses that day: `usage_log` rows with source `chat` or `chat-direct` |
| `ToolRuns` | `tool_call_log` rows that day |

"Created By" is stamped by SharePoint from the token, so the sender cannot forge another user's rows.

## Component: `web/usage_report.py`

The counts are read from `tasks.db`, which already records them. There are no new counters.

| Function | Purpose |
|---|---|
| `report_pending(cfg, today=None) -> int` | Sends each unsent active past day. Returns the number of rows sent. Never raises. |
| `run_usage_report_loop(cfg)` | Background loop: `report_pending` at startup, then once a day. Started and cancelled in `app.py`'s lifespan. |

- State lives in `~/.gator/usage_report.json`: the `InstallId` and the `email|date` keys already sent (last 60).
- Config keys in `config.json`: `usage_list_site_id`, `usage_list_id`, `usage_list_link`. Nothing is shipped in the source. Reporting is off until both the site ID and the list ID are set.
- While reporting is on, `/health` returns `usage_reporting: true` and the About dialog shows: "Daily chat and tool-run counts are reported under your Microsoft email. No message content is sent."
- The Graph token comes from `GraphClient` (the existing refresh logic). The row is created with `POST /sites/{site}/lists/{list}/items`.
- A day is marked sent after a successful create, or after a duplicate-key rejection (the row already exists).
- On a 403 the code opens the list's sharing link once (`GET /shares/{id}/list`) and retries once. This gives a user access through the org-wide link.
- Any other failure stops the run and leaves the remaining days unsent. They are retried at the next run, and a day older than 7 days is never sent.
- Failures are logged at warning level with no token values and never surface to the user.

## List setup

The existing "Gator Usage" list is used. Gator's token can write rows but not change the list schema, so these are done in SharePoint:

- Add an `AppVersion` single-line-text column.
- Index `Title` and turn on "Enforce unique values". This makes a repeat send fail harmlessly.
- Item-level permissions (List settings, Advanced settings): Read access "Read items that were created by the user"; Create and Edit access "Create items and edit items created by the user".
- Every Gator user needs permission to add items. They get it from the org-wide "Can edit items" sharing link. Other admins get full control of the same list.

## Errors

- No Microsoft token or expired refresh: nothing is sent, and the days stay pending.
- Graph 403 after opening the link, 404, or a network failure: logged, and the days stay pending.

## Tests

`tests/test_usage_report.py` and `tests/test_identity.py` cover:

- Messages count only chat sources, and tool runs count from `tool_call_log`.
- An active past day is sent once, with a lowercase `email|date` key and exactly the columns above.
- Today, background-only days and days older than 7 days are not sent.
- A duplicate-key response marks the day sent. Other failures leave it pending.
- A 403 opens the link and retries once. Without a link it is a plain failure.
- Without an identity, or with the list IDs unset, nothing is sent.
- A missing `tool_call_log` table still reports messages.
- `InstallId` is stable across runs.
