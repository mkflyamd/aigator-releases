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

| Column                        | Value                                                                                                                                                                                                                                                                                                             |
| ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------- |
| `Title`                       | key `email                                                                                                                                                                                                                                                                                                        | date`(lowercase email,`YYYY-MM-DD`) |
| `Email`                       | identity email                                                                                                                                                                                                                                                                                                    |
| `ReportDate`                  | the UTC date                                                                                                                                                                                                                                                                                                      |
| `OS`                          | Windows, macOS or Linux                                                                                                                                                                                                                                                                                           |
| `AppVersion`                  | contents of `version.txt`                                                                                                                                                                                                                                                                                         |
| `InstallId`                   | random UUID created once per install                                                                                                                                                                                                                                                                              |
| `Messages`                    | chat responses that day: `usage_log` rows with source `chat` or `chat-direct`                                                                                                                                                                                                                                     |
| `ToolRuns`                    | `tool_call_log` rows that day                                                                                                                                                                                                                                                                                     |
| `InputTokens`, `OutputTokens` | sum of `usage_log` tokens that day                                                                                                                                                                                                                                                                                |
| `Conversations`               | distinct `context_id` in `turn_log` that day                                                                                                                                                                                                                                                                      |
| `BackgroundTasks`             | `tasks` rows created that day                                                                                                                                                                                                                                                                                     |
| `ToolErrors`                  | `tool_call_log` rows whose `outcome` is `error` (cancelled and rejected are user actions, not errors)                                                                                                                                                                                                             |
| `McpToolRuns`                 | `tool_call_log` rows with `is_mcp` set                                                                                                                                                                                                                                                                            |
| `LlmErrors`                   | `turn_log` rows with an `llm_error`                                                                                                                                                                                                                                                                               |
| `Failovers`                   | `turn_log` rows with `failover_used` set                                                                                                                                                                                                                                                                          |
| `Drafts`                      | `task_drafts` rows created that day                                                                                                                                                                                                                                                                               |
| `AvgTurnMs`                   | average `turn_log.duration_ms` that day                                                                                                                                                                                                                                                                           |
| `Details`                     | JSON text of counts: `models` (turns per vendor family: `claude`, `gpt`, `gemini`, `llama`, `qwen`, `glm`, `deepseek`, `mistral`, or `custom`), `skills` (turns with each built-in skill active, from `turn_log.active_skills`), `tools` (top 10 built-in tools by runs), `errors` (tool errors per `error_code`) |

Model names are never sent: each model is counted under a vendor family from a closed list, and anything else is `custom`. Names in `Details` are limited to built-in tools and skills. User-added MCP servers are counted under `mcp` and user-made skills under `custom`, never by name. A missing table or column gives zeros, as `tool_call_log` does for `ToolRuns`. These signals do not change which days are active.

"Created By" is stamped by SharePoint from the token, so the sender cannot forge another user's rows.

## Consent

Nothing is sent until the user answers a first-run notice. The answer belongs to the user: an admin turning reporting on only makes the Settings section appear and never turns sharing on.

