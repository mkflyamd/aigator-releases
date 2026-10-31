# File Transfer — Design

## Problem

Two Gator chats asked to move a Teams-attached file into a OneDrive folder. The file was locked, so Graph returned 423 and nothing moved. One chat then asked the user what to do; the other gave up with advice. Causes:

- `move_onedrive_file` returns a flat `"Move failed: …"` string. There is no retry, no fallback and no machine-readable reason.
- No registered upload tool exists. Upload lives only in `skills/m365-onedrive/scripts/upload.py` and in private docx/ppt save-back code. The script writes only to `/me/drive/root:/{path}` (no drive or folder IDs, unencoded path, no conflict handling).
- `copy_onedrive_file` polls Graph's pre-authenticated monitor URL with an `Authorization` header and swallows every error. The 60s poll can time out on a finished copy.
- The onedrive skill guide says nothing about move, copy, locks or Teams attachments.
- Every app has its own file path (OneDrive download, Teams attachment resolve, Jira staging, docx/ppt save-back). Nothing is shared.
- Two UI defects: the ask-user option card overflows (`.btn-secondary { white-space: nowrap }` at `style.css:2651` is never overridden by `.ask-user-option`), and an expired permission approval drops the user's message.

## Goals

- A file move/copy/upload/download that works regardless of the app, with OneDrive/SharePoint as the first provider.
- Locked sources are handled by the tool, not improvised by the model.
- No regression in existing tools.

## Non-goals

- Delete in any form. Gator never removes a file.
- A Google Drive provider (the interface leaves room for one).
- Migrating Jira attachment staging.
- Changing or retiring existing OneDrive tools.

## Design

### Existing tools stay

`read/list/search/download/move/copy/get_onedrive_item` and `resolve_teams_attachment` keep their names, arguments and results. Only two changes:

1. `copy_onedrive_file`: poll the monitor URL without `Authorization`, treat a bare item JSON (no `status`) as completed, and surface the last poll error instead of swallowing it.
2. `move_onedrive_file`, `copy_onedrive_file` and `get_onedrive_item` error dicts gain an additive `error_code` (`locked`, `forbidden`, `not_found`, `throttled`, `unknown`) next to the existing `error` string.

### New file tools

The four tools are registered in the existing `onedrive` skill (`web/skills/onedrive/tools.py`), not in a new skill. Data-source gating (`data_sources._NATIVE_SOURCES`), the Teams attachment dependency and the Settings toggle are all keyed on the `onedrive` skill's tool names; a separate skill would bypass the "SharePoint and OneDrive" approval card. The orchestration and provider code lives in a helper package `web/skills/_files/` (underscore-prefixed, so the loader skips it, like `_m365`). Handlers import it lazily inside the function, because `test_onedrive_file_routing.py` loads `tools.py` by file path without a package.

**File reference:** `{provider, drive_id, item_id}` plus optional `name`. Any tool that already returns `drive_id` and `item_id` (`get_onedrive_item`, `resolve_teams_attachment`, list/search) supplies one.

**Provider interface** (duck-typed, in `web/skills/_files/transfer.py`'s docstring): `stat`, `is_foreign_owner`, `move`, `copy`, `find_in_folder`, `download`, `upload`. The OneDrive/SharePoint provider (`web/skills/_m365/onedrive_provider.py`) wraps the existing tool functions for stat, download, copy and move, so nothing is reimplemented. `upload` is the only new Graph code.

**Upload:** reuses the primitives in the existing `web/skills/_m365/file_transfer.py` (`Source`, `safe_filename`, chunked upload session, size verification, never-overwrite), which today only addresses folders by path. A new `store_in_folder` addresses a folder by `drive_id` + `folder_id`, percent-encodes the name, uses simple PUT up to 4 MB and an upload session above that, and uses `conflictBehavior=rename` so an existing file is never overwritten. Existing `store` behaviour is unchanged.

**Tools:**

| Tool | Purpose |
|---|---|
| `file_upload` | Upload a local file to a folder ref (path guard applies) |
| `file_transfer` | `mode` = `move` or `copy`, source ref, destination folder ref |

Stat and download are not added as new tools: `get_onedrive_item` and `download_onedrive_file` already take `drive_id` + `item_id` and stay the entry points. A neutral `file_info`/`file_download` alias would be pure duplication until a second provider exists; adding one then is a one-function change.

### `file_transfer` flow

1. `copy` mode: server-side copy; if it fails, go to step 4.
2. `move` mode: if the source drive is another person's OneDrive (Graph `driveType` is `business` or `personal` and its id differs from the user's `/me/drive` id, or the check cannot be made), perform a copy instead and say so (`reason: "not_owner"`). SharePoint libraries (`documentLibrary`) and the user's own drive attempt the native move.
3. On `locked`, retry the move twice (3s, then 6s). If still locked, do a server-side copy.
4. If the copy fails with anything other than `forbidden` or `not_found`, download the source to `~/Downloads` (the user's stated fallback, with a numeric suffix if the name is taken, never overwriting a local file) and upload it to the destination folder.
5. Verify the destination: confirm the item by ID, or if the copy is still pending list the destination folder for the name and size.

Result:

```
{status: "moved" | "copied" | "pending" | "failed",
 method: "native_move" | "server_copy" | "download_upload",
 original_remains: bool,
 reason: "locked" | "not_owner" | null,
 dest: {drive_id, item_id, name, web_url},
 local_copy: path | null}
```

When `original_remains` is true the agent tells the user the original is still in place and that they can remove it themselves.

### Safety

- Local paths go through the existing `guard_path_args`.
- Uploads and copies write only to destinations the user named in the request.
- No tool deletes anything.

### Skill guides

`onedrive/SKILL.md` gains move, copy, lock and Teams-attachment guidance and points to `file_upload` and `file_transfer`. The false "upload" claim is corrected. `m365-onedrive/SKILL.md` gets a cross-reference.

### UI fixes

- `.ask-user-option { white-space: normal; }` with `overflow-wrap: anywhere` on the label and description.
- Permission approval: `_PENDING_DEP_APPROVALS` (`web/routes/chat.py`) is in-memory, one-shot and expires after 600s, so a backend restart, a long wait or a double click all produce the 404 the user saw. On a failed grant the client re-sends the saved request so the server issues a fresh permission card; nothing is auto-granted.

## Testing

- Unit (mocked Graph): move 423 then copy fallback; copy with async monitor and no auth header; pending copy resolved by listing; copy failure then download+upload; large-file upload session; name encoding; non-owner source performs copy.
- Existing `test_onedrive_file_routing.py`, `test_graph_id_encoding.py` and `test_secrets_guard.py` must pass unchanged.
- Real tenant: Teams-attached file held open in Word, moved to a OneDrive folder.
- Browser: option card with long descriptions renders wrapped.
