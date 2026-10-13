# Security Feature: Logging

## Purpose and scope

AI Gator uses two managed production logging capabilities. This plan defines
their content, retention, and operational controls.

| Log                                    | Content                                                                                                                         |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Backend log (`gator_backend.log`)      | Application and server diagnostics, including warnings, errors, and unhandled exception tracebacks.                             |
| Agent execution telemetry (`tasks.db`) | Structured `turn_log` and `tool_call_log` records for LLM turns and user-initiated tool executions, including MCP-backed tools. |

This approach keeps the implementation focused on proactive controls for the
production logging paths.

## Logging behavior

### Backend log (`gator_backend.log`)

The backend log is a managed plain-text record of application and server
diagnostics. It will be continuously bounded during runtime.

- `gator_backend.log` is limited to 5 MiB.
- When the limit is reached, the active log is rotated before further output is
  written.
- One backup, `gator_backend.1.log`, is retained. Older backups are replaced
  rather than accumulating.
- Both the active log and its backup are limited to 5 MiB. The retained backend
  log footprint is therefore at most 10 MiB.
- Cleanup runs at application startup and once every 24 hours. Files whose
  modification time is more than 30 days old are deleted.

The backend will use the standard Python logging system with a non-blocking
logging queue and a dedicated listener using a rotating file handler. This
provides continuous rotation without allowing log I/O to block application
work.

### Agent execution telemetry (`tasks.db`)

Agent execution telemetry provides a structured diagnostic timeline for LLM
turns and tool executions. It is stored in SQLite tables within `tasks.db`.

Each LLM turn record will include only the metadata needed for operational
diagnostics, such as:

- timestamp;
- model;
- outcome;
- token counts;
- duration; and
- optional, length-bounded diagnostic error details.

Each tool-execution record will include only the metadata needed to determine
what was invoked and whether it completed:

- timestamp;
- tool name;
- whether the tool is MCP-backed;
- outcome (`success`, `error`, `rejected`, or `cancelled`);
- duration; and
- optional normalized error code.

Tool execution records do not retain prompts, responses, tool arguments, or
tool results. Each user-initiated built-in or MCP-backed execution is recorded
through the shared execution and MCP transport paths.

Retention cleanup runs at application startup and once every 24 hours. SQLite
records older than 30 days are deleted from both `turn_log` and `tool_call_log`.

## Access control

The backend log (and its folder), `tasks.db` and `scheduler.db` hold paths, error text and job prompts.
AI Gator limits them to the current user when it creates them and again after a log rotation.

- On macOS and Linux the mode is `600` for files and `700` for the log folder.
- On Windows AI Gator removes the inherited ACL entries and grants Full Control to the current user only (`icacls`).
- If AI Gator cannot apply the restriction, it logs an error. It writes no log lines to the file. It also turns telemetry off for that run.

## Logging levels and privacy mode

The backend log records `INFO` and above. Telemetry holds metadata only (see above).

Every record is passed through one function, `sanitize()` in `web/log_sanitizer.py`, before it is written.
This function always removes:

- secrets, tokens and bearer values;
- the user's home folder name;
- tenant IDs; and
- internal hostnames (`*.amd.com`, `.corp`, `.local`, `.internal`, UNC server names).

Privacy mode removes more. Turn it on with `privacy_mode` in `config.json` (or `PATCH /api/config`), or with
`AIGATOR_PRIVACY_MODE=1`. It is on by default in packaged builds. Set `privacy_mode` to `false` to turn it off.
In privacy mode, logs and telemetry:

- omit tool, skill and MCP server names (telemetry stores `<tool>`);
- omit all file paths and GUIDs; and
- replace error detail text with `<redacted>` in telemetry.

Outcomes, durations, token counts and tool-call counts stay available.

## Retention summary

| Data                 | Size limit                       | Age limit | When it runs                        |
| -------------------- | -------------------------------- | --------- | ----------------------------------- |
| `gator_backend.log`  | 5 MiB (plus one 5 MiB backup)    | 30 days   | on every write; startup; every 24 h |
| `tasks.db` telemetry | 100,000 rows per telemetry table | 30 days   | startup; every 24 h                 |

These limits follow the AMD logging and data protection requirement to keep diagnostic data only as long as needed.