- State in `usage_report.json`: `consent` (`on` or `off`), `notice_version`, `last_result` and `last_sent_at`. With no `consent`, or with `on` for an older `notice_version`, the choice is unset and nothing is sent. An `off` stays `off` when the notice changes.
- The notice opens once reporting is available and the choice is unset, at the next moment no other dialog or onboarding is open. Buttons: **Turn off** and **Keep sharing**. Esc decides later: nothing is saved and the notice shows again on the next launch. Clicking outside the dialog does nothing. Focus starts on the title.
- The notice lists what is sent (work email, a random install ID, operating system and version, counts of messages, tokens, errors, and the features, tools and model families used), what is never sent (messages, prompts, files, paths), where it goes (the company's SharePoint list) and how to turn it off.
- Settings, General, Privacy has one toggle, **Share usage with my organization**, a one-line delivery status, and **What is sent**, which reopens the notice read-only with a single **Close** button. The section is hidden when reporting is not available. Turning the toggle on before an answer opens the notice first.
- Delivery status is one of Not started, Off, Waiting, Delayed, Sign-in needed or Sent, with the last report time when there is one.
- Routes: `GET /api/usage-sharing` returns `{available, consent, status, last_sent_at}`. `POST /api/usage-sharing` with `{enabled}` saves the answer, wakes the reporter and returns the same status. The POST requires the CSRF token.

## Component: `web/usage_report.py`

The counts are read from `tasks.db`, which already records them. There are no new counters.

| Function                                  | Purpose                                                                                                                                                                |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `report_pending(cfg, today=None) -> int`  | Sends each unsent active past day. Returns the number of rows sent. Never raises.                                                                                      |
| `run_usage_report_loop(cfg)`              | Background loop: `report_pending` at startup, then once a day or when `request_report()` is called. Started in `app.py`'s lifespan, cancelled and awaited at shutdown. |
| `consent_choice()`, `set_consent(choice)` | Read and save the user's answer. `report_pending` sends nothing unless the choice is `on`, and checks it again before each day it sends.                               |
| `delivery_status(cfg)`                    | Status fields for Settings. No counts, emails or error text.                                                                                                           |

- State lives in `~/.gator/usage_report.json`: the `InstallId` and the `email|date` keys already sent (last 60).
- Config keys in `config.json`: `usage_list_site_id`, `usage_list_id`, `usage_list_link`. Nothing is shipped in the source. Reporting is off until both the site ID and the list ID are set.
- While reporting is on, `/health` returns `usage_reporting: true` and the About dialog shows: "May collect issues and usage to improve AI Gator."
- The Graph token comes from `GraphClient` (the existing refresh logic). The row is created with `POST /sites/{site}/lists/{list}/items`.
- A day is marked sent after a successful create, or after a duplicate-key rejection (the row already exists, which only happens if the list enforces unique titles).
- On a 403 the code opens the list's sharing link once (`GET /shares/{id}/list`) and retries once. This gives a user access through the org-wide link.
- Any other failure stops the run and leaves the remaining days unsent. They are retried at the next run, and a day older than 7 days is never sent.
- Failures are logged at warning level with no token values. The user only sees the delivery status in Settings.

## List setup

The existing "Gator Usage" list is used. Gator's token can write rows but not change the list schema, so these are done in SharePoint:

- Add an `AppVersion` single-line-text column.
- Add number columns `InputTokens`, `OutputTokens`, `Conversations`, `BackgroundTasks`, `ToolErrors`, `McpToolRuns`, `LlmErrors`, `Failovers`, `Drafts`, `AvgTurnMs`, and a multiple-lines-of-plain-text column `Details`.
- Index `Title` but leave "Enforce unique values" off. SharePoint does not allow unique values together with item-level permissions. A repeat send after local state is lost adds a duplicate row, and `tools/sync_usage_to_mysql.py` skips it when loading MySQL.
- Item-level permissions (List settings, Advanced settings): Read access "Read items that were created by the user"; Create and Edit access "Create items and edit items created by the user".
- Every Gator user needs permission to add items. They get it from the org-wide "Can edit items" sharing link. Other admins get full control of the same list.

## Copy to MySQL

`tools/sync_usage_to_mysql.py` is run by an admin. It copies the list into table `usage_daily` in the `aigator_usage` database (approved MySQL request 880), keyed by `(email, report_date)`. Desktops never connect to MySQL.

- A row is copied only when the `Title` email is one of the creator's own addresses (sign-in name, mail, or SMTP alias, looked up in Graph from the creator SharePoint recorded on the item). Any other row is skipped, so a user with write access to the list cannot report as someone else.
- When the key already exists the first row is kept and later rows are ignored.
- Emails and daily counts are the only personal data stored. The table is read by admins only.

## Errors

- No Microsoft token or expired refresh: nothing is sent, and the days stay pending.
- Graph 403 after opening the link, 404, or a network failure: logged, and the days stay pending.

## Tests

`tests/test_usage_report.py` and `tests/test_identity.py` cover:

- Messages count only chat sources, and tool runs count from `tool_call_log`.
- An active past day is sent once, with a lowercase `email|date` key and exactly the columns above.
- Today, background-only days and days older than 7 days are not sent.
- A duplicate-key response marks the day sent. Other failures leave it pending. Without a unique index the list simply accepts the row.
- A 403 opens the link and retries once. Without a link it is a plain failure.
- Without an identity, or with the list IDs unset, nothing is sent.
- A missing `tool_call_log` table still reports messages.
- `InstallId` is stable across runs.
- Each new signal is counted from `tasks.db` for its day, and missing tables or columns give zeros.
- Background-only days stay inactive with the new signals present.
- `Details` never contains user-added MCP server or skill names.
- Nothing is sent while the choice is unset or off, and a day that was pending is sent after the user turns sharing on.
- A new `notice_version` asks again, but an earlier off stays off.
- A choice saved while a send is running is not overwritten, and no further day is sent after an opt-out.
- Models are counted by vendor family and a custom model name is never sent.
- Delivery status follows the choice and the last result, and exposes only the four status fields.
- `tests/test_usage_sharing_routes.py`: the status route, the choice route with and without a CSRF token, and that Keep sharing wakes the reporter.
- `tests/usage_sharing_ui.test.js`: the notice opens on first run, Esc saves nothing, toggling on before an answer opens the notice first, Keep sharing and Turn off save the matching answer, and the read-only version only closes.
