# Daily Usage Report — Design

## Goal

Measure adoption of AI Gator per individual user. Each install writes one row per active user per day to a SharePoint list through Microsoft Graph. Admins read the list outside Gator.

## Scope

In: the daily write from Gator, and the list it writes to.
Out: any dashboard or read path in Gator. Admins use a SharePoint view, Excel, or Power BI on the list.

## Who is reported

The Microsoft account email from `web/identity.py` (see the identity spec). With no Microsoft sign-in there is no identity and nothing is sent.

A day is active when the user sent at least one chat message or ran at least one tool. An inactive day sends no row.

## What is sent

Counts only. Never message text, file names, tool arguments, or connector tokens.

| Column | Value |
|---|---|
| `Title` | key `email|date` (lowercase email, `YYYY-MM-DD`), unique |
| `Email` | identity email |
| `ReportDate` | the UTC date |
| `OS` | Windows or macOS |
| `AppVersion` | contents of `version.txt` |
| `InstallId` | random UUID created once per install, stored in the data dir |
| `Messages` | chat messages sent that day |
| `ToolRuns` | tool runs that day |
| `Connectors` | names of connected providers, for example `microsoft,slack` |

"Created By" is stamped by SharePoint from the token, so the sender cannot forge another user's rows.

## Component: `web/usage_report.py`

| Function | Purpose |
|---|---|
| `record_message()` | Adds 1 to today's message count. |
| `record_tool_run()` | Adds 1 to today's tool-run count. |
| `report_pending() -> None` | Sends each unsent past day with activity. Never raises. |
| `run_usage_report_loop()` | Background loop: runs `report_pending()` at startup and then once a day. Started beside `_logging_retention_loop`. |

- Daily counts live in a small JSON file in the data dir, keyed by date. Counters contain numbers only.
- `report_pending()` posts to `POST /sites/{site}/lists/{list}/items` with the Graph token from the existing `graph_client` refresh logic. The site and list IDs come from config as `usage_list_site_id` and `usage_list_id`. With either unset, the loop does nothing.
- A day is marked sent after a 201, or after a duplicate-key rejection (the row already exists).
- Any other failure leaves the day unsent. It is retried on the next run. Days older than 7 days are dropped.
- Failures are logged at warning level with no token values and never surface to the user.

## List setup

The existing "Gator Usage" list is used. Required changes before the first release that reports:

- Add an `AppVersion` single-line-text column.
- Index `Title` and turn on "Enforce unique values". This makes a repeat send fail harmlessly.
- Item-level permissions: "Create items and edit items created by the user" and "Read items created by the user".
- Every Gator user needs permission to add items to the list. Other admins get full control of the same list.

## Errors

- No Microsoft token or expired refresh: nothing is sent, and the day stays pending.
- Graph 403 or 404: logged, the day stays pending.
- Network failure: same as above.

## Tests

- Message and tool-run counters accumulate per day.
- A past active day is sent once, with the expected fields and a lowercase `email|date` key.
- A 201 or a duplicate-key response marks the day sent.
- Other failures leave the day pending, and a day older than 7 days is dropped.
- An inactive day sends nothing.
- Without an identity, or without the list IDs in config, nothing is sent.
- No message text, file names, or tool arguments appear in any payload.
