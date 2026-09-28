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
